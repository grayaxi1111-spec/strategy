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
from quant_tool.strategies.bnh import BuyAndHoldStrategy
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

def run_matrix(config: dict, default_ticker: str, results_dir: str):
    logger.info("Running Phase 12 Backtest Matrix Validation")
    
    # 準備資料
    tickers = ['VOO', '0050.TW']
    data_dict = {}
    for t in tickers:
        df = get_daily_data(t)
        if not df.empty:
            data_dict[t] = compute_all_indicators(df)
        else:
            logger.error(f"Failed to load data for {t}, skipping.")

    initial_capital = config.get('portfolio', {}).get('initial_capital', 1000000)
    warmup_days = config.get('warmup', {}).get('days', 200)
    rebalance_freq = config.get('portfolio', {}).get('rebalance_frequency', 'quarterly')
    alloc_a = config.get('portfolio', {}).get('allocation', {}).get('strategy_a', 0.5)
    
    strategy_config = {}
    strategy_config['warmup_days'] = warmup_days
    strategy_config['ma200_slope_threshold'] = config.get('filters', {}).get('ma200_slope_threshold', -0.005)

    results = []

    def _add_result(phase, name, ticker, report):
        results.append({
            'Phase': phase,
            'Name': name,
            'Ticker': ticker,
            'CAGR': f"{report.get('cagr', 0)*100:.2f}%",
            'MDD': f"{report.get('mdd', 0)*100:.2f}%",
            'Sharpe': f"{report.get('sharpe', 0):.2f}",
            'Win Rate': f"{report.get('win_rate', 0)*100:.1f}%" if 'win_rate' in report else '-',
            'P/L Ratio': f"{report.get('profit_loss_ratio', 0):.2f}" if 'profit_loss_ratio' in report else '-',
            'Trades/Yr': f"{report.get('trades_per_year', 0):.1f}" if 'trades_per_year' in report else '-',
        })

    for t in tickers:
        if t not in data_dict:
            continue
        df = data_dict[t]
        market = 'TW' if 'TW' in t else 'US'
        cost_model = CostModel.from_config(config.get('costs', {}), market)

        # === Phase 1: B&H (Lump Sum) ===
        # 使用 Portfolio (50/50 兩邊都放 B&H) 達成 100% 參與
        dca_amount = 0.0
        port_bh = Portfolio(
            strategy_a=BuyAndHoldStrategy(strategy_config),
            strategy_b=BuyAndHoldStrategy(strategy_config),
            initial_capital=initial_capital,
            allocation_a=0.5,
            warmup_days=warmup_days,
            cost_model=cost_model,
            rebalance_frequency=None,
            dca_amount=dca_amount
        )
        res_bh = port_bh.run(df)
        rep_bh = portfolio_summary(res_bh.combined_equity, res_bh.equity_a, res_bh.equity_b)
        _add_result('Phase 1', 'B&H (DCA)', t, rep_bh['combined'])

        # === Phase 2: Trend Daily ===
        bt_trend = Backtest(TrendStrategy(strategy_config), initial_capital=initial_capital, warmup_days=warmup_days, cost_model=cost_model)
        res_trend = bt_trend.run(df)
        _add_result('Phase 2', 'Trend (Daily)', t, summarize(res_trend))

        # === Phase 2: Trend Weekly (VOO only) ===
        if t == 'VOO':
            df_weekly = df.resample('W-FRI', on='date').agg({
                'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
            }).dropna().reset_index()
            df_weekly = compute_all_indicators(df_weekly)
            bt_trend_w = Backtest(TrendStrategy(strategy_config), initial_capital=initial_capital, warmup_days=warmup_days//5, cost_model=cost_model)
            res_trend_w = bt_trend_w.run(df_weekly)
            _add_result('Phase 2', 'Trend (Weekly)', t, summarize(res_trend_w))

        # === Phase 3: MeanRev Daily ===
        bt_mr = Backtest(MeanRevStrategy(strategy_config), initial_capital=initial_capital, warmup_days=warmup_days, cost_model=cost_model)
        res_mr = bt_mr.run(df)
        _add_result('Phase 3', 'MeanRev (Daily)', t, summarize(res_mr))

        # === Phase 4: Portfolio A+B ===
        port_ab = Portfolio(
            strategy_a=TrendStrategy(strategy_config),
            strategy_b=MeanRevStrategy(strategy_config),
            initial_capital=initial_capital,
            allocation_a=alloc_a,
            warmup_days=warmup_days,
            cost_model=cost_model,
            rebalance_frequency=rebalance_freq,
            dca_amount=0.0  # 根據基準，組合也可加入 DCA 或不加。此處展示無 DCA 的 A+B
        )
        res_ab = port_ab.run(df)
        rep_ab = portfolio_summary(res_ab.combined_equity, res_ab.equity_a, res_ab.equity_b)
        _add_result('Phase 4', 'A+B Portfolio', t, rep_ab['combined'])

    # === Phase 5: 敏感度測試 (以 VOO Portfolio 為例，調整 MA200斜率閾值 ±20%) ===
    if 'VOO' in data_dict:
        t = 'VOO'
        df = data_dict[t]
        market = 'US'
        cost_model = CostModel.from_config(config.get('costs', {}), market)
        base_thresh = config.get('filters', {}).get('ma200_slope_threshold', -0.005)
        
        for variant, factor in [('Thresh -20%', 1.2), ('Thresh +20%', 0.8)]:
            sc = strategy_config.copy()
            sc['ma200_slope_threshold'] = base_thresh * factor
            port_sens = Portfolio(
                strategy_a=TrendStrategy(sc),
                strategy_b=MeanRevStrategy(sc),
                initial_capital=initial_capital,
                allocation_a=alloc_a,
                warmup_days=warmup_days,
                cost_model=cost_model,
                rebalance_frequency=rebalance_freq
            )
            res_sens = port_sens.run(df)
            rep_sens = portfolio_summary(res_sens.combined_equity, res_sens.equity_a, res_sens.equity_b)
            _add_result('Phase 5', f'A+B Sens ({variant})', t, rep_sens['combined'])

    # TODO: Phase 6 Variants (槓桿, 債券輪動, ADX濾網) 待未來實作
    results.append({
        'Phase': 'Phase 6', 'Name': 'Variants (Leverage/Bond/ADX)', 'Ticker': 'VOO/0050',
        'CAGR': 'TODO', 'MDD': 'TODO', 'Sharpe': 'TODO', 'Win Rate': '-', 'P/L Ratio': '-', 'Trades/Yr': '-'
    })

    # Print results
    res_df = pd.DataFrame(results)
    print("\n=== 回測矩陣結果 (Phase 12) ===")
    print(res_df.to_markdown(index=False))
    
    # Save to CSV
    csv_path = os.path.join(results_dir, "matrix_results.csv")
    res_df.to_csv(csv_path, index=False)
    logger.info(f"Matrix results saved to {csv_path}")

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
