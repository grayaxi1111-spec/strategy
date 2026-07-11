"""績效層:單帳本與組合層的績效指標計算與報表。

輸入慣例:
  - equity:每日淨值序列(pd.Series,index 為日期)
  - trades:回測引擎輸出的交易紀錄(欄位見 backtest.TRADE_COLUMNS)
組合層函數只吃 equity 曲線,由第 10 節 portfolio.py 負責產生並調用。
"""
import numpy as np
import pandas as pd

from quant_tool.backtest import BacktestResult

TRADING_DAYS_PER_YEAR = 252
DAYS_PER_YEAR = 365.25


def daily_returns(equity: pd.Series) -> pd.Series:
    """日報酬序列。"""
    return equity.pct_change().dropna()


def _years(equity: pd.Series) -> float:
    """曲線涵蓋的日曆年數(依首尾日期)。"""
    if len(equity) < 2:
        return 0.0
    span_days = (equity.index[-1] - equity.index[0]).days
    return span_days / DAYS_PER_YEAR


def cagr(equity: pd.Series) -> float:
    """年化報酬率(依日曆時間年化)。"""
    years = _years(equity)
    if years <= 0 or equity.iloc[0] <= 0:
        return 0.0
    return (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0


def max_drawdown(equity: pd.Series) -> float:
    """最大回撤,回傳正值比例(0.25 代表 -25%)。"""
    if len(equity) < 2:
        return 0.0
    drawdown = equity / equity.cummax() - 1.0
    return float(-drawdown.min())


def sharpe_ratio(equity: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Sharpe Ratio(日報酬年化,rf 為年利率)。波動為 0 時回傳 0。"""
    r = daily_returns(equity) - risk_free_rate / TRADING_DAYS_PER_YEAR
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def sortino_ratio(equity: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Sortino Ratio:只用下跌日的均方根當風險分母。無下跌日時回傳 0。"""
    r = daily_returns(equity) - risk_free_rate / TRADING_DAYS_PER_YEAR
    if len(r) < 2:
        return 0.0
    downside = np.sqrt(np.mean(np.square(np.minimum(r, 0.0))))
    if downside == 0:
        return 0.0
    return float(r.mean() / downside * np.sqrt(TRADING_DAYS_PER_YEAR))


def realized_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """
    重放交易紀錄,計算每筆賣出(SELL/REDUCE)的已實現損益。

    成本基礎採加權平均且含買入費用(value = 買入實際現金流出),
    賣出 pnl = 淨入金 - 平均成本 × 賣出股數,故已扣除來回成本。
    """
    shares_held = 0.0
    avg_cost = 0.0
    records = []
    for _, t in trades.iterrows():
        if t['action'] in ('BUY', 'BUY_HALF'):
            new_shares = shares_held + t['shares']
            avg_cost = (shares_held * avg_cost + t['value']) / new_shares
            shares_held = new_shares
        elif t['action'] in ('SELL', 'REDUCE'):
            pnl = t['value'] - avg_cost * t['shares']
            records.append({'date': t['date'], 'action': t['action'],
                            'shares': t['shares'], 'pnl': pnl})
            shares_held -= t['shares']
            if shares_held <= 1e-9:  # 完全出清,重置成本
                shares_held, avg_cost = 0.0, 0.0
    return pd.DataFrame(records, columns=['date', 'action', 'shares', 'pnl'])


def win_rate(trades: pd.DataFrame) -> float:
    """勝率 = 獲利的已實現交易 / 全部已實現交易。無已實現交易回傳 0。"""
    realized = realized_trades(trades)
    if realized.empty:
        return 0.0
    return float((realized['pnl'] > 0).mean())


def profit_loss_ratio(trades: pd.DataFrame) -> float:
    """盈虧比 = 平均獲利 / |平均虧損|。無虧損交易回傳 inf,無獲利回傳 0。"""
    realized = realized_trades(trades)
    wins = realized.loc[realized['pnl'] > 0, 'pnl']
    losses = realized.loc[realized['pnl'] < 0, 'pnl']
    if wins.empty:
        return 0.0
    if losses.empty:
        return float('inf')
    return float(wins.mean() / abs(losses.mean()))


def trades_per_year(trades: pd.DataFrame, equity: pd.Series) -> float:
    """年均交易次數(每筆成交事件都計入,買賣各算一次)。"""
    years = _years(equity)
    if years <= 0:
        return 0.0
    return len(trades) / years


def time_in_market(equity_curve: pd.DataFrame) -> float:
    """持倉時間比例 = 收盤有持股的交易日 / 全部交易日。"""
    if equity_curve.empty:
        return 0.0
    return float((equity_curve['shares'] > 0).mean())


def equity_summary(equity: pd.Series) -> dict:
    """任意淨值曲線的核心指標(CAGR / MDD / Sharpe / Sortino / 總報酬)。"""
    return {
        'total_return': float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) else 0.0,
        'cagr': cagr(equity),
        'mdd': max_drawdown(equity),
        'sharpe': sharpe_ratio(equity),
        'sortino': sortino_ratio(equity),
    }


def summarize(result: BacktestResult) -> dict:
    """單一帳本的績效報表(核心指標 + 交易統計)。"""
    equity = result.equity_curve['equity']
    report = equity_summary(equity)
    report.update({
        'win_rate': win_rate(result.trades),
        'profit_loss_ratio': profit_loss_ratio(result.trades),
        'trades_per_year': trades_per_year(result.trades, equity),
        'time_in_market': time_in_market(result.equity_curve),
        'n_trades': len(result.trades),
        'final_equity': result.final_equity,
    })
    return report


def rolling_correlation(equity_a: pd.Series, equity_b: pd.Series,
                        window: int = 60) -> pd.Series:
    """兩帳本日報酬的滾動相關係數(預設 60 日窗口)。"""
    return daily_returns(equity_a).rolling(window).corr(daily_returns(equity_b))


def rebalance_contribution(rebalanced_equity: pd.Series,
                           unrebalanced_equity: pd.Series) -> float:
    """
    再平衡貢獻 = 有再平衡的總報酬 - 無再平衡(counterfactual)的總報酬。
    兩條曲線的起始資金與期間需一致,counterfactual 曲線由組合層產生。
    """
    ret_rebalanced = rebalanced_equity.iloc[-1] / rebalanced_equity.iloc[0] - 1.0
    ret_unrebalanced = unrebalanced_equity.iloc[-1] / unrebalanced_equity.iloc[0] - 1.0
    return float(ret_rebalanced - ret_unrebalanced)


def portfolio_summary(combined_equity: pd.Series,
                      equity_a: pd.Series, equity_b: pd.Series,
                      unrebalanced_equity: pd.Series | None = None,
                      corr_window: int = 60) -> dict:
    """
    組合層績效報表:組合 + 兩帳本各一份核心指標,
    外加滾動相關係數(60 日)與再平衡貢獻(需提供無再平衡曲線)。
    """
    corr = rolling_correlation(equity_a, equity_b, window=corr_window).dropna()
    report = {
        'combined': equity_summary(combined_equity),
        'ledger_a': equity_summary(equity_a),
        'ledger_b': equity_summary(equity_b),
        'rolling_corr_mean': float(corr.mean()) if len(corr) else float('nan'),
        'rolling_corr_last': float(corr.iloc[-1]) if len(corr) else float('nan'),
    }
    if unrebalanced_equity is not None:
        report['rebalance_contribution'] = rebalance_contribution(
            combined_equity, unrebalanced_equity)
    return report
