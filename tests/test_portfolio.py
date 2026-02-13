"""Tests for portfolio management."""

import pytest

from src.portfolio.portfolio_manager import PortfolioManager


class TestPortfolioManager:
    def _make_pm(self, capital=300.0):
        return PortfolioManager({"capital": {"initial_usd": capital}})

    def test_open_position_deducts_capital(self):
        pm = self._make_pm(300.0)
        pm.open_position("ETH-USD", 2000.0, 0.003, 6.0, 1950.0, 2080.0)
        assert pm.capital == 294.0
        assert pm.open_position_count == 1

    def test_close_position_adds_capital(self):
        pm = self._make_pm(300.0)
        pm.open_position("ETH-USD", 2000.0, 0.003, 6.0, 1950.0, 2080.0)
        trade = pm.close_position("ETH-USD", 2100.0, "take_profit")
        assert trade is not None
        assert trade.pnl > 0
        assert pm.capital > 294.0  # got back more than cost
        assert pm.open_position_count == 0

    def test_close_nonexistent_returns_none(self):
        pm = self._make_pm()
        result = pm.close_position("FAKE-USD", 100.0, "test")
        assert result is None

    def test_pnl_tracking(self):
        pm = self._make_pm(300.0)
        pm.open_position("ETH-USD", 100.0, 0.06, 6.0, 97.5, 104.0)
        pm.close_position("ETH-USD", 104.0, "take_profit")
        assert pm.win_count == 1
        assert pm.loss_count == 0
        assert pm.total_pnl > 0

    def test_multiple_positions(self):
        pm = self._make_pm(300.0)
        pm.open_position("ETH-USD", 2000.0, 0.003, 6.0, 1950.0, 2080.0)
        pm.open_position("SOL-USD", 100.0, 0.06, 6.0, 97.5, 104.0)
        assert pm.open_position_count == 2
        assert pm.capital == 288.0

    def test_unrealized_pnl(self):
        pm = self._make_pm(300.0)
        pm.open_position("ETH-USD", 2000.0, 0.003, 6.0, 1950.0, 2080.0)
        # Price goes up
        pnl = pm.unrealized_pnl({"ETH-USD": 2100.0})
        assert pnl > 0

    def test_summary(self):
        pm = self._make_pm(300.0)
        pm.open_position("ETH-USD", 100.0, 0.06, 6.0, 97.5, 104.0)
        pm.close_position("ETH-USD", 104.0, "take_profit")
        s = pm.summary()
        assert "capital" in s
        assert "wins" in s
        assert s["wins"] == 1
