"""Performance reporting for backtest results."""

from src.backtesting.backtest_engine import BacktestResult
from src.utils.logger import setup_logger

log = setup_logger("performance")


def print_report(result: BacktestResult):
    """Print a formatted backtest performance report."""
    print("\n" + "=" * 60)
    print("  BACKTEST PERFORMANCE REPORT")
    print("=" * 60)
    print(f"  Starting Capital:   ${result.starting_capital:,.2f}")
    print(f"  Ending Capital:     ${result.ending_capital:,.2f}")
    print(f"  Total P&L:          ${result.total_pnl:+,.2f}")
    print(f"  Total Return:       {result.total_return_pct:+.2f}%")
    print("-" * 60)
    print(f"  Total Trades:       {len(result.trades)}")
    print(f"  Wins:               {result.win_count}")
    print(f"  Losses:             {result.loss_count}")
    print(f"  Win Rate:           {result.win_rate:.0%}")
    print(f"  Avg Win:            ${result.avg_win:+,.2f}")
    print(f"  Avg Loss:           ${result.avg_loss:+,.2f}")
    print("-" * 60)
    print(f"  Profit Factor:      {result.profit_factor:.2f}")
    print(f"  Sharpe Ratio:       {result.sharpe_ratio:.2f}")
    print(f"  Max Drawdown:       {result.max_drawdown_pct:.2f}%")
    print("=" * 60)

    if result.trades:
        # Breakdown by exit reason
        reasons = {}
        for t in result.trades:
            reasons.setdefault(t.exit_reason, []).append(t)
        print("\n  Exit Reason Breakdown:")
        for reason, trades in sorted(reasons.items()):
            count = len(trades)
            pnl = sum(t.pnl for t in trades)
            print(f"    {reason:20s}  {count:3d} trades  ${pnl:+8.2f}")

        # Breakdown by product
        products = {}
        for t in result.trades:
            products.setdefault(t.product_id, []).append(t)
        print("\n  Product Breakdown:")
        for pid, trades in sorted(products.items()):
            count = len(trades)
            pnl = sum(t.pnl for t in trades)
            wins = sum(1 for t in trades if t.pnl > 0)
            print(f"    {pid:12s}  {count:3d} trades  W:{wins} L:{count - wins}  ${pnl:+8.2f}")

    print()
