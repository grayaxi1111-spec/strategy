import numpy as np
import pandas as pd
import pytest

from quant_tool import metrics
from quant_tool.backtest import BacktestResult, TRADE_COLUMNS


def make_equity(values, start='2024-01-01'):
    dates = pd.bdate_range(start=start, periods=len(values))
    return pd.Series([float(v) for v in values], index=dates)


def make_trades(rows):
    """rows: (action, shares, value) 依序建立交易紀錄。"""
    dates = pd.bdate_range(start='2024-01-01', periods=len(rows))
    return pd.DataFrame([
        {'date': d, 'action': a, 'price': 0.0, 'shares': s, 'value': v,
         'fee': 0.0, 'position': 0.0, 'cash': 0.0, 'avg_cost': 0.0}
        for d, (a, s, v) in zip(dates, rows)
    ], columns=TRADE_COLUMNS)


def test_cagr_known_series():
    """100 → 121,首尾相距 731 天(約兩年),CAGR ≈ 10%。"""
    equity = pd.Series([100.0, 121.0],
                       index=pd.to_datetime(['2024-01-01', '2026-01-01']))
    expected = 1.21 ** (metrics.DAYS_PER_YEAR / 731) - 1.0
    assert metrics.cagr(equity) == pytest.approx(expected)
    assert metrics.cagr(equity) == pytest.approx(0.0996, abs=1e-3)


def test_max_drawdown_known_series():
    """峰 120 → 谷 90 為最深回撤 25%(後段 130→117 僅 10%)。"""
    equity = make_equity([100, 120, 90, 130, 117])
    assert metrics.max_drawdown(equity) == pytest.approx(0.25)


def test_sharpe_known_returns():
    """日報酬 [+2%, -1%]:mean=0.005, std=0.021213 → Sharpe ≈ 3.742。"""
    equity = make_equity([100.0, 102.0, 100.98])
    assert metrics.sharpe_ratio(equity) == pytest.approx(
        0.005 / np.sqrt(0.00045) * np.sqrt(252), rel=1e-6)
    assert metrics.sharpe_ratio(equity) == pytest.approx(3.7417, abs=1e-3)


def test_sharpe_zero_volatility():
    equity = make_equity([100.0, 100.0, 100.0])
    assert metrics.sharpe_ratio(equity) == 0.0


def test_sortino_known_returns():
    """日報酬 [+2%, -1%]:下行均方根 = sqrt(0.0001/2) → Sortino ≈ 11.225。"""
    equity = make_equity([100.0, 102.0, 100.98])
    downside = np.sqrt(0.0001 / 2)
    assert metrics.sortino_ratio(equity) == pytest.approx(
        0.005 / downside * np.sqrt(252), rel=1e-6)
    assert metrics.sortino_ratio(equity) == pytest.approx(11.2250, abs=1e-3)


def test_win_rate_and_pl_ratio_full_roundtrips():
    """兩趟完整買賣:+200 / -100 → 勝率 50%,盈虧比 2.0。"""
    trades = make_trades([
        ('BUY', 100.0, 1000.0),   # 成本 10/股
        ('SELL', 100.0, 1200.0),  # pnl +200
        ('BUY', 100.0, 1000.0),
        ('SELL', 100.0, 900.0),   # pnl -100
    ])
    assert metrics.win_rate(trades) == pytest.approx(0.5)
    assert metrics.profit_loss_ratio(trades) == pytest.approx(2.0)


def test_realized_pnl_with_reduce():
    """REDUCE 部分出場也要按平均成本實現損益。"""
    trades = make_trades([
        ('BUY', 100.0, 1000.0),    # 成本 10/股
        ('REDUCE', 50.0, 600.0),   # pnl = 600 - 500 = +100
        ('SELL', 50.0, 450.0),     # pnl = 450 - 500 = -50
    ])
    realized = metrics.realized_trades(trades)
    assert list(realized['pnl']) == pytest.approx([100.0, -50.0])
    assert metrics.win_rate(trades) == pytest.approx(0.5)
    assert metrics.profit_loss_ratio(trades) == pytest.approx(2.0)


def test_trades_per_year():
    """一年期間 4 筆成交 → 年均約 4 次。"""
    equity = pd.Series([100.0, 110.0],
                       index=pd.to_datetime(['2024-01-01', '2024-12-31']))
    trades = make_trades([('BUY', 1, 10)] * 4)
    expected = 4 / (365 / metrics.DAYS_PER_YEAR)
    assert metrics.trades_per_year(trades, equity) == pytest.approx(expected)


def test_time_in_market():
    """5 個交易日中 2 天有持倉 → 40%。"""
    dates = pd.bdate_range('2024-01-01', periods=5)
    curve = pd.DataFrame({
        'shares': [0.0, 0.0, 50.0, 50.0, 0.0],
        'equity': [100.0] * 5,
    }, index=dates)
    assert metrics.time_in_market(curve) == pytest.approx(0.4)


def test_summarize_single_ledger_report():
    """單帳本報表需含所有核心指標與交易統計。"""
    dates = pd.bdate_range('2024-01-01', periods=4)
    curve = pd.DataFrame({
        'close': [10.0] * 4, 'cash': [0.0] * 4, 'shares': [100.0] * 4,
        'position_value': [1000, 1100, 1050, 1200],
        'equity': [1000.0, 1100.0, 1050.0, 1200.0],
    }, index=dates)
    trades = make_trades([('BUY', 100.0, 1000.0), ('SELL', 100.0, 1200.0)])
    result = BacktestResult(trades=trades, equity_curve=curve, initial_capital=1000.0)

    report = metrics.summarize(result)
    for key in ('total_return', 'cagr', 'mdd', 'sharpe', 'sortino', 'win_rate',
                'profit_loss_ratio', 'trades_per_year', 'time_in_market',
                'n_trades', 'final_equity'):
        assert key in report
    assert report['total_return'] == pytest.approx(0.2)
    assert report['mdd'] == pytest.approx(50.0 / 1100.0)
    assert report['win_rate'] == pytest.approx(1.0)
    assert report['n_trades'] == 2
    assert report['time_in_market'] == pytest.approx(1.0)


def test_rolling_correlation_known_series():
    """同向日報酬 → 相關 1;反向 → 相關 -1。"""
    factors_a = [1.01, 0.99, 1.01, 0.99, 1.01, 0.99]
    factors_b = [0.99, 1.01, 0.99, 1.01, 0.99, 1.01]
    a = make_equity(np.cumprod([100.0] + factors_a))
    same = metrics.rolling_correlation(a, a * 2, window=4).dropna()
    assert (same == pytest.approx(1.0)) if np.isscalar(same) else \
        all(v == pytest.approx(1.0) for v in same)

    b = make_equity(np.cumprod([100.0] + factors_b))
    inverse = metrics.rolling_correlation(a, b, window=4).dropna()
    assert all(v == pytest.approx(-1.0) for v in inverse)


def test_rebalance_contribution():
    """有再平衡 +20%、無再平衡 +15% → 貢獻 +5 個百分點。"""
    rebalanced = make_equity([100.0, 105.0, 120.0])
    unrebalanced = make_equity([100.0, 104.0, 115.0])
    assert metrics.rebalance_contribution(rebalanced, unrebalanced) == pytest.approx(0.05)


def test_portfolio_summary_structure():
    """組合報表:組合+兩帳本各一份指標、相關係數、再平衡貢獻。"""
    n = 70  # 需超過 60 日窗口
    rng = np.random.default_rng(42)
    a = make_equity(np.cumprod([100.0] + list(1 + rng.normal(0.001, 0.01, n))))
    b = make_equity(np.cumprod([100.0] + list(1 + rng.normal(0.001, 0.01, n))))
    combined = (a + b) / 2
    # 無再平衡的 counterfactual:同起點但期末報酬低 1%
    unrebalanced = combined.copy()
    unrebalanced.iloc[-1] = combined.iloc[-1] * 0.99

    report = metrics.portfolio_summary(combined, a, b,
                                       unrebalanced_equity=unrebalanced)
    for key in ('combined', 'ledger_a', 'ledger_b',
                'rolling_corr_mean', 'rolling_corr_last', 'rebalance_contribution'):
        assert key in report
    assert 'cagr' in report['combined'] and 'mdd' in report['ledger_b']
    assert -1.0 <= report['rolling_corr_last'] <= 1.0
    assert report['rebalance_contribution'] > 0  # 有再平衡的曲線報酬較高
