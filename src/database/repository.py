"""Database CRUD operations."""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.database.models import DailyPerformance, GridOrder, SignalLog, Trade
from src.portfolio.portfolio_manager import ClosedTrade
from src.strategy.signal_generator import Signal
from src.utils.logger import setup_logger

log = setup_logger("db-repo")


class Repository:
    """Database access layer for trades, signals, and daily performance."""

    def __init__(self, session_factory):
        self.Session = session_factory

    # ── Trades ───────────────────────────────────────────────────────

    def save_trade_open(self, product_id: str, entry_price: float, size: float,
                        usd_cost: float, stop_loss: float, take_profit: float,
                        order_id: str, paper: bool) -> int:
        with self.Session() as session:
            trade = Trade(
                product_id=product_id,
                side="BUY",
                entry_price=entry_price,
                size=size,
                usd_cost=usd_cost,
                stop_loss=stop_loss,
                take_profit=take_profit,
                order_id=order_id,
                paper=1 if paper else 0,
            )
            session.add(trade)
            session.commit()
            log.debug(f"Saved open trade #{trade.id} for {product_id}")
            return trade.id

    def save_trade_close(self, product_id: str, closed: ClosedTrade):
        with self.Session() as session:
            # Find the most recent open trade for this product
            trade = (
                session.query(Trade)
                .filter(Trade.product_id == product_id, Trade.exit_price.is_(None))
                .order_by(Trade.id.desc())
                .first()
            )
            if trade:
                trade.exit_price = closed.exit_price
                trade.usd_return = closed.usd_return
                trade.pnl = closed.pnl
                trade.pnl_pct = closed.pnl_pct
                trade.exit_reason = closed.exit_reason
                trade.exit_time = datetime.now(timezone.utc)
                session.commit()
                log.debug(f"Saved close for trade #{trade.id}")

    def get_trades(self, limit: int = 50) -> list[Trade]:
        with self.Session() as session:
            return session.query(Trade).order_by(Trade.id.desc()).limit(limit).all()

    def get_open_trades(self) -> list[Trade]:
        with self.Session() as session:
            return session.query(Trade).filter(Trade.exit_price.is_(None)).all()

    # ── Signals ──────────────────────────────────────────────────────

    def save_signal(self, signal: Signal, acted_on: bool = False):
        with self.Session() as session:
            entry = SignalLog(
                product_id=signal.product_id,
                signal_type=signal.signal_type.value,
                price=signal.price,
                confidence=signal.confidence,
                reasons=json.dumps(signal.reasons),
                acted_on=1 if acted_on else 0,
            )
            session.add(entry)
            session.commit()

    # ── Daily Performance ────────────────────────────────────────────

    def save_daily_performance(self, date_str: str, data: dict):
        # Map summary keys to DailyPerformance column names
        mapped = {
            "starting_capital": data.get("starting_capital"),
            "ending_capital": data.get("capital"),
            "trades_count": data.get("total_trades", 0),
            "wins": data.get("wins", 0),
            "losses": data.get("losses", 0),
            "realized_pnl": data.get("realized_pnl", 0),
            "unrealized_pnl": data.get("unrealized_pnl", 0),
            "max_drawdown": data.get("max_drawdown", 0),
        }
        # Drop None values so defaults apply
        mapped = {k: v for k, v in mapped.items() if v is not None}

        with self.Session() as session:
            existing = session.query(DailyPerformance).filter_by(date=date_str).first()
            if existing:
                for k, v in mapped.items():
                    setattr(existing, k, v)
            else:
                entry = DailyPerformance(date=date_str, **mapped)
                session.add(entry)
            session.commit()

    def get_daily_performance(self, days: int = 30) -> list[DailyPerformance]:
        with self.Session() as session:
            return (
                session.query(DailyPerformance)
                .order_by(DailyPerformance.date.desc())
                .limit(days)
                .all()
            )

    # ── Grid Orders ───────────────────────────────────────────────────

    def save_grid_order(self, product_id: str, side: str, level_price: float,
                        base_size: float, order_id: str, grid_center: float,
                        level_index: int, paper: bool, status: str = "open") -> int:
        with self.Session() as session:
            order = GridOrder(
                product_id=product_id,
                side=side,
                level_price=level_price,
                base_size=base_size,
                order_id=order_id,
                grid_center=grid_center,
                level_index=level_index,
                paper=1 if paper else 0,
                status=status,
            )
            session.add(order)
            session.commit()
            log.debug(f"Saved grid order #{order.id} {side} {product_id} @ ${level_price:.4f}")
            return order.id

    def fill_grid_order(self, order_id: str, fill_price: float, pnl: float = 0.0):
        with self.Session() as session:
            order = session.query(GridOrder).filter_by(order_id=order_id, status="open").first()
            if order:
                order.status = "filled"
                order.fill_price = fill_price
                order.pnl = pnl
                order.filled_at = datetime.now(timezone.utc)
                session.commit()

    def cancel_grid_orders(self, product_id: str):
        with self.Session() as session:
            orders = session.query(GridOrder).filter(
                GridOrder.product_id == product_id,
                GridOrder.status == "open"
            ).all()
            for order in orders:
                order.status = "cancelled"
            session.commit()
            log.debug(f"Cancelled {len(orders)} grid orders for {product_id}")

    def get_open_grid_orders(self, product_id: str = None) -> list[GridOrder]:
        with self.Session() as session:
            q = session.query(GridOrder).filter_by(status="open")
            if product_id:
                q = q.filter_by(product_id=product_id)
            return q.all()

    def get_grid_pnl(self, product_id: str = None) -> float:
        with self.Session() as session:
            q = session.query(GridOrder).filter_by(status="filled")
            if product_id:
                q = q.filter_by(product_id=product_id)
            orders = q.all()
            return sum(o.pnl or 0 for o in orders)
