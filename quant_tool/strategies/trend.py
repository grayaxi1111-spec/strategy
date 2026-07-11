import pandas as pd
from enum import Enum, auto
from quant_tool.strategies.base import Strategy, SignalType, Account

class TrendState(Enum):
    FLAT = auto()
    FULL = auto()
    HALF = auto()

class TrendStrategy(Strategy):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.state = TrendState.FLAT
        self.warmup_days = self.config.get('warmup_days', 200)
        self.slope_threshold = self.config.get('ma200_slope_threshold', -0.005)
        self.days_processed = 0

    def generate_signal(self, row: pd.Series, account: Account) -> SignalType:
        self.days_processed += 1
        
        # 暖機期內不觸發
        if self.days_processed <= self.warmup_days:
            return SignalType.HOLD

        ma20 = row.get('MA20')
        ma60 = row.get('MA60')
        ma200 = row.get('MA200')
        ma200_slope = row.get('MA200_Slope')
        super_trend_dir = row.get('SuperTrend_Dir')

        # 避免有缺失值
        if pd.isna(ma20) or pd.isna(ma60) or pd.isna(ma200) or pd.isna(ma200_slope) or pd.isna(super_trend_dir):
            return SignalType.HOLD

        regime_bull = (ma20 > ma60 > ma200) and (ma200_slope >= self.slope_threshold)
        supertrend_green = (super_trend_dir == 1)
        allowed = regime_bull and supertrend_green

        # 出場優先權邏輯
        if self.state in [TrendState.FULL, TrendState.HALF]:
            if not regime_bull:
                self.state = TrendState.FLAT
                return SignalType.SELL

        if self.state == TrendState.FULL:
            if not supertrend_green:
                self.state = TrendState.HALF
                return SignalType.REDUCE

        elif self.state == TrendState.HALF:
            if allowed:
                self.state = TrendState.FULL
                return SignalType.BUY

        elif self.state == TrendState.FLAT:
            if allowed:
                self.state = TrendState.FULL
                return SignalType.BUY

        return SignalType.HOLD
