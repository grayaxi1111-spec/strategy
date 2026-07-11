import os
import sqlite3
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "market_data.db")

def get_connection(db_path=DEFAULT_DB_PATH):
    """Get SQLite database connection"""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    return sqlite3.connect(db_path)

def _download_data(ticker: str, start: str = None, end: str = None) -> pd.DataFrame:
    """Download data from yfinance"""
    logger.info(f"Downloading {ticker} from {start} to {end}")
    df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
    
    if df.empty:
        return df

    # Flatten multi-index columns if present (yfinance sometimes returns multi-index for a single ticker)
    if isinstance(df.columns, pd.MultiIndex):
        # We only asked for one ticker, so we can drop the ticker level (usually level 1)
        # Check if 'Ticker' is in the names
        if 'Ticker' in df.columns.names:
            ticker_level_idx = df.columns.names.index('Ticker')
            df.columns = df.columns.droplevel(ticker_level_idx)
        else:
            # Fallback if names are different, usually level 1 is ticker if length is 2
            if len(df.columns.levels) > 1:
                df.columns = df.columns.droplevel(1)
        
    df.reset_index(inplace=True)
    
    # Ensure Date is timezone-naive string or datetime
    df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
    
    # Standardize column names
    df.rename(columns={
        'Date': 'date',
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume'
    }, inplace=True)
    
    # Sometimes yfinance returns columns in different order or with extra columns
    cols = ['date', 'open', 'high', 'low', 'close', 'volume']
    # keep only these columns if they exist
    existing_cols = [c for c in cols if c in df.columns]
    df = df[existing_cols]
    
    return df

def get_daily_data(ticker: str, db_path: str = DEFAULT_DB_PATH) -> pd.DataFrame:
    """
    Get daily data for a ticker. Uses local SQLite cache and incrementally updates it.
    """
    # Replace dots in ticker for sqlite table name
    table_name = ticker.replace('.', '_')
    
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        table_exists = cursor.fetchone() is not None
        
        start_date = None
        if table_exists:
            # Get last date
            cursor.execute(f"SELECT MAX(date) FROM {table_name}")
            last_date_str = cursor.fetchone()[0]
            if last_date_str:
                last_date = pd.to_datetime(last_date_str)
                # Next day after last available
                start_date = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
                
        # Download new data
        try:
            df_new = _download_data(ticker, start=start_date)
        except Exception as e:
            logger.error(f"Failed to download data for {ticker}: {e}")
            df_new = pd.DataFrame()
            
        if not df_new.empty:
            # Save to db
            # convert date to string for sqlite
            df_new['date'] = df_new['date'].dt.strftime('%Y-%m-%d')
            df_new.to_sql(table_name, conn, if_exists='append', index=False)
            logger.info(f"Appended {len(df_new)} rows to {table_name}")
            
        # Read full data from db
        if table_exists or not df_new.empty:
            df_full = pd.read_sql(f"SELECT * FROM {table_name} ORDER BY date ASC", conn)
            df_full['date'] = pd.to_datetime(df_full['date'])
            return df_full
        else:
            return pd.DataFrame()
