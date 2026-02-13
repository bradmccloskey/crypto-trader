"""SQLAlchemy models for trade history and performance tracking."""

from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)

from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)  # BUY or SELL
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    size = Column(Float, nullable=False)
    usd_cost = Column(Float, nullable=False)
    usd_return = Column(Float)
    pnl = Column(Float)
    pnl_pct = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    exit_reason = Column(String)  # stop_loss, take_profit, trailing_stop, signal
    order_id = Column(String)
    paper = Column(Integer, default=1)  # 1=paper, 0=live
    entry_time = Column(DateTime, default=_utcnow)
    exit_time = Column(DateTime)
    created_at = Column(DateTime, default=_utcnow)


class SignalLog(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String, nullable=False, index=True)
    signal_type = Column(String, nullable=False)  # BUY, SELL, HOLD
    price = Column(Float, nullable=False)
    confidence = Column(Float)
    reasons = Column(String)  # JSON string
    acted_on = Column(Integer, default=0)  # 1 if a trade was placed
    created_at = Column(DateTime, default=_utcnow)


class DailyPerformance(Base):
    __tablename__ = "daily_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, nullable=False, unique=True)
    starting_capital = Column(Float)
    ending_capital = Column(Float)
    trades_count = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    realized_pnl = Column(Float, default=0)
    unrealized_pnl = Column(Float, default=0)
    max_drawdown = Column(Float, default=0)
    created_at = Column(DateTime, default=_utcnow)


def init_db(db_path: str = "data/trading.db"):
    """Create all tables and return engine + session factory."""
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return engine, Session
