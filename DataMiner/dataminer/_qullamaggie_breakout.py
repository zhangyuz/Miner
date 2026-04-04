"""
Qullamaggie Breakout Strategy
Assume: 21 trading days = 1 month, 252 trading days = 1 year.
"""

from dataclasses import dataclass
from typing import Optional, Dict

import numpy as np
import pandas as pd
from detonator import get_logger, SingletonParent
from pandas import DataFrame
from scipy.stats import linregress

from ._market_data_shovel import  MarketDataShovel
from ._trade_cal import  TradeCalendarShovel
from ._vcp import VCP


@dataclass
class QullamaggieBreakoutConfig:
    """
    Configuration for Qullamaggie Breakout Strategy.
    Defaults represent the "Sweet Spot" for HFF (High Tight Flag) setups.
    """
    # 1. Universe Filters (Liquidity & Price)
    min_price: float = 5.0
    min_dollar_vol: float = 10_000_000  # $10M/day (Avoid slippage on size)

    # 2. The "Super Stock" Trend Filters
    min_roc_6m: float = 30.0  # Episodic momentum requirement
    min_adr_pct: float = 3.5  # Average Daily Range % (Don't trade boring stocks)
    min_trend_quality: float = 0.80  # R-squared value of the trend (Smoothness)

    # 3. Moving Average "Surfing" logic
    ma_fast: int = 10
    ma_medium: int = 20
    ma_slow: int = 50

    # 4. The Setup (Consolidation & Tightness)
    consolidation_period: int = 20  # Look back period for highs
    max_drawdown_from_high: float = 0.12  # Can't be more than 12% off highs (Deep bases are bad)
    tightness_period: int = 5
    max_tightness_ratio: float = 0.65  # Recent volatility must be < 65% of historical


class QullamaggieBreakout(SingletonParent):
    def __init__(self, config: QullamaggieBreakoutConfig):
        self.cfg = config
        self._logger = get_logger(self.__class__.__name__)

    def _calc_rsquared(self, series: pd.Series) -> float:
        """Calculates the R^2 (smoothness) of a series against time."""
        # A perfect line up has R^2 = 1.0. Choppy mess has R^2 ~ 0.
        y = series.values
        x = np.arange(len(y))
        slope, intercept, r_value, p_value, std_err = linregress(x, y)
        return r_value ** 2

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df['Close']
        volume = df['Volume']

        # 1. Moving Averages
        df['SMA_10'] = close.rolling(self.cfg.ma_fast).mean()
        df['SMA_20'] = close.rolling(self.cfg.ma_medium).mean()
        df['SMA_50'] = close.rolling(self.cfg.ma_slow).mean()
        df['Vol_SMA_50'] = volume.rolling(50).mean()

        # 2. Dollar Volume (Liquidity)
        df['Dollar_Vol'] = (close + df['Open'] + df['Low'] + df['High']) * volume / 4
        df['Avg_Dollar_Vol_20'] = df['Dollar_Vol'].rolling(20).mean()

        # 3. ADR% (Average Daily Range) - Crucial for Qullamaggie
        # High/Low for the day expressed as a percentage
        daily_range_pct = (df['High'] / df['Low'] - 1) * 100
        df['ADR_20'] = daily_range_pct.rolling(20).mean()

        # 4. Momentum (Rate of Change)
        df['ROC_6M'] = close.pct_change(132) * 100  # ~6 months
        df['ROC_3M'] = close.pct_change(66) * 100
        df['ROC_1M'] = close.pct_change(22) * 100

        # 5. Volatility (ATR) & Tightness
        # Simple Tightness: (High - Low) / Close
        range_pct = (df['High'] - df['Low']) / close
        df['Avg_Range_Pct_20'] = range_pct.rolling(20).mean()
        df['Avg_Range_Pct_Recent'] = range_pct.rolling(self.cfg.tightness_period).mean()

        # Ratio < 1 means contracting. We want < 0.65 ideally.
        df['Tightness_Ratio'] = df['Avg_Range_Pct_Recent'] / df['Avg_Range_Pct_20']

        # 6. Trend Quality (Linearity of the last 3 months)
        # We apply this via rolling apply, but for speed in Python,
        # we will calculate it only for the last candle in the analyze function.

        return df

    def analyze_stock(self, df: DataFrame) -> Optional[Dict]:
        if df is None or df.empty:
            self._logger.warning(f"Skipping: No data to analyze")

        try:
            # Standardize headers
            df.columns = [c.title() for c in df.columns]
            ticker = df.iloc[0]['Ticker']

            # Fast Fail 1: Not enough data
            if len(df) < 135:
                self._logger.debug(f"Skipping {ticker}: {len(df)} rows")
                return None

            # Fast Fail 2: Price too low (Penny stocks)
            if df['Close'].iloc[-1] < self.cfg.min_price:
                self._logger.debug(f"Skipping {ticker}: price({df['Close'].iloc[-1]}) is lower than {self.cfg.min_price}")
                return None

            # Calculate Indicators
            df = self._calculate_indicators(df)
            curr = df.iloc[-1]

            # --- FILTER GATE 1: Liquidity & Personality ---
            if curr['Avg_Dollar_Vol_20'] < self.cfg.min_dollar_vol:
                self._logger.debug(f"Skipping {ticker}: liquidity not enough")
                return None
            if curr['ADR_20'] < self.cfg.min_adr_pct:
                self._logger.debug(f"Skipping {ticker}: moves too slow")
                return None  # Moves too slow

            # --- FILTER GATE 2: The Trend (The "Surfing") ---
            # 1. Price > SMA10 > SMA20 > SMA50 (Ideal stacking)
            # OR at least Price > SMA20 > SMA50 for early entries
            trend_stacked = (curr['SMA_10'] > curr['SMA_20']) and (curr['SMA_20'] > curr['SMA_50'])
            price_surfing = curr['Close'] > curr['SMA_20']

            if not (trend_stacked and price_surfing):
                self._logger.debug(f"Skipping {ticker}: no trend stacked")
                return None

            # --- FILTER GATE 3: Momentum ---
            # Qullamaggie needs a prior "Episode". Look for >30% in 6m.
            if curr['ROC_6M'] < self.cfg.min_roc_6m:
                return None

            # --- FILTER GATE 4: The Setup (Consolidation) ---
            # Calculate Highest High of last 20 days
            high_20d = df['High'].iloc[-self.cfg.consolidation_period:].max()
            dd_from_high = (high_20d - curr['Close']) / high_20d

            if dd_from_high > self.cfg.max_drawdown_from_high:
                self._logger.debug(f"Skipping {ticker}: drawdown too deep")
                return None  # Too deep, broken setup

            # --- FILTER GATE 5: Tightness (The Trigger) ---
            if curr['Tightness_Ratio'] > self.cfg.max_tightness_ratio:
                self._logger.debug(f"Skipping {ticker}: tightness not tightening enough")
                return None  # Too loose, needs more time

            # --- FILTER GATE 6: Trend Quality (Expensive calc, do last) ---
            # Calculate R-squared of the last 20 closes (approx 2 months of smoothness)
            recent_closes = df['Close'].iloc[-20:]
            trend_quality = self._calc_rsquared(recent_closes)

            if trend_quality < self.cfg.min_trend_quality:
                self._logger.debug(f"Skipping {ticker}: trend quality not enough")
                return None  # Choppy trend, headache stock

            # --- SCORING (Q-Score) ---
            # Create a composite score to rank the best setups
            # 1. Tighter is better (Weight: 40%)
            # 2. Higher ADR is better (Weight: 30%)
            # 3. Smoother Trend is better (Weight: 30%)

            score_tight = max(0, 1 - curr['Tightness_Ratio']) * 100  # Lower ratio = higher score
            score = (score_tight * 0.4) + (curr['ADR_20'] * 3.0) + (trend_quality * 30)

            return {
                "Ticker": ticker,
                "Date": curr['Date'],
                "Price": round(curr['Close'], 2),
                "Q_Score": round(score, 1),
                "ADR%": round(curr['ADR_20'], 1),
                "Tightness": round(curr['Tightness_Ratio'], 2),
                "Dist_High%": round(dd_from_high * 100, 1),
                "Vol_Surge": round(curr['Volume'] / curr['Vol_SMA_50'], 1),
                "Trend_R2": round(trend_quality, 2),
                "ROC_6M": round(curr['ROC_6M'], 0)
            }

        except Exception as e:
            # logger.warning(f"Skipping {ticker}: {e}")
            self._logger.error(f"Exception: {e}")
            return None


    def update_qullamaggie_breakout(self, trade_date:str) -> DataFrame:
        """
        Lets find the breakouts
        """
        mds:MarketDataShovel = MarketDataShovel.get_instance()
        tcs:TradeCalendarShovel = TradeCalendarShovel.get_instance()
        last_closed_date:str = tcs.get_last_closed_trade_date_before(trade_date, country='us', exchange='XNYS')
        trade_date_21_days_ago:str = tcs.get_us_trade_date_N_days_ago(21)
        trade_date_63_days_ago:str = tcs.get_us_trade_date_N_days_ago(63)
        trade_date_126_days_ago:str = tcs.get_us_trade_date_N_days_ago(126)
        bars_last = mds.get_historical_bars(interval='1d', start_date=last_closed_date, end_date=last_closed_date)
        bars21:Dict[str, DataFrame] = mds.get_historical_bars(interval='1d', start_date=trade_date_21_days_ago, end_date=last_closed_date)
        bars63:Dict[str, DataFrame] = mds.get_historical_bars(interval='1d', start_date=trade_date_63_days_ago, end_date=last_closed_date)
        bars126:Dict[str, DataFrame] = mds.get_historical_bars(interval='1d', start_date=trade_date_126_days_ago, end_date=last_closed_date)
        # compare close price of bars_last and bars21, bars63, bars126 and find top 2% raising stocks
        top_2_raising_stocks = []
        top_2_raising_stocks_percent = 0.02
        top_2_raising_stocks.extend(
            ticker
            for ticker, bars in bars_last.items()
            if bars['Close'].iloc[-1] > bars21[ticker]['Close'].iloc[-1]
            and bars['Close'].iloc[-1] > bars63[ticker]['Close'].iloc[-1]
            and bars['Close'].iloc[-1] > bars126[ticker]['Close'].iloc[-1]
        )
        top_2_raising_stocks.sort(key=lambda x: bars_last[x]['Close'].iloc[-1], reverse=True)
        top_2_raising_stocks = top_2_raising_stocks[:int(len(top_2_raising_stocks) * top_2_raising_stocks_percent)]
        return top_2_raising_stocks

