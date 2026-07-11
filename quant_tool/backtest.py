import pandas as pd
from dataclasses import dataclass

from quant_tool.strategies.base import Strategy, SignalType, Account

# 交易紀錄與淨值序列的固定欄位（確保空結果也有一致 schema）
TRADE_COLUMNS = ['date', 'action', 'price', 'shares', 'value', 'position', 'cash', 'avg_cost']
EQUITY_COLUMNS = ['close', 'cash', 'shares', 'position_value', 'equity']


@dataclass
class BacktestResult:
    """單策略回測結果：交易紀錄 + 每日淨值序列。"""
    trades: pd.DataFrame       # 欄位見 TRADE_COLUMNS
    equity_curve: pd.DataFrame # index=date，欄位見 EQUITY_COLUMNS
    initial_capital: float

    @property
    def final_equity(self) -> float:
        if self.equity_curve.empty:
            return self.initial_capital
        return float(self.equity_curve['equity'].iloc[-1])

    @property
    def total_return(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return self.final_equity / self.initial_capital - 1.0


class Backtest:
    """
    單策略回測引擎。

    執行模型（避免未來函數）：
      - t 日收盤依收盤資料產生訊號 → t+1 日「開盤價」成交（延遲一日）。
      - 暖機期：前 warmup_days 個交易日一律不成交。

    訊號 → 成交的統一語意（與具體策略無關）：
      - BUY      ：投入帳戶全部現金
      - BUY_HALF ：投入帳戶現金的 50%（留另外 50% 給後續加碼）
      - SELL     ：清掉全部持股
      - REDUCE   ：賣出當前持股的 50%
      - HOLD     ：不動作

    交易成本於第 8 節整合，目前以無摩擦成交計算。
    """

    def __init__(self, strategy: Strategy, initial_capital: float = 100000.0,
                 warmup_days: int = 200):
        self.strategy = strategy
        self.initial_capital = float(initial_capital)
        self.warmup_days = warmup_days

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """逐日跑策略，回傳交易紀錄與每日淨值。df 需含 date/open/close 及指標欄位。"""
        account = Account(self.initial_capital)
        pending_signal = SignalType.HOLD  # 昨日收盤產生、等待今日開盤成交的訊號
        trades = []
        equity_records = []

        for day_idx, (_, row) in enumerate(df.iterrows()):
            date = row['date']
            open_price = float(row['open'])
            close_price = float(row['close'])

            # 1. 先成交昨日訊號（今日開盤價）；暖機期內不成交
            if pending_signal != SignalType.HOLD and day_idx >= self.warmup_days:
                trade = self._execute(account, pending_signal, open_price, date)
                if trade is not None:
                    trades.append(trade)

            # 2. 依今日收盤資料產生訊號，延到明日開盤才成交
            pending_signal = self.strategy.generate_signal(row, account)

            # 3. 收盤後結算當日淨值（持倉市值 + 現金）
            position_value = account.position.shares * close_price
            equity_records.append({
                'date': date,
                'close': close_price,
                'cash': account.cash,
                'shares': account.position.shares,
                'position_value': position_value,
                'equity': account.cash + position_value,
            })

        trades_df = pd.DataFrame(trades, columns=TRADE_COLUMNS)
        equity_df = pd.DataFrame(equity_records)
        if not equity_df.empty:
            equity_df = equity_df.set_index('date')[EQUITY_COLUMNS]
        else:
            equity_df = pd.DataFrame(columns=EQUITY_COLUMNS)

        return BacktestResult(trades=trades_df, equity_curve=equity_df,
                              initial_capital=self.initial_capital)

    def _execute(self, account: Account, signal: SignalType, price: float, date):
        """依訊號在給定價格成交，更新帳戶並回傳一筆交易紀錄（無成交則回傳 None）。"""
        pos = account.position

        # --- 買進：投入全部或半數現金 ---
        if signal in (SignalType.BUY, SignalType.BUY_HALF):
            budget = account.cash if signal == SignalType.BUY else account.cash * 0.5
            if budget <= 0 or price <= 0:
                return None
            shares = budget / price
            # TODO(第8節): 在此扣抵買入交易成本（手續費 / 滑價）
            was_flat = pos.shares <= 0
            new_shares = pos.shares + shares
            # 加權平均成本
            pos.average_price = (pos.shares * pos.average_price + budget) / new_shares
            pos.shares = new_shares
            account.cash -= budget
            if was_flat:
                pos.entry_date = date
            return self._record(date, signal, price, shares, budget, account)

        # --- 賣出：清倉或減碼一半 ---
        if signal in (SignalType.SELL, SignalType.REDUCE):
            if pos.shares <= 0 or price <= 0:
                return None
            shares = pos.shares if signal == SignalType.SELL else pos.shares * 0.5
            proceeds = shares * price
            # TODO(第8節): 在此扣抵賣出交易成本（手續費 + 證交稅 / 滑價）
            pos.shares -= shares
            account.cash += proceeds
            if pos.shares <= 1e-9:  # 完全出清，重置成本與進場日
                pos.shares = 0.0
                pos.average_price = 0.0
                pos.entry_date = None
            return self._record(date, signal, price, shares, proceeds, account)

        return None

    @staticmethod
    def _record(date, signal: SignalType, price: float, shares: float,
                value: float, account: Account) -> dict:
        return {
            'date': date,
            'action': signal.name,
            'price': price,
            'shares': shares,          # 本次成交股數（正值）
            'value': value,            # 本次成交金額（正值）
            'position': account.position.shares,  # 成交後持股
            'cash': account.cash,                 # 成交後現金
            'avg_cost': account.position.average_price,
        }
