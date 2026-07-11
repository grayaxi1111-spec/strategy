import pandas as pd
import numpy as np

def compute_sma(series: pd.Series, period: int) -> pd.Series:
    """計算簡單移動平均線 (SMA)"""
    return series.rolling(window=period).mean()

def compute_slope(series: pd.Series, period: int = 20) -> pd.Series:
    """計算斜率 (Rate of Change) - 預設 20 日變動率"""
    return series.pct_change(periods=period)

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """計算 RSI (Wilder's Smoothing)"""
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    
    # Wilder's Smoothing (RMA)
    roll_up = up.ewm(alpha=1/period, adjust=False).mean()
    roll_down = down.ewm(alpha=1/period, adjust=False).mean()
    
    rs = roll_up / roll_down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def compute_supertrend(high: pd.Series, low: pd.Series, close: pd.Series, 
                       atr_period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """計算 SuperTrend 指標"""
    # 1. 準備 ATR
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/atr_period, adjust=False).mean()

    # 2. 基本上下軌
    hl2 = (high + low) / 2
    basic_ub = hl2 + multiplier * atr
    basic_lb = hl2 - multiplier * atr

    # 3. 準備結果容器
    # 為提升效能，使用 NumPy array 取代 DataFrame iloc
    n = len(close)
    basic_ub_arr = basic_ub.to_numpy()
    basic_lb_arr = basic_lb.to_numpy()
    close_arr = close.to_numpy()
    
    final_ub_arr = np.zeros(n)
    final_lb_arr = np.zeros(n)
    supertrend_arr = np.zeros(n)
    supertrend_dir_arr = np.ones(n) # 1: 綠色 (上升), -1: 紅色 (下降)

    # 第一個有效值 (避免 nan 導致的比較錯誤)
    # 通常取 ATR 計算出來之後的第一個有效值
    start_idx = atr_period
    
    for i in range(start_idx, n):
        # Final Upper Band
        if basic_ub_arr[i] < final_ub_arr[i-1] or close_arr[i-1] > final_ub_arr[i-1]:
            final_ub_arr[i] = basic_ub_arr[i]
        else:
            final_ub_arr[i] = final_ub_arr[i-1]
            
        # Final Lower Band
        if basic_lb_arr[i] > final_lb_arr[i-1] or close_arr[i-1] < final_lb_arr[i-1]:
            final_lb_arr[i] = basic_lb_arr[i]
        else:
            final_lb_arr[i] = final_lb_arr[i-1]
            
        # SuperTrend Direction
        if supertrend_dir_arr[i-1] == 1:
            if close_arr[i] > final_lb_arr[i]:
                supertrend_dir_arr[i] = 1
            else:
                supertrend_dir_arr[i] = -1
        else:
            if close_arr[i] < final_ub_arr[i]:
                supertrend_dir_arr[i] = -1
            else:
                supertrend_dir_arr[i] = 1
                
        # SuperTrend Value
        if supertrend_dir_arr[i] == 1:
            supertrend_arr[i] = final_lb_arr[i]
        else:
            supertrend_arr[i] = final_ub_arr[i]

    # 將 nan 填回前面未計算的部分
    final_ub_arr[:start_idx] = np.nan
    final_lb_arr[:start_idx] = np.nan
    supertrend_arr[:start_idx] = np.nan
    supertrend_dir_arr[:start_idx] = np.nan

    return pd.DataFrame({
        'SuperTrend': supertrend_arr,
        'SuperTrend_Dir': supertrend_dir_arr,
        'SuperTrend_UB': final_ub_arr,
        'SuperTrend_LB': final_lb_arr,
    }, index=close.index)

def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    """計算 ADX"""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    up = high - high.shift(1)
    down = low.shift(1) - low
    
    pos_dm = np.where((up > down) & (up > 0), up, 0.0)
    neg_dm = np.where((down > up) & (down > 0), down, 0.0)
    
    pos_dm = pd.Series(pos_dm, index=close.index)
    neg_dm = pd.Series(neg_dm, index=close.index)
    
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    pos_di_smooth = pos_dm.ewm(alpha=1/period, adjust=False).mean()
    neg_di_smooth = neg_dm.ewm(alpha=1/period, adjust=False).mean()
    
    pos_di = 100 * (pos_di_smooth / atr)
    neg_di = 100 * (neg_di_smooth / atr)
    
    dx = 100 * (abs(pos_di - neg_di) / (pos_di + neg_di))
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    
    return pd.DataFrame({
        'ADX': adx,
        '+DI': pos_di,
        '-DI': neg_di
    })

def compute_all_indicators(df: pd.DataFrame, config: dict = None) -> pd.DataFrame:
    """計算所有指標並回傳帶有新欄位的 DataFrame，保證無未來函數"""
    res_df = df.copy()
    
    # 預設參數 (若有 config 可從 config 覆蓋)
    ma_periods = [5, 20, 60, 200]
    st_atr = 10
    st_mult = 3.0
    rsi_period = 2
    adx_period = 14
    
    if config:
        ind_cfg = config.get('indicators', {})
        ma_periods = ind_cfg.get('ma_periods', ma_periods)
        st_atr = ind_cfg.get('supertrend', {}).get('atr_period', st_atr)
        st_mult = ind_cfg.get('supertrend', {}).get('multiplier', st_mult)
        rsi_period = ind_cfg.get('rsi', {}).get('period', rsi_period)
        adx_period = ind_cfg.get('adx', {}).get('period', adx_period)
        
    # 計算 MA
    for p in ma_periods:
        res_df[f'MA{p}'] = compute_sma(res_df['close'], p)
        
    # 計算 MA200 斜率
    if 'MA200' in res_df.columns:
        # 預設使用 20 日作為變動率評估區間
        res_df['MA200_Slope'] = compute_slope(res_df['MA200'], 20)
        
    # 計算 SuperTrend
    st_df = compute_supertrend(res_df['high'], res_df['low'], res_df['close'], 
                               atr_period=st_atr, multiplier=st_mult)
    res_df = pd.concat([res_df, st_df], axis=1)
    
    # 計算 RSI
    res_df['RSI2'] = compute_rsi(res_df['close'], period=rsi_period)
    
    # 計算 ADX
    adx_df = compute_adx(res_df['high'], res_df['low'], res_df['close'], period=adx_period)
    res_df = pd.concat([res_df, adx_df], axis=1)
    
    return res_df
