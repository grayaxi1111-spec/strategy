import pandas as pd
import pytest
from quant_tool.strategies.base import SignalType, Account
from quant_tool.strategies.mean_rev import MeanRevStrategy, MeanRevState

@pytest.fixture
def base_account():
    return Account()

def test_warmup_period(base_account):
    strategy = MeanRevStrategy({'warmup_days': 10})
    
    # 滿足進場條件
    row = pd.Series({
        'close': 100,
        'MA200': 90,
        'MA5': 105,
        'RSI2': 5
    })
    
    # 前10天暖機，應該 HOLD
    for _ in range(10):
        assert strategy.generate_signal(row, base_account) == SignalType.HOLD
    
    # 第11天開始可以交易，發出 BUY_HALF
    assert strategy.generate_signal(row, base_account) == SignalType.BUY_HALF
    assert strategy.state == MeanRevState.HALF

def test_oversold_entry_and_rebound_exit(base_account):
    strategy = MeanRevStrategy({'warmup_days': 0})
    
    # 1. 進場：close > MA200 且 RSI2 < 10
    entry_row = pd.Series({'close': 100, 'MA200': 90, 'MA5': 105, 'RSI2': 8})
    assert strategy.generate_signal(entry_row, base_account) == SignalType.BUY_HALF
    assert strategy.state == MeanRevState.HALF
    
    # 2. 持有期間：條件未改變，不加碼也不出場
    hold_row = pd.Series({'close': 98, 'MA200': 90, 'MA5': 102, 'RSI2': 15})
    assert strategy.generate_signal(hold_row, base_account) == SignalType.HOLD
    assert strategy.state == MeanRevState.HALF
    assert strategy.days_held == 1
    
    # 3. 加碼：RSI2 < 5
    scale_in_row = pd.Series({'close': 95, 'MA200': 90, 'MA5': 100, 'RSI2': 4})
    assert strategy.generate_signal(scale_in_row, base_account) == SignalType.BUY
    assert strategy.state == MeanRevState.FULL
    assert strategy.days_held == 2
    
    # 4. 反彈出場 1：RSI2 > 65
    exit_row_rsi = pd.Series({'close': 102, 'MA200': 90, 'MA5': 103, 'RSI2': 70})
    assert strategy.generate_signal(exit_row_rsi, base_account) == SignalType.SELL
    assert strategy.state == MeanRevState.FLAT
    assert strategy.days_held == 0
    
    # 回到進場狀態，測試反彈出場 2
    assert strategy.generate_signal(entry_row, base_account) == SignalType.BUY_HALF
    
    # 反彈出場 2：close > MA5
    exit_row_ma5 = pd.Series({'close': 106, 'MA200': 90, 'MA5': 105, 'RSI2': 50})
    assert strategy.generate_signal(exit_row_ma5, base_account) == SignalType.SELL
    assert strategy.state == MeanRevState.FLAT

def test_regime_break_exit(base_account):
    strategy = MeanRevStrategy({'warmup_days': 0})
    
    # 進場
    entry_row = pd.Series({'close': 100, 'MA200': 90, 'MA5': 105, 'RSI2': 8})
    assert strategy.generate_signal(entry_row, base_account) == SignalType.BUY_HALF
    
    # 環境破壞：close < MA200
    break_row = pd.Series({'close': 85, 'MA200': 90, 'MA5': 95, 'RSI2': 30})
    assert strategy.generate_signal(break_row, base_account) == SignalType.SELL
    assert strategy.state == MeanRevState.FLAT
    assert strategy.days_held == 0

def test_time_stop_exit(base_account):
    strategy = MeanRevStrategy({'warmup_days': 0})
    
    # 進場
    entry_row = pd.Series({'close': 100, 'MA200': 90, 'MA5': 105, 'RSI2': 8})
    assert strategy.generate_signal(entry_row, base_account) == SignalType.BUY_HALF
    
    # 模擬持有 10 天
    hold_row = pd.Series({'close': 98, 'MA200': 90, 'MA5': 102, 'RSI2': 15})
    for i in range(1, 11):
        assert strategy.generate_signal(hold_row, base_account) == SignalType.HOLD
        assert strategy.days_held == i
        
    # 第 11 天觸發時間停損
    assert strategy.generate_signal(hold_row, base_account) == SignalType.SELL
    assert strategy.state == MeanRevState.FLAT
    assert strategy.days_held == 0
