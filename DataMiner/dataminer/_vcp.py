"""
TOOD: add VcpConfig
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from detonator import get_logger,SingletonParent
from pandas import DataFrame
from scipy.stats import linregress


@dataclass
class VcpConfig:
    pass


class VCPAnalyzer(SingletonParent):
    """
    Advanced Volatility Contraction Pattern (VCP) Analyzer.
    Uses Variance Funnels and Linear Decay to detect the 'Squeeze'.
    """

    def __init__(self, cfg: VcpConfig=None):
        self._cfg = cfg or VcpConfig()
        self._logger = get_logger('VcpAnalyzer')

    def calculate_vcp_metrics(self, df: DataFrame, window_short:int=5, window_med:int=10, window_long:int=20) -> dict:
        """
        Calculates advanced VCP metrics using Log Returns and ATR Slope.
        使用对数收益率和 ATR 斜率计算高级 VCP 指标。
        """
        # Ensure we have enough data
        if len(df) < window_long + 2:
            self._logger.debug("Skipping %s: too few rows", df.iloc[0]['Ticker'])
            return None

        # 1. Prepare Data: Log Returns (More accurate than percentage change for math)
        df = df.copy()
        df['Log_Ret'] = np.log(df['Close'] / df['Close'].shift(1))

        # 2. The Variance Funnel (Multi-Timeframe Standard Deviation)
        # We calculate the Std Dev of returns over 3 windows
        vol_short = df['Log_Ret'].rolling(window=window_short).std().iloc[-1]
        vol_med = df['Log_Ret'].rolling(window=window_med).std().iloc[-1]
        vol_long = df['Log_Ret'].rolling(window=window_long).std().iloc[-1]

        # Avoid division by zero
        if vol_long == 0:
            self._logger.debug("Skipping %s: too few rows", df.iloc[0]['Ticker'])
            return None

        # Funnel Check: Is Short < Med < Long?
        # A perfect VCP should have ratios < 1.0
        ratio_short_med = vol_short / vol_med if vol_med > 0 else 1.0
        ratio_med_long = vol_med / vol_long if vol_long > 0 else 1.0

        # 3. ATR Slope (Linear Regression of Volatility)
        # Calculate Normalized ATR (NATR) to make it price-agnostic
        df['TR'] = np.maximum(df['High'] - df['Low'],
                              np.maximum(abs(df['High'] - df['Close'].shift(1)),
                                         abs(df['Low'] - df['Close'].shift(1))))
        df['ATR'] = df['TR'].rolling(window=14).mean()
        df['NATR'] = (df['ATR'] / df['Close']) * 100

        # Get last 20 days of NATR
        recent_natr = df['NATR'].iloc[-20:].dropna()

        if len(recent_natr) < 20:
            atr_slope = 0
        else:
            # X axis is just [0, 1, 2... 19]
            x = np.arange(len(recent_natr))
            slope, _, _, _, _ = linregress(x, recent_natr.values)
            atr_slope = slope  # Negative slope means tightening

        # 4. Bollinger Band Width Squeeze (The "Squeeze" Indicator)
        # Standard calculation: (Upper - Lower) / Middle
        sma = df['Close'].rolling(20).mean()
        std = df['Close'].rolling(20).std()
        upper = sma + (2 * std)
        lower = sma - (2 * std)
        bb_width = (upper - lower) / sma

        # Calculate percentile of current width vs last 6 months (126 days)
        # Current width should be at the low end of its history
        current_width = bb_width.iloc[-1]
        min_width_6m = bb_width.iloc[-126:].min()
        max_width_6m = bb_width.iloc[-126:].max()

        # Squeeze percentile: 0.0 = tightest in 6 months, 1.0 = widest
        if (max_width_6m - min_width_6m) == 0:
            squeeze_pct = 0.5
        else:
            squeeze_pct = (current_width - min_width_6m) / (max_width_6m - min_width_6m)

        return {
            "Vol_Ratio_Short": ratio_short_med,  # Should be < 1.0
            "Vol_Ratio_Med": ratio_med_long,  # Should be < 1.0
            "ATR_Slope": atr_slope,  # Should be Negative (< 0)
            "BB_Squeeze_Pct": squeeze_pct,  # Should be Low (< 0.10 is extreme squeeze)
            "Is_Funnel": (vol_short < vol_med) and (vol_med < vol_long)
        }

    # How to use this inside the previous analyze_ticker function:
    def check_advanced_vcp(self, df:DataFrame):
        metrics = self.calculate_vcp_metrics(df)
        if not metrics: 
            self._logger.warning("Skipping %s: no metrics", df.iloc[0]['Ticker'])
            return None
        # STRICT CRITERIA FOR PRODUCT READY SCANNER
        # 1. Variance Funnel must be present or Short term vol must be deeply crushed
        is_tight = (metrics['Vol_Ratio_Short'] < 0.75)

        # 2. ATR should be decaying (negative slope) OR already very flat
        is_decaying = (metrics['ATR_Slope'] < 0)

        # 3. Bollinger Squeeze: Must be in the bottom 20% of its 6-month range
        is_squeezing = (metrics['BB_Squeeze_Pct'] < 0.20)

        # Composite VCP Score (Higher is better)
        vcp_score = 0
        if is_tight: vcp_score += 40
        if metrics['Is_Funnel']: vcp_score += 20
        if is_decaying: vcp_score += 20
        if is_squeezing: vcp_score += 20

        return vcp_score, metrics
