import logging

import numpy as np
import pandas as pd
import pytest

from quant_tool import portfolio as pf
from quant_tool.costs import CostModel
from quant_tool.strategies.base import Strategy, SignalType


class ScriptedStrategy(Strategy):
    """測試用:依日期查表發訊號,其餘一律 HOLD。"""

    def __init__(self, script: dict = None):
        super().__init__()
        self.script = {pd.Timestamp(k): v for k, v in (script or {}).items()}

    def generate_signal(self, row, account) -> SignalType:
        return self.script.get(pd.Timestamp(row['date']), SignalType.HOLD)


def make_df(dates, prices):
    """open == close 的簡化行情,方便直接驗證帳務數字。"""
    prices = [float(p) for p in prices]
    return pd.DataFrame({'date': list(dates), 'open': prices, 'close': prices})


def make_portfolio(strategy_a=None, strategy_b=None, **kwargs):
    kwargs.setdefault('initial_capital', 1000.0)
    kwargs.setdefault('warmup_days', 0)
    return pf.Portfolio(strategy_a or ScriptedStrategy(),
                        strategy_b or ScriptedStrategy(), **kwargs)


def test_dual_ledger_initialization_50_50():
    """雙帳本初始化:預設各拿總資金 50%。"""
    dates = pd.bdate_range('2024-01-01', periods=5)
    result = make_portfolio().run(make_df(dates, [100] * 5))
    assert result.equity_a.iloc[0] == pytest.approx(500.0)
    assert result.equity_b.iloc[0] == pytest.approx(500.0)
    assert result.combined_equity.iloc[-1] == pytest.approx(1000.0)
    assert result.rebalances.empty  # 未跨季,不觸發再平衡
    assert result.result_a.initial_capital == pytest.approx(500.0)


def test_ledgers_are_independent():
    """兩帳本獨立記帳、獨立持倉:A 進場不影響 B。"""
    dates = pd.bdate_range('2024-01-01', periods=5)
    strat_a = ScriptedStrategy({dates[0]: SignalType.BUY})
    result = make_portfolio(strat_a, rebalance_frequency=None).run(
        make_df(dates, [100] * 5))
    # A 於次日開盤以 100 全倉買入 5 股;B 完全不動
    assert len(result.result_a.trades) == 1
    assert result.result_a.equity_curve['shares'].iloc[-1] == pytest.approx(5.0)
    assert result.result_b.trades.empty
    assert result.result_b.equity_curve['shares'].iloc[-1] == 0.0
    assert result.equity_b.iloc[-1] == pytest.approx(500.0)


def test_merged_net_position():
    """合併淨部位:同一標的兩帳本同時持有時,net_shares = 兩帳本持股相加。"""
    dates = pd.bdate_range('2024-01-01', periods=5)
    strat_a = ScriptedStrategy({dates[0]: SignalType.BUY})
    strat_b = ScriptedStrategy({dates[1]: SignalType.BUY_HALF})
    result = make_portfolio(strat_a, strat_b, rebalance_frequency=None).run(
        make_df(dates, [100] * 5))
    # A 全倉 5 股;B 半倉 250 → 2.5 股;淨部位 7.5 股
    assert result.result_a.equity_curve['shares'].iloc[-1] == pytest.approx(5.0)
    assert result.result_b.equity_curve['shares'].iloc[-1] == pytest.approx(2.5)
    assert result.equity_curve['net_shares'].iloc[-1] == pytest.approx(7.5)


def quarter_cross_df(price_q1=100.0, price_q2=150.0):
    """跨季行情:3 月底價格 price_q1,4 月起跳到 price_q2。"""
    mar = pd.bdate_range('2024-03-25', '2024-03-29')
    apr = pd.bdate_range('2024-04-01', '2024-04-05')
    return make_df(mar.append(apr), [price_q1] * len(mar) + [price_q2] * len(apr))


def test_quarterly_rebalance_restores_50_50():
    """季度再平衡:賣賺的、補虧的,兩帳本回到 50/50。"""
    df = quarter_cross_df()
    strat_a = ScriptedStrategy({pd.Timestamp('2024-03-25'): SignalType.BUY})
    result = make_portfolio(strat_a).run(df)

    # A 以 100 全倉買 5 股;4/1(新一季首個交易日)開盤價 150:
    # A 淨值 750、B 500 → 各 625。A 現金為 0,須賣 125/150 股補足轉帳。
    assert len(result.rebalances) == 1
    reb = result.rebalances.iloc[0]
    assert reb['date'] == pd.Timestamp('2024-04-01')
    assert reb['from_ledger'] == 'A' and reb['to_ledger'] == 'B'
    assert reb['amount'] == pytest.approx(125.0)
    assert reb['shares_sold'] == pytest.approx(125.0 / 150.0)
    assert reb['weight_a'] == pytest.approx(0.5)

    day = result.equity_curve.loc[pd.Timestamp('2024-04-01')]
    assert day['equity_a'] == pytest.approx(625.0)
    assert day['equity_b'] == pytest.approx(625.0)
    assert day['equity'] == pytest.approx(1250.0)  # 無成本下再平衡不憑空增減淨值


def test_rebalance_sell_pays_costs():
    """再平衡賣股需付成本:B 補足目標金額,費用自 A 淨值扣除。"""
    sell_rate = 0.001855  # 0050 賣出:手續費六折 + 證交稅
    df = quarter_cross_df()
    strat_a = ScriptedStrategy({pd.Timestamp('2024-03-25'): SignalType.BUY})
    result = make_portfolio(
        strat_a, cost_model=CostModel(buy_rate=0.0, sell_rate=sell_rate)).run(df)

    reb = result.rebalances.iloc[0]
    gross = 125.0 / (1.0 - sell_rate)  # 反推含成本的成交額
    assert reb['fee'] == pytest.approx(gross * sell_rate)
    assert reb['amount'] == pytest.approx(125.0)  # B 仍收到完整缺口金額
    day = result.equity_curve.loc[pd.Timestamp('2024-04-01')]
    assert day['equity_b'] == pytest.approx(625.0)
    assert day['equity_a'] == pytest.approx(625.0 - reb['fee'])


def test_rebalance_disabled():
    """rebalance_frequency=None:跨季也不再平衡,帳本維持各自損益。"""
    df = quarter_cross_df()
    strat_a = ScriptedStrategy({pd.Timestamp('2024-03-25'): SignalType.BUY})
    result = make_portfolio(strat_a, rebalance_frequency=None).run(df)
    assert result.rebalances.empty
    assert result.equity_a.iloc[-1] == pytest.approx(750.0)
    assert result.equity_b.iloc[-1] == pytest.approx(500.0)


def test_rebalance_not_triggered_when_balanced():
    """兩帳本本來就 50/50(都空手)時,跨季不產生再平衡紀錄。"""
    result = make_portfolio().run(quarter_cross_df())
    assert result.rebalances.empty


def test_dca_monthly_split_50_50():
    """DCA:每月第一個交易日入金,按 50/50 分進兩帳本;起始日不入金。"""
    dates = pd.bdate_range('2024-01-29', '2024-02-02')  # 跨一次月界(2/1)
    result = make_portfolio(dca_amount=300.0, rebalance_frequency=None).run(
        make_df(dates, [100] * len(dates)))

    assert len(result.cash_flows) == 1
    flow = result.cash_flows.iloc[0]
    assert flow['date'] == pd.Timestamp('2024-02-01')
    assert flow['amount'] == pytest.approx(300.0)
    assert flow['amount_a'] == pytest.approx(150.0)
    assert flow['amount_b'] == pytest.approx(150.0)

    assert result.combined_equity.iloc[0] == pytest.approx(1000.0)  # 起始日不入金
    assert result.equity_a.iloc[-1] == pytest.approx(650.0)
    assert result.equity_b.iloc[-1] == pytest.approx(650.0)


def test_dca_follows_allocation_ratio():
    """DCA 分配跟著 allocation 比例走(60/40)。"""
    dates = pd.bdate_range('2024-01-29', '2024-02-02')
    result = make_portfolio(dca_amount=300.0, allocation_a=0.6,
                            rebalance_frequency=None).run(
        make_df(dates, [100] * len(dates)))
    flow = result.cash_flows.iloc[0]
    assert flow['amount_a'] == pytest.approx(180.0)
    assert flow['amount_b'] == pytest.approx(120.0)
    assert result.equity_a.iloc[0] == pytest.approx(600.0)   # 初始 60%
    assert result.equity_a.iloc[-1] == pytest.approx(780.0)  # 600 + 180


def test_correlation_warning_when_diversification_fails(caplog):
    """兩帳本同時滿倉同一標的 → 滾動相關 = 1,應輸出分散失效警告。"""
    n = 130  # 需超過 60 日窗口
    dates = pd.bdate_range('2024-01-01', periods=n)
    rng = np.random.default_rng(7)
    prices = 100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, n))
    buy_first_day = {dates[0]: SignalType.BUY}
    p = make_portfolio(ScriptedStrategy(buy_first_day),
                       ScriptedStrategy(buy_first_day), rebalance_frequency=None)

    with caplog.at_level(logging.WARNING, logger='quant_tool.portfolio'):
        result = p.run(make_df(dates, prices))

    assert '相關係數' in caplog.text
    corr = result.rolling_correlation().dropna()
    assert corr.iloc[-1] == pytest.approx(1.0)


def test_no_correlation_warning_when_ledger_idle(caplog):
    """B 全程空手(日報酬恆為 0)→ 相關係數無定義,不應誤發警告。"""
    n = 130
    dates = pd.bdate_range('2024-01-01', periods=n)
    rng = np.random.default_rng(7)
    prices = 100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, n))
    p = make_portfolio(ScriptedStrategy({dates[0]: SignalType.BUY}),
                       rebalance_frequency=None)

    with caplog.at_level(logging.WARNING, logger='quant_tool.portfolio'):
        p.run(make_df(dates, prices))

    assert '相關係數' not in caplog.text


def test_flow_adjusted_correlation_ignores_transfers():
    """相關係數用現金流調整後的報酬:DCA 同日入金不該製造假相關。"""
    n = 130
    dates = pd.bdate_range('2024-01-01', periods=n)
    rng = np.random.default_rng(11)
    prices = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, n))
    # A 持股、B 空手,但每月兩帳本同時入金
    result = make_portfolio(ScriptedStrategy({dates[0]: SignalType.BUY}),
                            dca_amount=100.0, rebalance_frequency=None).run(
        make_df(dates, prices))
    # B 扣除入金後日報酬恆為 0 → 相關係數應為 nan(而非被入金拉出正相關)
    assert result.rolling_correlation().dropna().empty


def test_warmup_blocks_trades():
    """暖機期內策略訊號不成交。"""
    dates = pd.bdate_range('2024-01-01', periods=6)
    strat_a = ScriptedStrategy({d: SignalType.BUY for d in dates})
    result = pf.Portfolio(strat_a, ScriptedStrategy(), initial_capital=1000.0,
                          warmup_days=4, rebalance_frequency=None).run(
        make_df(dates, [100] * 6))
    trades = result.result_a.trades
    assert len(trades) == 1
    assert trades['date'].iloc[0] == dates[4]  # 第 5 個交易日才首次成交


def test_empty_dataframe_does_not_crash():
    """空行情:結果保有一致 schema,final_equity 回傳初始資金。"""
    result = make_portfolio().run(make_df([], []))
    assert result.equity_curve.empty
    assert result.rebalances.empty and result.cash_flows.empty
    assert result.final_equity == pytest.approx(1000.0)


def test_invalid_parameters_raise():
    with pytest.raises(ValueError):
        make_portfolio(allocation_a=0.0)
    with pytest.raises(ValueError):
        make_portfolio(rebalance_frequency='weekly')
