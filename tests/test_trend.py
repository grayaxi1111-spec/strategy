import pandas as pd
import pytest
from quant_tool.strategies.base import SignalType, Account
from quant_tool.strategies.trend import TrendStrategy, TrendState

@pytest.fixture
def base_row():
    # 預設是一個不滿足條件的普通狀態
    return pd.Series({
        'MA20': 50,
        'MA60': 60,
        'MA200': 70,
        'MA200_Slope': 0,
        'SuperTrend_Dir': -1
    })

def test_warmup_period(base_row):
    strategy = TrendStrategy({'warmup_days': 10})
    account = Account()
    
    # 讓條件滿足 ALLOWED
    bull_row = pd.Series({
        'MA20': 80,
        'MA60': 70,
        'MA200': 60,
        'MA200_Slope': 0.02,
        'SuperTrend_Dir': 1
    })
    
    # 前10天都在暖機，儘管條件滿足也應該 HOLD
    for i in range(10):
        assert strategy.generate_signal(bull_row, account) == SignalType.HOLD
    
    # 第11天開始可以交易，條件滿足應該發出 BUY
    assert strategy.generate_signal(bull_row, account) == SignalType.BUY
    assert strategy.state == TrendState.FULL

def test_state_machine_transitions():
    strategy = TrendStrategy({'warmup_days': 0})
    account = Account()
    
    bull_green = pd.Series({
        'MA20': 80, 'MA60': 70, 'MA200': 60,
        'MA200_Slope': 0.01, 'SuperTrend_Dir': 1
    })
    bull_red = pd.Series({
        'MA20': 80, 'MA60': 70, 'MA200': 60,
        'MA200_Slope': 0.01, 'SuperTrend_Dir': -1
    })
    bear_green = pd.Series({
        'MA20': 50, 'MA60': 60, 'MA200': 70,
        'MA200_Slope': -0.01, 'SuperTrend_Dir': 1
    })
    
    # 1. FLAT -> FULL
    assert strategy.state == TrendState.FLAT
    assert strategy.generate_signal(bull_green, account) == SignalType.BUY
    assert strategy.state == TrendState.FULL
    
    # 2. FULL 繼續保持
    assert strategy.generate_signal(bull_green, account) == SignalType.HOLD
    assert strategy.state == TrendState.FULL
    
    # 3. FULL -> HALF
    assert strategy.generate_signal(bull_red, account) == SignalType.REDUCE
    assert strategy.state == TrendState.HALF
    
    # 4. HALF 繼續保持
    assert strategy.generate_signal(bull_red, account) == SignalType.HOLD
    assert strategy.state == TrendState.HALF
    
    # 5. HALF -> FULL
    assert strategy.generate_signal(bull_green, account) == SignalType.BUY
    assert strategy.state == TrendState.FULL
    
    # 6. FULL -> FLAT (環境破壞直接清倉)
    assert strategy.generate_signal(bear_green, account) == SignalType.SELL
    assert strategy.state == TrendState.FLAT
    
    # 回到 HALF 然後測試 HALF -> FLAT
    strategy.state = TrendState.HALF
    assert strategy.generate_signal(bear_green, account) == SignalType.SELL
    assert strategy.state == TrendState.FLAT
    
def test_ma200_slope_filter():
    strategy = TrendStrategy({'warmup_days': 0})
    account = Account()
    
    # MA排列對，SuperTrend綠，但MA200斜率不對 (< -0.5%)
    # 注意：-0.01 (-1%) 只略低於門檻 -0.005 (-0.5%)，
    # 若門檻單位寫錯（例如誤用 -0.5 而非 -0.005）這個案例會被誤判為通過
    row = pd.Series({
        'MA20': 80, 'MA60': 70, 'MA200': 60,
        'MA200_Slope': -0.01, 'SuperTrend_Dir': 1
    })
    assert strategy.generate_signal(row, account) == SignalType.HOLD
    assert strategy.state == TrendState.FLAT
