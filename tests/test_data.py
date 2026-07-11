import os
import pandas as pd
import pytest
from unittest.mock import patch
from quant_tool.data import get_daily_data, _download_data

@pytest.fixture
def temp_db_path(tmp_path):
    return os.path.join(tmp_path, "test_market_data.db")

def test_download_data_voo():
    # Test direct download via yfinance
    df = _download_data("VOO", start="2024-01-01", end="2024-01-10")
    assert not df.empty
    assert "date" in df.columns
    assert "close" in df.columns
    # Check if date is datetime
    assert pd.api.types.is_datetime64_any_dtype(df["date"])

def test_download_data_0050():
    # Test 0050.TW ticker
    df = _download_data("0050.TW", start="2024-01-01", end="2024-01-10")
    assert not df.empty
    assert "date" in df.columns
    assert "close" in df.columns

def test_get_daily_data_cache_and_incremental(temp_db_path):
    # First download
    with patch('quant_tool.data._download_data') as mock_download:
        mock_download.return_value = pd.DataFrame({
            'date': pd.to_datetime(['2024-01-02', '2024-01-03']),
            'open': [100.0, 101.0],
            'high': [102.0, 103.0],
            'low': [99.0, 100.0],
            'close': [101.5, 102.5],
            'volume': [1000, 2000]
        })
        
        df1 = get_daily_data("TEST_TICKER", db_path=temp_db_path)
        assert len(df1) == 2
        mock_download.assert_called_once_with("TEST_TICKER", start=None)
        
    # Second download (incremental)
    with patch('quant_tool.data._download_data') as mock_download:
        mock_download.return_value = pd.DataFrame({
            'date': pd.to_datetime(['2024-01-04']),
            'open': [102.0],
            'high': [104.0],
            'low': [101.0],
            'close': [103.5],
            'volume': [1500]
        })
        
        df2 = get_daily_data("TEST_TICKER", db_path=temp_db_path)
        assert len(df2) == 3
        assert df2['date'].iloc[-1].strftime('%Y-%m-%d') == '2024-01-04'
        mock_download.assert_called_once_with("TEST_TICKER", start="2024-01-04")
        
    # Third download (no new data)
    with patch('quant_tool.data._download_data') as mock_download:
        mock_download.return_value = pd.DataFrame()
        
        df3 = get_daily_data("TEST_TICKER", db_path=temp_db_path)
        assert len(df3) == 3
        mock_download.assert_called_once_with("TEST_TICKER", start="2024-01-05")
