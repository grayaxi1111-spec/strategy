import logging
import os

import pandas as pd
import pytest

from quant_tool.backtest import Backtest
from quant_tool.costs import CostModel
from quant_tool.strategies.base import Strategy, SignalType

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "quant_tool", "config.yaml")

# 與 config.yaml 相同的成本參數,直接以 dict 測 from_config
COSTS_CFG = {
    'TW': {
        'buy_commission_rate': 0.001425,
        'commission_discount': 0.6,
        'sell_commission_rate': 0.001425,
        'sell_tax_rate': 0.001,
    },
    'US': {
        'buy_slippage': 0.0005,
        'sell_slippage': 0.0005,
    },
}

TW_BUY_RATE = 0.001425 * 0.6            # 手續費 × 折扣
TW_SELL_RATE = 0.001425 * 0.6 + 0.001   # 手續費 × 折扣 + 證交稅
US_RATE = 0.0005                        # 單邊滑價


class ScriptedStrategy(Strategy):
    """依預設清單逐日回傳訊號。"""
    def __init__(self, signals):
        super().__init__()
        self.signals = list(signals)
        self.i = 0

    def generate_signal(self, row, account):
        sig = self.signals[self.i] if self.i < len(self.signals) else SignalType.HOLD
        self.i += 1
        return sig


def make_df(opens, closes, start='2024-01-01'):
    n = len(opens)
    dates = pd.bdate_range(start=start, periods=n)
    return pd.DataFrame({
        'date': dates,
        'open': [float(x) for x in opens],
        'high': [float(x) for x in closes],
        'low': [float(x) for x in opens],
        'close': [float(x) for x in closes],
        'volume': [1000] * n,
    })


def test_tw_buy_cost():
    """0050 買入成本 = 手續費 0.1425% × 折扣。"""
    model = CostModel.from_config(COSTS_CFG, 'TW')
    assert model.buy_rate == pytest.approx(TW_BUY_RATE)
    assert model.buy_cost(100000.0) == pytest.approx(100000.0 * TW_BUY_RATE)  # 85.5


def test_tw_sell_cost():
    """0050 賣出成本 = 手續費 0.1425% × 折扣 + 證交稅 0.1%。"""
    model = CostModel.from_config(COSTS_CFG, 'TW')
    assert model.sell_rate == pytest.approx(TW_SELL_RATE)
    assert model.sell_cost(100000.0) == pytest.approx(100000.0 * TW_SELL_RATE)  # 185.5


def test_us_buy_sell_cost():
    """VOO 買賣各 0.05% 滑價。"""
    model = CostModel.from_config(COSTS_CFG, 'US')
    assert model.buy_rate == pytest.approx(US_RATE)
    assert model.sell_rate == pytest.approx(US_RATE)
    assert model.round_trip_rate == pytest.approx(0.001)


def test_commission_discount_configurable():
    """折扣比例可配置:改折扣後買賣手續費同步變動。"""
    cfg = {'TW': dict(COSTS_CFG['TW'], commission_discount=0.28)}
    model = CostModel.from_config(cfg, 'TW')
    assert model.buy_rate == pytest.approx(0.001425 * 0.28)
    assert model.sell_rate == pytest.approx(0.001425 * 0.28 + 0.001)


def test_from_yaml_reads_real_config():
    """成本參數可直接從專案 config.yaml 讀取。"""
    tw = CostModel.from_yaml(CONFIG_PATH, 'TW')
    us = CostModel.from_yaml(CONFIG_PATH, 'US')
    assert tw.buy_rate == pytest.approx(TW_BUY_RATE)
    assert tw.sell_rate == pytest.approx(TW_SELL_RATE)
    assert us.round_trip_rate == pytest.approx(0.001)


def test_tw_round_trip_warning(caplog):
    """0050 來回成本約 0.27%,建立模型時必須記錄警告(吃掉策略 B 10~30% 獲利)。"""
    with caplog.at_level(logging.WARNING, logger='quant_tool.costs'):
        model = CostModel.from_config(COSTS_CFG, 'TW')
    assert model.round_trip_rate == pytest.approx(TW_BUY_RATE + TW_SELL_RATE)  # ~0.271%
    assert '策略 B' in caplog.text and 'VOO' in caplog.text


def test_us_no_warning(caplog):
    """VOO 來回成本僅 0.1%,不應觸發警告。"""
    with caplog.at_level(logging.WARNING, logger='quant_tool.costs'):
        CostModel.from_config(COSTS_CFG, 'US')
    assert caplog.text == ''


def test_backtest_applies_round_trip_costs():
    """回測引擎買賣一趟後,淨值損失需等於來回成本。"""
    df = make_df(opens=[100, 100, 100], closes=[100, 100, 100])
    strat = ScriptedStrategy([SignalType.BUY, SignalType.SELL, SignalType.HOLD])
    model = CostModel.from_config(COSTS_CFG, 'TW')
    result = Backtest(strat, initial_capital=10000.0, warmup_days=0,
                      cost_model=model).run(df)

    trades = result.trades
    assert len(trades) == 2

    # 買入:總流出 10000,股數已扣買入成本
    expected_shares = 10000.0 / (100.0 * (1 + TW_BUY_RATE))
    buy = trades.iloc[0]
    assert buy['shares'] == pytest.approx(expected_shares)
    assert buy['fee'] == pytest.approx(10000.0 - expected_shares * 100.0)

    # 賣出:實收 = 市值 × (1 - 賣出費率)
    gross = expected_shares * 100.0
    sell = trades.iloc[1]
    assert sell['fee'] == pytest.approx(gross * TW_SELL_RATE)
    assert sell['value'] == pytest.approx(gross * (1 - TW_SELL_RATE))

    # 價格全程不變 → 淨值損失即為來回成本(~0.27%)
    expected_final = gross * (1 - TW_SELL_RATE)
    assert result.final_equity == pytest.approx(expected_final)
    assert result.total_return == pytest.approx(expected_final / 10000.0 - 1.0)


def test_backtest_default_is_frictionless():
    """未提供 cost_model 時維持無摩擦成交(fee = 0)。"""
    df = make_df(opens=[100, 100, 100], closes=[100, 100, 100])
    strat = ScriptedStrategy([SignalType.BUY, SignalType.SELL, SignalType.HOLD])
    result = Backtest(strat, initial_capital=10000.0, warmup_days=0).run(df)

    assert (result.trades['fee'] == 0.0).all()
    assert result.final_equity == pytest.approx(10000.0)
