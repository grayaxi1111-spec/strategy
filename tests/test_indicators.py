import unittest
import pandas as pd
import numpy as np
from quant_tool.indicators import compute_sma, compute_slope, compute_rsi, compute_supertrend, compute_adx, compute_all_indicators

class TestIndicators(unittest.TestCase):
    def setUp(self):
        # Create a simple trend dataset for testing
        dates = pd.date_range('2020-01-01', periods=100)
        self.df = pd.DataFrame({
            'open': np.linspace(10, 110, 100),
            'high': np.linspace(12, 112, 100),
            'low': np.linspace(8, 108, 100),
            'close': np.linspace(10, 110, 100),
            'volume': np.random.randint(100, 1000, 100)
        }, index=dates)
        
    def test_compute_sma(self):
        sma5 = compute_sma(self.df['close'], 5)
        self.assertTrue(np.isnan(sma5.iloc[0]))
        # (10 + 11.0101 + 12.0202 + 13.0303 + 14.0404) / 5
        self.assertAlmostEqual(sma5.iloc[4], self.df['close'].iloc[0:5].mean())
        
    def test_compute_slope(self):
        slope = compute_slope(self.df['close'], 10)
        self.assertTrue(np.isnan(slope.iloc[0]))
        self.assertAlmostEqual(slope.iloc[10], (self.df['close'].iloc[10] - self.df['close'].iloc[0]) / self.df['close'].iloc[0])

    def test_compute_rsi(self):
        # A constantly increasing series should have RSI near 100 after some periods
        rsi = compute_rsi(self.df['close'], period=14)
        self.assertTrue(np.isnan(rsi.iloc[0]))
        # Since it only goes up, RSI should be 100.
        self.assertAlmostEqual(rsi.iloc[-1], 100.0)

    def test_compute_supertrend(self):
        st_df = compute_supertrend(self.df['high'], self.df['low'], self.df['close'], atr_period=10, multiplier=3)
        self.assertIn('SuperTrend', st_df.columns)
        self.assertIn('SuperTrend_Dir', st_df.columns)
        # Because the price goes up constantly, it should be in an uptrend (direction = 1)
        self.assertEqual(st_df['SuperTrend_Dir'].iloc[-1], 1)
        # In an uptrend the SuperTrend line acts as a support line below price
        valid = st_df.dropna(subset=['SuperTrend'])
        self.assertTrue((self.df['close'].loc[valid.index] > valid['SuperTrend']).all())

    def test_compute_adx(self):
        adx_df = compute_adx(self.df['high'], self.df['low'], self.df['close'], period=14)
        self.assertIn('ADX', adx_df.columns)
        self.assertIn('+DI', adx_df.columns)
        self.assertIn('-DI', adx_df.columns)
        # A one-directional trend has no down-moves, so -DI should collapse to ~0
        # and +DI should dominate, driving ADX toward its max (100) as trend strength is confirmed
        self.assertAlmostEqual(adx_df['-DI'].iloc[-1], 0.0, places=4)
        self.assertGreater(adx_df['+DI'].iloc[-1], 0)
        self.assertGreater(adx_df['ADX'].iloc[-1], 90)

    def test_compute_all_indicators(self):
        res_df = compute_all_indicators(self.df)
        expected_cols = [
            'MA5', 'MA20', 'MA60', 'MA200',
            'SuperTrend', 'SuperTrend_Dir', 'SuperTrend_UB', 'SuperTrend_LB',
            'RSI2', 'ADX', '+DI', '-DI'
        ]
        for col in expected_cols:
            self.assertIn(col, res_df.columns)

if __name__ == '__main__':
    unittest.main()
