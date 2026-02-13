# Crypto Trading Bot

An algorithmic cryptocurrency trading bot for the Coinbase Advanced Trade API. Uses multi-indicator technical analysis to generate trade signals, with position sizing, stop-losses, trailing stops, daily loss limits, and real-time SMS notifications.

Built for conservative automated trading — strict risk management ensures no single trade risks more than 2% of capital, and the bot pauses itself if daily losses exceed a configurable threshold.

## Features

- **Multi-Indicator Signals** — RSI, EMA crossover, Bollinger Bands, and volume confirmation must agree before entering a trade
- **Risk Management** — 2% position sizing, max 3 open positions, daily loss limits, protected assets
- **Stop-Loss + Trailing Stop** — Every trade gets a fixed stop-loss; trailing stop activates at configurable profit threshold to lock in gains
- **Paper & Live Modes** — Test strategies with simulated trades on real market data before risking capital
- **Backtesting Engine** — Run strategy against 6+ months of historical data with performance metrics (Sharpe ratio, max drawdown, profit factor)
- **SMS Notifications** — Trade opens, closes, daily summaries, and error alerts via iMessage
- **Persistent Storage** — All trades, signals, and daily performance tracked in SQLite
- **Configurable** — All strategy parameters, risk limits, and trading pairs defined in YAML

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **API** | coinbase-advanced-py (Coinbase Advanced Trade) |
| **Analysis** | pandas, ta (technical indicators), numpy |
| **Database** | SQLAlchemy + SQLite |
| **Config** | PyYAML, python-dotenv |
| **Scheduling** | schedule (daily summaries) |
| **Notifications** | iMessage via osascript queue |
| **Data Format** | Parquet (historical candles) |

## Architecture

```
┌─────────────────────────────────────────────┐
│             Main Bot Loop (60s)             │
│         _check_exits → _check_entries       │
├──────────┬────────────┬─────────────────────┤
│ Market   │  Strategy  │    Risk Manager     │
│ Data     │  Engine    │  ┌───────────────┐  │
│ (OHLCV)  │  (signals) │  │ Position Sizer│  │
│          │            │  │ Stop-Loss Mgr │  │
│          │            │  │ Daily Limits  │  │
│          │            │  │ Protected Assets│ │
├──────────┴────────────┴──┴───────────────┴──┤
│        Order Executor (paper / live)        │
├─────────────────────────────────────────────┤
│  Coinbase API  │  SQLite DB  │  SMS Queue   │
└─────────────────────────────────────────────┘
```

## Quick Start

```bash
# Clone and install
git clone https://github.com/bradmccloskey/crypto-trader.git
cd crypto-trader
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Coinbase API keys

# Test API connection
python scripts/test_connection.py

# Run backtest on historical data
python scripts/download_historical.py
python scripts/run_backtest.py

# Start paper trading
BOT_MODE=paper python src/main.py
```

## Configuration

**config/config.yaml** controls all strategy and risk parameters:

```yaml
trading_pairs:
  - ETH-USD
  - SOL-USD
  - AVAX-USD
  - DOGE-USD
  - ADA-USD
  - XRP-USD
  - DOT-USD

strategy:
  min_confirmations: 3          # indicators that must agree
  candle_granularity: ONE_HOUR
  lookback_candles: 100

risk:
  max_position_pct: 0.02        # 2% of capital per trade
  max_open_positions: 3
  daily_loss_limit_pct: 0.05    # pause trading at 5% daily loss
  daily_loss_limit_usd: 15.0    # or $15, whichever hit first
  stop_loss_pct: 0.015          # 1.5% stop-loss
  take_profit_pct: 0.08         # 8% take-profit
  trailing_stop_activate_pct: 0.02   # activate at 2% gain
  trailing_stop_distance_pct: 0.008  # trail by 0.8%
```

## Signal Logic

A BUY signal requires **3 of 4 indicators** to confirm:

| Indicator | Buy Condition |
|-----------|--------------|
| **RSI (14)** | Below 20 (oversold) |
| **EMA (12/26)** | Fast EMA crosses above slow EMA |
| **Bollinger Bands** | Price near lower band |
| **Volume** | Current volume > 2.5x 20-period average |

## Project Structure

```
crypto-trader/
├── src/
│   ├── main.py                   # TradingBot orchestrator and main loop
│   ├── api/
│   │   ├── coinbase_client.py    # Coinbase API wrapper with precision handling
│   │   ├── market_data.py        # OHLCV fetching with disk cache
│   │   └── order_executor.py     # Paper and live order execution
│   ├── strategy/
│   │   ├── indicators.py         # RSI, EMA, Bollinger Bands, volume ratio
│   │   └── signal_generator.py   # Multi-indicator signal logic
│   ├── risk/
│   │   ├── risk_manager.py       # Pre-trade safety checks, daily loss tracking
│   │   ├── position_sizer.py     # 2% rule position sizing
│   │   └── stop_loss.py          # Stop-loss, take-profit, trailing stop
│   ├── portfolio/
│   │   ├── portfolio_manager.py  # Position tracking and P&L
│   │   └── protected_assets.py   # BTC/SHIB trade guard
│   ├── backtesting/
│   │   ├── backtest_engine.py    # Historical strategy simulation
│   │   └── performance.py        # Win rate, Sharpe ratio, drawdown
│   ├── database/
│   │   ├── models.py             # Trade, Signal, DailyPerformance tables
│   │   └── repository.py         # Database CRUD
│   └── notifications/
│       └── sms_notifier.py       # SMS via iMessage queue
├── config/config.yaml            # Strategy and risk parameters
├── scripts/
│   ├── test_connection.py        # Verify API credentials
│   ├── download_historical.py    # Fetch historical candles
│   ├── run_backtest.py           # Run strategy backtest
│   └── emergency_stop.py         # Kill switch
├── tests/                        # 40 unit tests (indicators, risk, signals, portfolio, DB)
├── data/                         # SQLite DB, historical parquet files, SMS queue
└── logs/                         # Daily rotating log files
```

## Risk Management Layers

1. **Protected Assets** — Configurable coins (e.g., BTC, SHIB) that the bot will never trade
2. **Daily Loss Limit** — Trading pauses automatically if daily loss exceeds threshold
3. **Position Limits** — Max 3 concurrent open positions
4. **Position Sizing** — Each trade limited to 2% of total capital
5. **Stop-Loss** — Automatic exit at 1.5% loss from entry
6. **Trailing Stop** — Activates at 2% profit, trails by 0.8% to lock in gains
7. **Volume Filter** — Requires 2.5x average volume to confirm signal strength

## SMS Notifications

The bot sends iMessage alerts for:
- Trade opened (pair, price, size, stop-loss, take-profit)
- Trade closed (P&L, exit reason)
- Daily loss limit reached (trading paused)
- Daily summary at 8 PM (capital, wins/losses, P&L)
- Bot errors or crashes

## Running as a Service (macOS)

```bash
# Install launchd service for 24/7 operation
cp scripts/com.crypto-trader.bot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.crypto-trader.bot.plist
```

## Environment Variables

```
COINBASE_API_KEY=your_cdp_api_key
COINBASE_API_SECRET=your_ec_private_key
SMS_PHONE_NUMBER=+1XXXXXXXXXX
BOT_MODE=paper                    # paper or live
```

## Requirements

- Python 3.11+
- Coinbase Advanced Trade API key (CDP format)
- macOS (for iMessage notifications; bot runs on any OS without SMS)
