import pandas as pd
from enum import Enum, auto
from quant_tool.strategies.base import Strategy, SignalType, Account

class MeanRevState(Enum):
    FLAT = auto()
    HALF = auto()
    FULL = auto()

class MeanRevStrategy(Strategy):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.state = MeanRevState.FLAT
        self.warmup_days = self.config.get('warmup_days', 200)
        self.days_processed = 0
        self.days_held = 0

    def generate_signal(self, row: pd.Series, account: Account) -> SignalType:
        self.days_processed += 1
        
        # 暖機期內不觸發
        if self.days_processed <= self.warmup_days:
            return SignalType.HOLD

        close = row.get('close')
        ma200 = row.get('MA200')
        ma5 = row.get('MA5')
        rsi2 = row.get('RSI2')

        # 避免有缺失值
        if pd.isna(close) or pd.isna(ma200) or pd.isna(ma5) or pd.isna(rsi2):
            return SignalType.HOLD

        # 更新持有天數
        if self.state in [MeanRevState.HALF, MeanRevState.FULL]:
            self.days_held += 1
        else:
            self.days_held = 0

        # 出場優先權：先觸發先執行
        if self.state in [MeanRevState.HALF, MeanRevState.FULL]:
            # 1. 獲利了結
            if rsi2 > 65 or close > ma5:
                self.state = MeanRevState.FLAT
                self.days_held = 0
                return SignalType.SELL
                
            # 2. 環境破壞，無條件出場
            if close < ma200:
                self.state = MeanRevState.FLAT
                self.days_held = 0
                return SignalType.SELL
                
            # 3. 時間停損
            if self.days_held > 10:
                self.state = MeanRevState.FLAT
                self.days_held = 0
                return SignalType.SELL

        # 進場與加碼邏輯
        if self.state == MeanRevState.FLAT:
            # 確保環境安全 (防接刀) 且 RSI 超賣
            if close > ma200 and rsi2 < 10:
                self.state = MeanRevState.HALF
                self.days_held = 0
                return SignalType.BUY_HALF
                
        elif self.state == MeanRevState.HALF:
            # 更深的超賣，執行加碼
            if rsi2 < 5:
                self.state = MeanRevState.FULL
                return SignalType.BUY

        return SignalType.HOLD
