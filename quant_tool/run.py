import os
import argparse
import yaml
import logging
import pandas as pd
import matplotlib.pyplot as plt

from quant_tool.data import get_daily_data
from quant_tool.indicators import compute_all_indicators
from quant_tool.strategies.trend import TrendStrategy
from quant_tool.strategies.mean_rev import MeanRevStrategy
from quant_tool.costs import CostModel
from quant_tool.backtest import Backtest
from quant_tool.portfolio import Portfolio
from quant_tool.metrics import summarize, portfolio_summary

logger = logging.getLogger(__name__)

def load_config(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def run_single_strategy(df: pd.DataFrame, config: dict, ticker: str, strategy_name: str, results_dir: str):
    logger.info(f"Running single strategy '{strategy_name}' on {ticker}")
    
    # 建立成本模型
    market = 'TW' if 'TW' in ticker else 'US'
    cost_model = CostModel.from_config(config.get('costs', {}), market)
    
    initial_capital = config.get('portfolio', {}).get('initial_capital', 1000000)
    warmup_days = config.get('warmup', {}).get('days', 200)

    # 將 config 壓平或提取給策略（雖然策略目前使用 config dict，但可以加入具體參數）
    strategy_config = {}
    strategy_config['warmup_days'] = warmup_days
    strategy_config['ma200_slope_threshold'] = config.get('filters', {}).get('ma200_slope_threshold', -0.005)
    
    # 初始化策略
    if strategy_name == 'trend':
        strategy = TrendStrategy(strategy_config)
    elif strategy_name == 'mean_rev':
        strategy = MeanRevStrategy(strategy_config)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    # 回測
    backtest = Backtest(strategy, initial_capital=initial_capital, warmup_days=warmup_days, cost_model=cost_model)
    result = backtest.run(df)
    
    # 績效報表
    report = summarize(result)
    print(f"\n=== {strategy_name.upper()} 績效報表 ({ticker}) ===")
    for k, v in report.items():
        if isinstance(v, float):
            print(f"{k}: {v:.4f}")
        else:
            print(f"{k}: {v}")

    # 輸出 CSV
    trades_path = os.path.join(results_dir, f"{strategy_name}_{ticker}_trades.csv")
    result.trades.to_csv(trades_path, index=False)
    
    equity_path = os.path.join(results_dir, f"{strategy_name}_{ticker}_equity.csv")
    result.equity_curve.to_csv(equity_path)
    
    # 繪製圖表
    plot_path = os.path.join(results_dir, f"{strategy_name}_{ticker}_equity.png")
    plt.figure(figsize=(10, 6))
    plt.plot(result.equity_curve.index, result.equity_curve['equity'], label='Equity')
    plt.title(f"{strategy_name.upper()} Equity Curve ({ticker})")
    plt.xlabel('Date')
    plt.ylabel('Equity')
    plt.legend()
    plt.grid(True)
    plt.savefig(plot_path)
    plt.close()
    
    logger.info(f"Results saved to {results_dir}")

def run_portfolio(df: pd.DataFrame, config: dict, ticker: str, results_dir: str):
    logger.info(f"Running portfolio on {ticker}")
    
    market = 'TW' if 'TW' in ticker else 'US'
    cost_model = CostModel.from_config(config.get('costs', {}), market)
    
    initial_capital = config.get('portfolio', {}).get('initial_capital', 1000000)
    warmup_days = config.get('warmup', {}).get('days', 200)
    rebalance_frequency = config.get('portfolio', {}).get('rebalance_frequency', 'quarterly')
    alloc_a = config.get('portfolio', {}).get('allocation', {}).get('strategy_a', 0.5)

    strategy_config = {}
    strategy_config['warmup_days'] = warmup_days
    strategy_config['ma200_slope_threshold'] = config.get('filters', {}).get('ma200_slope_threshold', -0.005)

    strategy_a = TrendStrategy(strategy_config)
    strategy_b = MeanRevStrategy(strategy_config)
    
    portfolio = Portfolio(
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        initial_capital=initial_capital,
        allocation_a=alloc_a,
        warmup_days=warmup_days,
        cost_model=cost_model,
        rebalance_frequency=rebalance_frequency
    )
    
    result = portfolio.run(df)
    
    report = portfolio_summary(
        combined_equity=result.combined_equity,
        equity_a=result.equity_a,
        equity_b=result.equity_b
    )
    
    print(f"\n=== 組合績效報表 ({ticker}) ===")
    print("【總體】")
    for k, v in report['combined'].items():
        print(f"  {k}: {v:.4f}")
    
    print("【策略A (Trend)】")
    for k, v in report['ledger_a'].items():
        print(f"  {k}: {v:.4f}")

    print("【策略B (MeanRev)】")
    for k, v in report['ledger_b'].items():
        print(f"  {k}: {v:.4f}")
        
    if not pd.isna(report['rolling_corr_mean']):
        print(f"滾動相關係數 (均值): {report['rolling_corr_mean']:.4f}")
    else:
        print("滾動相關係數 (均值): NaN")
    
    # 輸出 CSV
    rebalances_path = os.path.join(results_dir, f"portfolio_{ticker}_rebalances.csv")
    result.rebalances.to_csv(rebalances_path, index=False)
    
    equity_path = os.path.join(results_dir, f"portfolio_{ticker}_equity.csv")
    result.equity_curve.to_csv(equity_path)
    
    # 繪圖
    plot_path = os.path.join(results_dir, f"portfolio_{ticker}_equity.png")
    plt.figure(figsize=(12, 8))
    plt.plot(result.equity_curve.index, result.combined_equity, label='Combined Equity', linewidth=2)
    plt.plot(result.equity_curve.index, result.equity_a, label='Trend Equity (A)', alpha=0.7)
    plt.plot(result.equity_curve.index, result.equity_b, label='MeanRev Equity (B)', alpha=0.7)
    plt.title(f"Portfolio Equity Curve ({ticker})")
    plt.xlabel('Date')
    plt.ylabel('Equity')
    plt.legend()
    plt.grid(True)
    plt.savefig(plot_path)
    plt.close()
    
    logger.info(f"Results saved to {results_dir}")

def run_matrix(config: dict, ticker: str, results_dir: str):
    logger.info(f"Running matrix (foundational) on {ticker}")
    print("Matrix mode is a placeholder for Phase 12.")

def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    parser = argparse.ArgumentParser(description="Quant Trading System")
    parser.add_argument('--mode', type=str, choices=['single', 'portfolio', 'matrix'], default='portfolio', help='Execution mode')
    parser.add_argument('--ticker', type=str, default='VOO', help='Ticker to run on')
    parser.add_argument('--config', type=str, default='quant_tool/config.yaml', help='Path to config file')
    parser.add_argument('--strategy', type=str, choices=['trend', 'mean_rev'], default='trend', help='Strategy name (for single mode)')
    parser.add_argument('--results-dir', type=str, default='results', help='Directory to save results')
    
    args = parser.parse_args()
    
    os.makedirs(args.results_dir, exist_ok=True)
    config = load_config(args.config)
    
    if args.mode in ['single', 'portfolio']:
        df = get_daily_data(args.ticker)
        if df.empty:
            logger.error(f"Failed to load data for {args.ticker}")
            return
            
        df = compute_all_indicators(df)
        
        if args.mode == 'single':
            run_single_strategy(df, config, args.ticker, args.strategy, args.results_dir)
        elif args.mode == 'portfolio':
            run_portfolio(df, config, args.ticker, args.results_dir)
            
    elif args.mode == 'matrix':
        run_matrix(config, args.ticker, args.results_dir)

if __name__ == "__main__":
    main()
