"""Tests for database models and repository."""

import os
import tempfile

import pytest

from src.database.models import init_db
from src.database.repository import Repository
from src.portfolio.portfolio_manager import ClosedTrade
from src.strategy.signal_generator import Signal, SignalType


@pytest.fixture
def repo():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        _, Session = init_db(db_path)
        yield Repository(Session)


class TestRepository:
    def test_save_and_get_trade(self, repo):
        trade_id = repo.save_trade_open(
            product_id="ETH-USD",
            entry_price=2000.0,
            size=0.003,
            usd_cost=6.0,
            stop_loss=1950.0,
            take_profit=2080.0,
            order_id="test-001",
            paper=True,
        )
        assert trade_id > 0

        trades = repo.get_trades(limit=10)
        assert len(trades) == 1
        assert trades[0].product_id == "ETH-USD"

    def test_save_trade_close(self, repo):
        repo.save_trade_open(
            product_id="ETH-USD",
            entry_price=2000.0,
            size=0.003,
            usd_cost=6.0,
            stop_loss=1950.0,
            take_profit=2080.0,
            order_id="test-001",
            paper=True,
        )
        closed = ClosedTrade(
            product_id="ETH-USD",
            entry_price=2000.0,
            exit_price=2080.0,
            size=0.003,
            usd_cost=6.0,
            usd_return=6.24,
            pnl=0.24,
            pnl_pct=0.04,
            exit_reason="take_profit",
        )
        repo.save_trade_close("ETH-USD", closed)

        trades = repo.get_trades()
        assert trades[0].exit_price == 2080.0
        assert trades[0].pnl == 0.24

    def test_save_signal(self, repo):
        signal = Signal(
            signal_type=SignalType.BUY,
            product_id="SOL-USD",
            price=100.0,
            stop_loss=97.5,
            take_profit=104.0,
            confidence=0.75,
            reasons=["RSI oversold", "EMA bullish"],
        )
        repo.save_signal(signal, acted_on=True)

    def test_daily_performance(self, repo):
        repo.save_daily_performance("2025-01-15", {
            "starting_capital": 300.0,
            "ending_capital": 302.50,
            "trades_count": 3,
            "wins": 2,
            "losses": 1,
            "realized_pnl": 2.50,
        })
        records = repo.get_daily_performance(days=7)
        assert len(records) == 1
        assert records[0].realized_pnl == 2.50
