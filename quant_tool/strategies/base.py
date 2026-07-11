from enum import Enum, auto
from abc import ABC, abstractmethod
import pandas as pd

class SignalType(Enum):
    BUY = auto()      # 買入 (全倉進場 或 剩餘資金全下)
    BUY_HALF = auto() # 買入半倉 (用於初始建倉 50%)
    SELL = auto()     # 賣出平倉
    HOLD = auto()     # 持有 / 空手觀望
    REDUCE = auto()   # 減碼 (例如賣出 50%)

class Position:
    def __init__(self):
        self.shares = 0.0
        self.average_price = 0.0
        self.entry_date = None
        self.days_held = 0

    @property
    def is_invested(self):
        return self.shares > 0

class Account:
    def __init__(self, initial_capital: float = 0.0):
        self.cash = initial_capital
        self.position = Position()

    def get_total_value(self, current_price: float) -> float:
        """取得當前帳戶總價值 (現金 + 持倉市值)"""
        return self.cash + (self.position.shares * current_price)

class Strategy(ABC):
    def __init__(self, config: dict = None):
        self.config = config or {}
        
    @abstractmethod
    def generate_signal(self, row: pd.Series, account: Account) -> SignalType:
        """
        根據當日 K 線與當前帳戶狀態，產生交易訊號
        """
        pass
        
    def pre_process(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        子類別 override 的 hook：在進入逐日迴圈前回傳處理好的 DataFrame
        例如進一步的特定過濾或合併
        """
        return df
