import pandas as pd
import pytest

from quant_tool.strategies.base import Strategy, SignalType
from quant_tool.backtest import Backtest


class ScriptedStrategy(Strategy):
    """依預設清單逐日回傳訊號，方便精準驗證引擎行為。"""
    def __init__(self, signals):
        super().__init__()
        self.signals = list(signals)
        self.i = 0

    def generate_signal(self, row, account):
        sig = self.signals[self.i] if self.i < len(self.signals) else SignalType.HOLD
        self.i += 1
        return sig


class AlwaysBuyStrategy(Strategy):
    """每天都喊 BUY，用來測試暖機期的成交封鎖。"""
    def generate_signal(self, row, account):
        return SignalType.BUY


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


def test_signal_executes_next_day_open():
    """t 日收盤出訊號 → t+1 日開盤成交（延遲一日）。"""
    df = make_df(opens=[10, 20, 30, 40], closes=[11, 21, 31, 41])
    # day0: BUY(掛單) / day1: 開盤成交、當日 HOLD / day2: SELL(掛單) / day3: 開盤成交
    strat = ScriptedStrategy([SignalType.BUY, SignalType.HOLD, SignalType.SELL, SignalType.HOLD])
    result = Backtest(strat, initial_capital=1000.0, warmup_days=0).run(df)

    trades = result.trades
    assert len(trades) == 2

    # day0 出的 BUY 不在 day0 成交，而是在 day1 的開盤價 20 成交
    buy = trades.iloc[0]
    assert buy['action'] == 'BUY'
    assert buy['date'] == df['date'].iloc[1]
    assert buy['price'] == 20.0
    assert buy['shares'] == pytest.approx(1000.0 / 20.0)  # 50 股
    assert buy['cash'] == pytest.approx(0.0)

    # day0 收盤結算時尚未持倉（證明沒有當日成交）
    eq = result.equity_curve
    assert eq.iloc[0]['shares'] == 0.0
    assert eq.iloc[0]['equity'] == pytest.approx(1000.0)

    # day2 出的 SELL 在 day3 開盤價 40 成交
    sell = trades.iloc[1]
    assert sell['action'] == 'SELL'
    assert sell['date'] == df['date'].iloc[3]
    assert sell['price'] == 40.0
    assert sell['cash'] == pytest.approx(50.0 * 40.0)  # 2000


def test_no_trading_during_warmup():
    """暖機期內不成交：warmup_days 之前不得有任何交易。"""
    n = 8
    df = make_df(opens=list(range(10, 10 + n)), closes=list(range(11, 11 + n)))
    result = Backtest(AlwaysBuyStrategy(), initial_capital=1000.0, warmup_days=3).run(df)

    trades = result.trades
    assert len(trades) >= 1
    # 第一筆成交必須落在 day_idx >= warmup_days（此處為第 3 個 index，即第 4 根 K）
    assert trades.iloc[0]['date'] == df['date'].iloc[3]
    # 所有成交日期都不早於暖機結束日
    assert (trades['date'] >= df['date'].iloc[3]).all()

    # 暖機期內（day0~day2）帳戶維持全現金、無持倉
    eq = result.equity_curve
    for i in range(3):
        assert eq.iloc[i]['shares'] == 0.0
        assert eq.iloc[i]['equity'] == pytest.approx(1000.0)


def test_equity_curve_reflects_position_value():
    """每日淨值 = 現金 + 持倉市值。"""
    df = make_df(opens=[10, 20, 25], closes=[11, 22, 26])
    strat = ScriptedStrategy([SignalType.BUY, SignalType.HOLD, SignalType.HOLD])
    result = Backtest(strat, initial_capital=1000.0, warmup_days=0).run(df)

    eq = result.equity_curve
    # day1 開盤價 20 買入 50 股，收盤價 22 → 市值 1100
    assert eq.iloc[1]['shares'] == pytest.approx(50.0)
    assert eq.iloc[1]['cash'] == pytest.approx(0.0)
    assert eq.iloc[1]['equity'] == pytest.approx(50.0 * 22.0)
    # day2 持倉不變，收盤價 26 → 市值 1300
    assert eq.iloc[2]['equity'] == pytest.approx(50.0 * 26.0)
    assert result.final_equity == pytest.approx(1300.0)


def test_buy_half_then_reduce():
    """BUY_HALF 投入半數現金，REDUCE 賣掉半數持股。"""
    df = make_df(opens=[10, 10, 10, 10], closes=[10, 10, 10, 10])
    strat = ScriptedStrategy([
        SignalType.BUY_HALF,  # day1: 花 500 買 50 股，剩 500 現金
        SignalType.HOLD,
        SignalType.REDUCE,    # day3: 賣掉 25 股，收回 250
        SignalType.HOLD,
    ])
    result = Backtest(strat, initial_capital=1000.0, warmup_days=0).run(df)

    buy_half = result.trades.iloc[0]
    assert buy_half['action'] == 'BUY_HALF'
    assert buy_half['shares'] == pytest.approx(50.0)
    assert buy_half['position'] == pytest.approx(50.0)
    assert buy_half['cash'] == pytest.approx(500.0)

    reduce = result.trades.iloc[1]
    assert reduce['action'] == 'REDUCE'
    assert reduce['shares'] == pytest.approx(25.0)
    assert reduce['position'] == pytest.approx(25.0)
    assert reduce['cash'] == pytest.approx(750.0)


def test_no_op_signals_produce_no_trades():
    """沒有現金時的 BUY 與沒有持倉時的 SELL 不應產生交易。"""
    df = make_df(opens=[10, 10, 10], closes=[10, 10, 10])
    # 一開始就 SELL（無持倉）→ 不成交
    strat = ScriptedStrategy([SignalType.SELL, SignalType.SELL, SignalType.HOLD])
    result = Backtest(strat, initial_capital=1000.0, warmup_days=0).run(df)
    assert result.trades.empty
    assert result.final_equity == pytest.approx(1000.0)
