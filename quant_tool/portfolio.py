"""組合層:雙帳本資金分配、季度再平衡、DCA 現金流、相關性監控與合併淨部位。

架構(AGENTS.md §1):
  - 兩帳本(A=趨勢、B=均值回歸)獨立記帳、獨立持倉,互不知道對方存在;
    組合層只透過「現金轉帳 + 必要時賣股」調整資金分配。
  - 再平衡:季末收盤判定失衡,下一季第一個交易日「開盤價」執行
    (與回測引擎 t+1 開盤成交的執行模型一致,避免未來函數):
    賣賺的、補虧的,把兩帳本淨值拉回目標比例(預設 50/50)。
  - DCA 現金流:每月第一個交易日開盤入金,按分配比例分進兩帳本 cash_pool,
    帳本何時投入市場仍由各自策略訊號決定。
  - 合併淨部位:同一標的兩帳本可能同時持有(趨勢滿倉 + 均值回歸進場),
    回測分開記帳,equity_curve['net_shares'] 提供合併後淨部位供實際下單參考。

再平衡轉帳「不」記入帳本 trades(保持策略交易統計純淨,勝率/盈虧比不失真),
明細見 PortfolioResult.rebalances;賣股成本仍由 cost_model 計算、自淨值扣除。
"""
import logging
from dataclasses import dataclass

import pandas as pd

from quant_tool.backtest import (BacktestResult, EQUITY_COLUMNS, TRADE_COLUMNS,
                                 execute_signal)
from quant_tool.costs import CostModel
from quant_tool.strategies.base import Account, SignalType, Strategy

logger = logging.getLogger(__name__)

# 兩帳本日報酬滾動相關係數:長期平均高於此值代表分散失效(預期 < 0.3)
CORRELATION_WARN_THRESHOLD = 0.6
CORRELATION_WINDOW = 60

# 再平衡頻率 → pandas Period 頻率代碼;None 表示不再平衡
REBALANCE_FREQ_CODES = {'monthly': 'M', 'quarterly': 'Q', 'yearly': 'Y'}

# 失衡金額小於此值(帳務浮點誤差等級)就不觸發再平衡
REBALANCE_TOLERANCE = 1e-6

PORTFOLIO_EQUITY_COLUMNS = ['close', 'equity_a', 'equity_b', 'equity',
                            'net_shares', 'flow_a', 'flow_b']
REBALANCE_COLUMNS = ['date', 'from_ledger', 'to_ledger', 'amount',
                     'shares_sold', 'price', 'fee', 'weight_a']
CASHFLOW_COLUMNS = ['date', 'amount', 'amount_a', 'amount_b']


def flow_adjusted_returns(equity: pd.Series, flows: pd.Series) -> pd.Series:
    """
    扣除當日外部現金流(DCA 入金、再平衡轉帳)後的日報酬。
    轉帳造成的淨值跳動不是策略績效,直接用 pct_change 會污染相關係數。
    """
    return ((equity - flows) / equity.shift(1) - 1.0).dropna()


@dataclass
class PortfolioResult:
    """組合回測結果:兩帳本各一份 BacktestResult + 組合層明細。"""
    result_a: BacktestResult   # 帳本 A(trades 只含策略交易,不含再平衡轉帳)
    result_b: BacktestResult   # 帳本 B
    equity_curve: pd.DataFrame # index=date,欄位見 PORTFOLIO_EQUITY_COLUMNS
    rebalances: pd.DataFrame   # 再平衡明細,欄位見 REBALANCE_COLUMNS
    cash_flows: pd.DataFrame   # DCA 入金明細,欄位見 CASHFLOW_COLUMNS
    initial_capital: float

    @property
    def equity_a(self) -> pd.Series:
        return self.equity_curve['equity_a']

    @property
    def equity_b(self) -> pd.Series:
        return self.equity_curve['equity_b']

    @property
    def combined_equity(self) -> pd.Series:
        """組合日淨值序列 = 兩帳本淨值相加。"""
        return self.equity_curve['equity']

    @property
    def final_equity(self) -> float:
        if self.equity_curve.empty:
            return self.initial_capital
        return float(self.combined_equity.iloc[-1])

    def rolling_correlation(self, window: int = CORRELATION_WINDOW) -> pd.Series:
        """兩帳本日報酬的滾動相關係數(現金流調整後,預設 60 日窗口)。"""
        r_a = flow_adjusted_returns(self.equity_a, self.equity_curve['flow_a'])
        r_b = flow_adjusted_returns(self.equity_b, self.equity_curve['flow_b'])
        return r_a.rolling(window).corr(r_b)


def check_correlation(result: PortfolioResult,
                      window: int = CORRELATION_WINDOW,
                      threshold: float = CORRELATION_WARN_THRESHOLD) -> float:
    """
    相關性監控:回傳兩帳本滾動相關係數的長期平均,
    高於 threshold 時輸出警告(分散失效,需檢討策略組合)。
    """
    corr = result.rolling_correlation(window).dropna()
    if corr.empty:
        return float('nan')
    mean_corr = float(corr.mean())
    if mean_corr > threshold:
        logger.warning(
            "兩帳本 %d 日滾動相關係數長期平均 %.2f > %.1f:"
            "分散失效,兩策略同漲同跌,需檢討策略組合。",
            window, mean_corr, threshold,
        )
    return mean_corr


class Portfolio:
    """
    雙帳本組合回測:同一份行情(含指標)同時餵給兩個策略,
    各自獨立記帳,組合層負責 DCA 入金與定期再平衡。

    v1 假設兩帳本交易同一標的(df 共用),故可直接合併淨部位。

    每日流程(與單策略回測一致的 t+1 開盤執行模型):
      1. 開盤:月份切換 → DCA 入金(回測起始日不入金)
      2. 開盤:再平衡週期切換 → 依開盤價把兩帳本拉回目標比例
      3. 開盤:成交昨日收盤產生的策略訊號(暖機期內不成交)
      4. 收盤:兩策略各自產生訊號,延到明日開盤成交
      5. 收盤:結算兩帳本與組合淨值
    """

    def __init__(self, strategy_a: Strategy, strategy_b: Strategy,
                 initial_capital: float = 1_000_000.0, allocation_a: float = 0.5,
                 warmup_days: int = 200, cost_model: CostModel | None = None,
                 rebalance_frequency: str | None = 'quarterly',
                 dca_amount: float = 0.0):
        if not 0.0 < allocation_a < 1.0:
            raise ValueError(f"allocation_a 需介於 0 與 1 之間,收到 {allocation_a}")
        if rebalance_frequency is not None and rebalance_frequency not in REBALANCE_FREQ_CODES:
            raise ValueError(
                f"rebalance_frequency 需為 {sorted(REBALANCE_FREQ_CODES)} 或 None,"
                f"收到 {rebalance_frequency!r}")
        self.strategy_a = strategy_a
        self.strategy_b = strategy_b
        self.initial_capital = float(initial_capital)
        self.allocation_a = float(allocation_a)
        self.warmup_days = warmup_days
        self.cost_model = cost_model if cost_model is not None else CostModel()
        self.rebalance_frequency = rebalance_frequency
        self.dca_amount = float(dca_amount)  # 每月入金金額,0 表示不入金

    def run(self, df: pd.DataFrame) -> PortfolioResult:
        """逐日跑雙策略組合。df 需含 date/open/close 及兩策略所需指標欄位。"""
        acct_a = Account(self.initial_capital * self.allocation_a)
        acct_b = Account(self.initial_capital * (1.0 - self.allocation_a))
        pending_a = pending_b = SignalType.HOLD
        prev_ts = None  # 前一交易日日期,用於判斷月份 / 再平衡週期切換
        reb_code = REBALANCE_FREQ_CODES.get(self.rebalance_frequency)

        trades_a, trades_b = [], []
        records_a, records_b, records = [], [], []
        rebalance_records, cashflow_records = [], []

        for day_idx, (_, row) in enumerate(df.iterrows()):
            date = row['date']
            ts = pd.Timestamp(date)
            open_price = float(row['open'])
            close_price = float(row['close'])
            flow_a = flow_b = 0.0  # 當日流入帳本的外部現金(入金 + 轉帳,可為負)

            # 1. DCA 入金:每月第一個交易日,按分配比例分進兩帳本 cash_pool
            if (self.dca_amount > 0 and prev_ts is not None
                    and ts.to_period('M') != prev_ts.to_period('M')):
                amount_a = self.dca_amount * self.allocation_a
                amount_b = self.dca_amount - amount_a
                acct_a.cash += amount_a
                acct_b.cash += amount_b
                flow_a += amount_a
                flow_b += amount_b
                cashflow_records.append({'date': date, 'amount': self.dca_amount,
                                         'amount_a': amount_a, 'amount_b': amount_b})

            # 2. 再平衡:每個週期的第一個交易日,依開盤價拉回目標比例
            if (reb_code is not None and prev_ts is not None
                    and ts.to_period(reb_code) != prev_ts.to_period(reb_code)):
                record, transfer_to_a = self._rebalance(acct_a, acct_b, open_price, date)
                if record is not None:
                    rebalance_records.append(record)
                    flow_a += transfer_to_a
                    flow_b -= transfer_to_a

            # 3. 成交昨日策略訊號(今日開盤價);暖機期內不成交
            if day_idx >= self.warmup_days:
                if pending_a != SignalType.HOLD:
                    trade = execute_signal(acct_a, pending_a, open_price, date,
                                           self.cost_model)
                    if trade is not None:
                        trades_a.append(trade)
                if pending_b != SignalType.HOLD:
                    trade = execute_signal(acct_b, pending_b, open_price, date,
                                           self.cost_model)
                    if trade is not None:
                        trades_b.append(trade)

            # 4. 依今日收盤資料產生訊號,延到明日開盤成交
            pending_a = self.strategy_a.generate_signal(row, acct_a)
            pending_b = self.strategy_b.generate_signal(row, acct_b)

            # 5. 收盤結算:兩帳本各自淨值 + 組合淨值 + 合併淨部位
            equity_a = acct_a.cash + acct_a.position.shares * close_price
            equity_b = acct_b.cash + acct_b.position.shares * close_price
            records_a.append({'date': date, 'close': close_price, 'cash': acct_a.cash,
                              'shares': acct_a.position.shares,
                              'position_value': acct_a.position.shares * close_price,
                              'equity': equity_a})
            records_b.append({'date': date, 'close': close_price, 'cash': acct_b.cash,
                              'shares': acct_b.position.shares,
                              'position_value': acct_b.position.shares * close_price,
                              'equity': equity_b})
            records.append({'date': date, 'close': close_price,
                            'equity_a': equity_a, 'equity_b': equity_b,
                            'equity': equity_a + equity_b,
                            'net_shares': acct_a.position.shares + acct_b.position.shares,
                            'flow_a': flow_a, 'flow_b': flow_b})
            prev_ts = ts

        result = PortfolioResult(
            result_a=BacktestResult(
                trades=pd.DataFrame(trades_a, columns=TRADE_COLUMNS),
                equity_curve=self._to_curve(records_a, EQUITY_COLUMNS),
                initial_capital=self.initial_capital * self.allocation_a),
            result_b=BacktestResult(
                trades=pd.DataFrame(trades_b, columns=TRADE_COLUMNS),
                equity_curve=self._to_curve(records_b, EQUITY_COLUMNS),
                initial_capital=self.initial_capital * (1.0 - self.allocation_a)),
            equity_curve=self._to_curve(records, PORTFOLIO_EQUITY_COLUMNS),
            rebalances=pd.DataFrame(rebalance_records, columns=REBALANCE_COLUMNS),
            cash_flows=pd.DataFrame(cashflow_records, columns=CASHFLOW_COLUMNS),
            initial_capital=self.initial_capital,
        )
        check_correlation(result)  # 長期相關 > 0.6 時輸出警告
        return result

    def _rebalance(self, acct_a: Account, acct_b: Account, price: float, date):
        """
        把兩帳本淨值(以 price 計)拉回目標比例:賣賺的、補虧的。
        超額帳本先用現金轉帳,現金不足才賣股補足(賣出成本由 cost_model 計)。
        回傳 (再平衡紀錄, 轉入帳本 A 的金額);未失衡則回傳 (None, 0.0)。
        """
        equity_a = acct_a.cash + acct_a.position.shares * price
        equity_b = acct_b.cash + acct_b.position.shares * price
        total = equity_a + equity_b
        if total <= 0:
            return None, 0.0
        surplus_a = equity_a - total * self.allocation_a  # >0:A 賺多了,要轉給 B
        if abs(surplus_a) < REBALANCE_TOLERANCE:
            return None, 0.0

        if surplus_a > 0:
            src, dst, src_name, dst_name = acct_a, acct_b, 'A', 'B'
        else:
            src, dst, src_name, dst_name = acct_b, acct_a, 'B', 'A'
        amount = abs(surplus_a)

        # 現金不足時賣股補足:反推「扣掉賣出成本後剛好補齊缺口」的成交額
        shares_sold = fee = 0.0
        shortfall = amount - src.cash
        if shortfall > 0 and src.position.shares > 0 and price > 0:
            gross_needed = shortfall / (1.0 - self.cost_model.sell_rate)
            shares_sold = min(gross_needed / price, src.position.shares)
            gross = shares_sold * price
            fee = self.cost_model.sell_cost(gross)
            src.position.shares -= shares_sold
            src.cash += gross - fee
            if src.position.shares <= 1e-9:  # 完全出清,重置成本與進場日
                src.position.shares = 0.0
                src.position.average_price = 0.0
                src.position.entry_date = None

        transfer = min(amount, src.cash)
        src.cash -= transfer
        dst.cash += transfer

        equity_a = acct_a.cash + acct_a.position.shares * price
        equity_b = acct_b.cash + acct_b.position.shares * price
        record = {'date': date, 'from_ledger': src_name, 'to_ledger': dst_name,
                  'amount': transfer, 'shares_sold': shares_sold, 'price': price,
                  'fee': fee, 'weight_a': equity_a / (equity_a + equity_b)}
        transfer_to_a = transfer if dst is acct_a else -transfer
        return record, transfer_to_a

    @staticmethod
    def _to_curve(records: list, columns: list) -> pd.DataFrame:
        """把逐日紀錄轉成 index=date 的淨值曲線(空紀錄也保有一致 schema)。"""
        if not records:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(records).set_index('date')[columns]
