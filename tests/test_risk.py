"""Tests for risk management."""

import pytest

from src.portfolio.protected_assets import ProtectedAssetError, ProtectedAssets
from src.risk.position_sizer import PositionSizer
from src.risk.risk_manager import RiskManager
from src.risk.stop_loss import StopLossManager


class TestProtectedAssets:
    def test_shib_is_protected(self):
        pa = ProtectedAssets({"protected_assets": ["SHIB", "BTC"]})
        assert pa.is_protected("SHIB-USD")
        with pytest.raises(ProtectedAssetError):
            pa.check("SHIB-USD")

    def test_btc_is_protected(self):
        pa = ProtectedAssets({"protected_assets": ["SHIB", "BTC"]})
        assert pa.is_protected("BTC-USD")
        with pytest.raises(ProtectedAssetError):
            pa.check("BTC-USD")

    def test_eth_is_allowed(self):
        pa = ProtectedAssets({"protected_assets": ["SHIB", "BTC"]})
        assert not pa.is_protected("ETH-USD")
        pa.check("ETH-USD")  # should not raise

    def test_case_insensitive(self):
        pa = ProtectedAssets({"protected_assets": ["shib", "btc"]})
        assert pa.is_protected("SHIB-USD")
        assert pa.is_protected("BTC-USD")


class TestPositionSizer:
    def test_two_percent_rule(self):
        config = {"risk": {"max_position_pct": 0.02}}
        sizer = PositionSizer(config)
        result = sizer.calculate(capital=300.0, price=2000.0)
        assert result["usd_amount"] == 6.0  # 2% of 300
        assert abs(result["base_size"] - 0.003) < 0.0001

    def test_scales_with_capital(self):
        config = {"risk": {"max_position_pct": 0.02}}
        sizer = PositionSizer(config)
        r1 = sizer.calculate(capital=300.0, price=100.0)
        r2 = sizer.calculate(capital=600.0, price=100.0)
        assert r2["usd_amount"] == r1["usd_amount"] * 2


class TestRiskManager:
    def _make_rm(self, **overrides):
        config = {
            "risk": {
                "max_open_positions": 3,
                "daily_loss_limit_pct": 0.05,
                "daily_loss_limit_usd": 15.0,
            },
            "capital": {"initial_usd": 300.0},
            "protected_assets": ["SHIB", "BTC"],
        }
        config["risk"].update(overrides)
        pa = ProtectedAssets(config)
        return RiskManager(config, pa)

    def test_blocks_protected_asset(self):
        rm = self._make_rm()
        ok, reason = rm.can_trade("SHIB-USD", 0)
        assert not ok
        assert "protected" in reason.lower()

    def test_blocks_max_positions(self):
        rm = self._make_rm(max_open_positions=2)
        ok, reason = rm.can_trade("ETH-USD", 2)
        assert not ok
        assert "position" in reason.lower()

    def test_allows_valid_trade(self):
        rm = self._make_rm()
        ok, reason = rm.can_trade("ETH-USD", 0)
        assert ok
        assert reason == ""

    def test_daily_loss_limit_usd(self):
        rm = self._make_rm(daily_loss_limit_usd=10.0)
        rm.record_loss(5.0)
        ok, _ = rm.can_trade("ETH-USD", 0)
        assert ok

        rm.record_loss(6.0)  # total 11 > 10
        ok, reason = rm.can_trade("ETH-USD", 0)
        assert not ok
        assert "paused" in reason.lower()

    def test_daily_loss_limit_pct(self):
        rm = self._make_rm(daily_loss_limit_pct=0.02, daily_loss_limit_usd=999)
        # 2% of 300 = $6
        rm.record_loss(7.0)
        assert rm.is_paused


class TestStopLossManager:
    def _make_slm(self):
        config = {
            "risk": {
                "stop_loss_pct": 0.025,
                "take_profit_pct": 0.04,
                "trailing_stop_activate_pct": 0.03,
                "trailing_stop_distance_pct": 0.015,
            }
        }
        return StopLossManager(config)

    def test_stop_loss_triggered(self):
        slm = self._make_slm()
        slm.register("ETH-USD", 100.0, 97.5, 104.0)
        assert slm.check("ETH-USD", 97.0) == "stop_loss"

    def test_take_profit_triggered(self):
        slm = self._make_slm()
        slm.register("ETH-USD", 100.0, 97.5, 104.0)
        assert slm.check("ETH-USD", 104.5) == "take_profit"

    def test_trailing_stop(self):
        slm = self._make_slm()
        slm.register("ETH-USD", 100.0, 97.5, 104.0)

        # Price goes up 3% → activates trailing
        assert slm.check("ETH-USD", 103.1) is None
        state = slm.get_state("ETH-USD")
        assert state.trailing_active

        # Price goes up more
        assert slm.check("ETH-USD", 103.5) is None

        # Price drops within trailing distance
        result = slm.check("ETH-USD", 101.5)
        assert result == "trailing_stop"

    def test_no_trigger_in_range(self):
        slm = self._make_slm()
        slm.register("ETH-USD", 100.0, 97.5, 104.0)
        assert slm.check("ETH-USD", 100.5) is None
        assert slm.check("ETH-USD", 99.0) is None
        assert slm.check("ETH-USD", 101.0) is None
