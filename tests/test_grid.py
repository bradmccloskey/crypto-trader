"""Tests for grid trading strategy."""

import pytest
import pandas as pd

from src.strategy.grid_strategy import GridStrategy, GridLevel, GridState


@pytest.fixture
def grid_config():
    return {
        "grid": {
            "enabled": True,
            "pairs": ["ETH-USD", "SOL-USD"],
            "grid_capital_usd": 150.0,
            "num_levels": 5,
            "grid_spacing_pct": 0.01,
            "order_size_usd": 10.0,
            "rebalance_threshold_pct": 0.05,
        }
    }


@pytest.fixture
def grid(grid_config):
    return GridStrategy(grid_config)


class TestGridLevelCalculation:
    def test_correct_number_of_levels(self, grid):
        levels = grid.calculate_grid_levels(1000.0)
        assert len(levels) == 10  # 5 above + 5 below

    def test_buy_levels_below_center(self, grid):
        levels = grid.calculate_grid_levels(1000.0)
        buys = [(i, p, s) for i, p, s in levels if s == "BUY"]
        assert len(buys) == 5
        for idx, price, side in buys:
            assert idx < 0
            assert price < 1000.0

    def test_sell_levels_above_center(self, grid):
        levels = grid.calculate_grid_levels(1000.0)
        sells = [(i, p, s) for i, p, s in levels if s == "SELL"]
        assert len(sells) == 5
        for idx, price, side in sells:
            assert idx > 0
            assert price > 1000.0

    def test_spacing_is_correct(self, grid):
        center = 1000.0
        levels = grid.calculate_grid_levels(center)
        buys = sorted([(i, p) for i, p, s in levels if s == "BUY"], key=lambda x: x[0])
        # Level -1 should be 1% below center
        assert abs(buys[-1][1] - center * 0.99) < 0.01

    def test_levels_sorted_by_index(self, grid):
        levels = grid.calculate_grid_levels(1000.0)
        indices = [i for i, _, _ in levels]
        assert indices == sorted(indices)


class TestGridInitialization:
    def test_initialize_creates_state(self, grid):
        state = grid.initialize_grid("ETH-USD", 2000.0)
        assert state.product_id == "ETH-USD"
        assert state.center_price == 2000.0
        assert len(state.levels) == 10

    def test_initialize_sets_base_sizes(self, grid):
        state = grid.initialize_grid("ETH-USD", 2000.0)
        for level in state.levels.values():
            expected_size = 10.0 / level.price
            assert abs(level.base_size - expected_size) < 0.0001

    def test_levels_start_as_pending(self, grid):
        state = grid.initialize_grid("ETH-USD", 2000.0)
        for level in state.levels.values():
            assert level.status == "pending"

    def test_grid_stored_in_grids_dict(self, grid):
        grid.initialize_grid("ETH-USD", 2000.0)
        assert "ETH-USD" in grid.grids


class TestRebalance:
    def test_needs_rebalance_when_no_grid(self, grid):
        assert grid.needs_rebalance("ETH-USD", 2000.0) is True

    def test_no_rebalance_within_threshold(self, grid):
        grid.initialize_grid("ETH-USD", 2000.0)
        # 1% drift < 5% threshold
        assert grid.needs_rebalance("ETH-USD", 2020.0) is False

    def test_rebalance_beyond_threshold(self, grid):
        grid.initialize_grid("ETH-USD", 2000.0)
        # 6% drift > 5% threshold
        assert grid.needs_rebalance("ETH-USD", 2120.0) is True

    def test_clear_preserves_pnl(self, grid):
        grid.initialize_grid("ETH-USD", 2000.0)
        grid.grids["ETH-USD"].realized_pnl = 5.50
        preserved = grid.clear_grid("ETH-USD")
        assert preserved == 5.50


class TestPaperFills:
    def test_buy_fills_when_low_hits_level(self, grid):
        grid.initialize_grid("ETH-USD", 100.0)
        # Mark all as open
        for level in grid.get_pending_levels("ETH-USD"):
            grid.mark_level_open("ETH-USD", level.index, f"ord-{level.index}")

        # Price drops to 98 — should fill level -1 (99.0) and level -2 (98.0)
        filled = grid.check_fills_paper("ETH-USD", 98.0, low=98.0, high=98.0)
        buy_fills = [f for f in filled if f.side == "BUY"]
        assert len(buy_fills) >= 2

    def test_sell_fills_when_high_hits_level(self, grid):
        grid.initialize_grid("ETH-USD", 100.0)
        for level in grid.get_pending_levels("ETH-USD"):
            grid.mark_level_open("ETH-USD", level.index, f"ord-{level.index}")

        # Price rises to 102 — should fill level +1 (101.0) and level +2 (102.0)
        filled = grid.check_fills_paper("ETH-USD", 102.0, low=102.0, high=102.0)
        sell_fills = [f for f in filled if f.side == "SELL"]
        assert len(sell_fills) >= 2

    def test_no_fill_on_pending_orders(self, grid):
        grid.initialize_grid("ETH-USD", 100.0)
        # Don't mark as open — still pending
        filled = grid.check_fills_paper("ETH-USD", 95.0, low=95.0, high=95.0)
        assert len(filled) == 0

    def test_filled_level_changes_status(self, grid):
        grid.initialize_grid("ETH-USD", 100.0)
        for level in grid.get_pending_levels("ETH-USD"):
            grid.mark_level_open("ETH-USD", level.index, f"ord-{level.index}")

        grid.check_fills_paper("ETH-USD", 99.0, low=99.0, high=99.0)
        state = grid.grids["ETH-USD"]
        filled_levels = [l for l in state.levels.values() if l.status == "filled"]
        assert len(filled_levels) >= 1


class TestHandleFill:
    def test_buy_fill_creates_sell(self, grid):
        grid.initialize_grid("ETH-USD", 100.0)
        state = grid.grids["ETH-USD"]
        buy_level = state.levels[-1]  # level -1: BUY at 99
        buy_level.status = "filled"

        new_level = grid.handle_fill("ETH-USD", buy_level)
        assert new_level is not None
        assert new_level.side == "SELL"
        assert new_level.price > buy_level.price

    def test_sell_fill_creates_buy(self, grid):
        grid.initialize_grid("ETH-USD", 100.0)
        state = grid.grids["ETH-USD"]
        sell_level = state.levels[1]  # level +1: SELL at 101
        sell_level.status = "filled"

        new_level = grid.handle_fill("ETH-USD", sell_level)
        assert new_level is not None
        assert new_level.side == "BUY"
        assert new_level.price < sell_level.price

    def test_sell_fill_adds_pnl(self, grid):
        grid.initialize_grid("ETH-USD", 100.0)
        state = grid.grids["ETH-USD"]
        sell_level = state.levels[1]
        sell_level.status = "filled"

        grid.handle_fill("ETH-USD", sell_level)
        assert state.realized_pnl > 0


class TestGridSummary:
    def test_summary_structure(self, grid):
        grid.initialize_grid("ETH-USD", 2000.0)
        for level in grid.get_pending_levels("ETH-USD"):
            grid.mark_level_open("ETH-USD", level.index, f"ord-{level.index}")

        summary = grid.get_grid_summary("ETH-USD")
        assert summary["product_id"] == "ETH-USD"
        assert summary["center_price"] == 2000.0
        assert summary["open_buys"] == 5
        assert summary["open_sells"] == 5
        assert summary["realized_pnl"] == 0.0

    def test_summary_empty_for_unknown_pair(self, grid):
        assert grid.get_grid_summary("UNKNOWN") == {}


class TestCapitalCalculation:
    def test_max_capital_required(self, grid):
        # 5 levels * $10/order * 2 pairs = $100
        assert grid.max_capital_required() == 100.0
