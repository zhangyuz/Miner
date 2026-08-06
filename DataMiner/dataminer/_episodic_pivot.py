"""
Episodic Pivot analyzer.

The core logic is intentionally pure: callers pass OHLCV dataframes in and get
ranked signal objects back. Database access, if used by callers, should remain a
read-only data loading concern outside the signal calculation path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd
from detonator import make_db_connection, mongo_2_df
from pandas import DataFrame

from .models import TickerDailyInfo


@dataclass(frozen=True)
class EpisodicPivotConfig:
    min_price: float = 5.0
    min_avg_dollar_volume: float = 10_000_000.0
    min_gap_pct: float = 0.10
    min_relative_volume: float = 3.0
    avg_volume_window: int = 50
    adr_window: int = 20
    neglect_lookback: int = 63
    max_pre_event_run_pct: float = 0.60
    max_base_range_pct: float = 0.80
    max_stop_adr_multiple: float = 1.5
    opening_range_minutes: int = 5
    entry_buffer_pct: float = 0.0
    require_catalyst: bool = False


@dataclass(frozen=True)
class EpisodicPivotCatalyst:
    kind: str = 'unknown'
    headline: str = ''
    reported_at: Optional[datetime] = None
    revenue_growth_yoy: Optional[float] = None
    eps_growth_yoy: Optional[float] = None
    revenue_surprise_pct: Optional[float] = None
    eps_surprise_pct: Optional[float] = None
    guidance_raised: bool = False

    def quality_score(self) -> float:
        score = 0.0
        if self.kind.lower() in {'earnings', 'guidance', 'fda', 'contract', 'regulatory'}:
            score += 0.35
        if self.revenue_growth_yoy is not None:
            score += min(max(self.revenue_growth_yoy, 0.0) / 0.50, 1.0) * 0.20
        if self.eps_growth_yoy is not None:
            score += min(max(self.eps_growth_yoy, 0.0) / 1.00, 1.0) * 0.20
        if self.revenue_surprise_pct is not None:
            score += min(max(self.revenue_surprise_pct, 0.0) / 0.20, 1.0) * 0.10
        if self.eps_surprise_pct is not None:
            score += min(max(self.eps_surprise_pct, 0.0) / 0.30, 1.0) * 0.10
        if self.guidance_raised:
            score += 0.15
        if self.headline:
            score += 0.05
        return min(score, 1.0)


@dataclass(frozen=True)
class EpisodicPivotSignal:
    ticker: str
    trade_date: Any
    is_candidate: bool
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    reject_reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    catalyst: Optional[EpisodicPivotCatalyst] = None
    previous_close: float = np.nan
    open: float = np.nan
    high: float = np.nan
    low: float = np.nan
    close: float = np.nan
    volume: float = np.nan
    avg_volume: float = np.nan
    avg_dollar_volume: float = np.nan
    gap_pct: float = np.nan
    day_gain_pct: float = np.nan
    relative_volume: float = np.nan
    adr_pct: float = np.nan
    pre_event_run_pct: float = np.nan
    base_range_pct: float = np.nan
    close_position: float = np.nan

    def to_dict(self) -> dict[str, Any]:
        return {
            'ticker': self.ticker,
            'trade_date': self.trade_date,
            'is_candidate': self.is_candidate,
            'score': self.score,
            'reasons': list(self.reasons),
            'reject_reasons': list(self.reject_reasons),
            'warnings': list(self.warnings),
            'catalyst_kind': self.catalyst.kind if self.catalyst else None,
            'previous_close': self.previous_close,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'avg_volume': self.avg_volume,
            'avg_dollar_volume': self.avg_dollar_volume,
            'gap_pct': self.gap_pct,
            'day_gain_pct': self.day_gain_pct,
            'relative_volume': self.relative_volume,
            'adr_pct': self.adr_pct,
            'pre_event_run_pct': self.pre_event_run_pct,
            'base_range_pct': self.base_range_pct,
            'close_position': self.close_position,
        }


@dataclass(frozen=True)
class OpeningRangeTradePlan:
    ticker: str
    trade_date: Any
    is_tradeable: bool
    entry: float
    stop: float
    risk_pct: float
    risk_adr_multiple: float
    opening_range_high: float
    opening_range_low: float
    opening_range_minutes: int
    reject_reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            'ticker': self.ticker,
            'trade_date': self.trade_date,
            'is_tradeable': self.is_tradeable,
            'entry': self.entry,
            'stop': self.stop,
            'risk_pct': self.risk_pct,
            'risk_adr_multiple': self.risk_adr_multiple,
            'opening_range_high': self.opening_range_high,
            'opening_range_low': self.opening_range_low,
            'opening_range_minutes': self.opening_range_minutes,
            'reject_reasons': list(self.reject_reasons),
            'warnings': list(self.warnings),
        }


class EpisodicPivotAnalyzer:
    REQUIRED_DAILY_COLUMNS = ('open', 'high', 'low', 'close', 'volume')
    REQUIRED_INTRADAY_COLUMNS = ('open', 'high', 'low', 'close')

    def __init__(self, cfg: Optional[EpisodicPivotConfig] = None):
        self.cfg = cfg or EpisodicPivotConfig()

    def analyze_daily_bars(
        self,
        bars: DataFrame,
        ticker: Optional[str] = None,
        catalyst: Optional[EpisodicPivotCatalyst] = None,
    ) -> Optional[EpisodicPivotSignal]:
        bars = self._normalize_ohlcv(bars)
        min_rows = max(
            self.cfg.avg_volume_window,
            self.cfg.adr_window,
            self.cfg.neglect_lookback,
        ) + 1
        if len(bars) < min_rows:
            return None

        event = bars.iloc[-1]
        prior = bars.iloc[:-1]
        ticker = ticker or str(event.get('ticker', ''))

        avg_volume = float(prior['volume'].tail(self.cfg.avg_volume_window).mean())
        avg_dollar_volume = float(
            ((prior['open'] + prior['high'] + prior['low'] + prior['close']) / 4 * prior['volume'])
            .tail(self.cfg.avg_volume_window)
            .mean()
        )
        previous_close = float(prior['close'].iloc[-1])
        gap_pct = float(event['open'] / previous_close - 1)
        day_gain_pct = float(event['close'] / previous_close - 1)
        relative_volume = float(event['volume'] / avg_volume) if avg_volume > 0 else np.nan
        adr_pct = float((prior['high'] / prior['low'] - 1).tail(self.cfg.adr_window).mean())

        neglect_window = prior.tail(self.cfg.neglect_lookback)
        pre_event_run_pct = float(previous_close / neglect_window['close'].iloc[0] - 1)
        base_range_pct = float(neglect_window['high'].max() / neglect_window['low'].min() - 1)
        daily_range = float(event['high'] - event['low'])
        close_position = float((event['close'] - event['low']) / daily_range) if daily_range > 0 else 0.5

        reasons: list[str] = []
        reject_reasons: list[str] = []
        warnings: list[str] = []

        if event['close'] >= self.cfg.min_price:
            reasons.append('price')
        else:
            reject_reasons.append('price_below_minimum')
        if avg_dollar_volume >= self.cfg.min_avg_dollar_volume:
            reasons.append('liquidity')
        else:
            reject_reasons.append('avg_dollar_volume_below_minimum')
        if gap_pct >= self.cfg.min_gap_pct:
            reasons.append('gap')
        else:
            reject_reasons.append('gap_below_minimum')
        if relative_volume >= self.cfg.min_relative_volume:
            reasons.append('relative_volume')
        else:
            reject_reasons.append('relative_volume_below_minimum')
        if catalyst is not None:
            reasons.append('catalyst')
        elif self.cfg.require_catalyst:
            reject_reasons.append('missing_required_catalyst')
            warnings.append('missing_required_catalyst')
        if pre_event_run_pct > self.cfg.max_pre_event_run_pct:
            reject_reasons.append('extended_before_event')
            warnings.append('extended_before_event')
        if base_range_pct > self.cfg.max_base_range_pct:
            reject_reasons.append('wide_prior_base')
            warnings.append('wide_prior_base')

        is_candidate = (
            event['close'] >= self.cfg.min_price
            and avg_dollar_volume >= self.cfg.min_avg_dollar_volume
            and gap_pct >= self.cfg.min_gap_pct
            and relative_volume >= self.cfg.min_relative_volume
            and (catalyst is not None or not self.cfg.require_catalyst)
            and pre_event_run_pct <= self.cfg.max_pre_event_run_pct
            and base_range_pct <= self.cfg.max_base_range_pct
        )

        score = self._score(
            gap_pct=gap_pct,
            relative_volume=relative_volume,
            avg_dollar_volume=avg_dollar_volume,
            catalyst=catalyst,
            pre_event_run_pct=pre_event_run_pct,
            base_range_pct=base_range_pct,
            close_position=close_position,
        )

        return EpisodicPivotSignal(
            ticker=ticker,
            trade_date=event.get('trade_date', event.name),
            is_candidate=is_candidate,
            score=score,
            reasons=tuple(reasons),
            reject_reasons=tuple(reject_reasons),
            warnings=tuple(warnings),
            catalyst=catalyst,
            previous_close=previous_close,
            open=float(event['open']),
            high=float(event['high']),
            low=float(event['low']),
            close=float(event['close']),
            volume=float(event['volume']),
            avg_volume=avg_volume,
            avg_dollar_volume=avg_dollar_volume,
            gap_pct=gap_pct,
            day_gain_pct=day_gain_pct,
            relative_volume=relative_volume,
            adr_pct=adr_pct,
            pre_event_run_pct=pre_event_run_pct,
            base_range_pct=base_range_pct,
            close_position=close_position,
        )

    def scan_daily_bars(
        self,
        ticker_bars: Mapping[str, DataFrame],
        catalysts: Optional[Mapping[str, EpisodicPivotCatalyst]] = None,
        candidates_only: bool = True,
    ) -> DataFrame:
        signals = []
        catalysts = catalysts or {}
        for ticker, bars in ticker_bars.items():
            signal = self.analyze_daily_bars(
                bars,
                ticker=ticker,
                catalyst=catalysts.get(ticker),
            )
            if signal is None:
                continue
            if candidates_only and not signal.is_candidate:
                continue
            signals.append(signal.to_dict())
        if not signals:
            return DataFrame()
        return DataFrame(signals).sort_values(
            ['score', 'relative_volume', 'gap_pct'],
            ascending=[False, False, False],
            ignore_index=True,
        )

    def read_daily_bars_from_mongo(
        self,
        ticker: str,
        lookback: int = 252,
        end_date: Optional[datetime] = None,
        interval: str = '1d',
    ) -> DataFrame:
        if not ticker:
            raise ValueError('ticker is required')
        if lookback <= 0:
            raise ValueError('lookback must be positive')

        make_db_connection()
        query: dict[str, Any] = {
            'ticker': ticker.upper(),
            'interval': interval,
        }
        if end_date is not None:
            query['trade_date__lte'] = end_date

        docs = TickerDailyInfo.objects(**query).order_by('-trade_date').limit(lookback)
        bars = mongo_2_df(docs)
        if bars.empty:
            return bars
        return bars.sort_values('trade_date', kind='stable').reset_index(drop=True)

    def scan_mongo_daily_bars(
        self,
        tickers: list[str] | tuple[str, ...],
        lookback: int = 252,
        end_date: Optional[datetime] = None,
        interval: str = '1d',
        catalysts: Optional[Mapping[str, EpisodicPivotCatalyst]] = None,
        candidates_only: bool = True,
    ) -> DataFrame:
        normalized_catalysts = {
            ticker.upper(): catalyst for ticker, catalyst in (catalysts or {}).items()
        }
        ticker_bars: dict[str, DataFrame] = {}
        for ticker in tickers:
            normalized_ticker = ticker.upper()
            bars = self.read_daily_bars_from_mongo(
                normalized_ticker,
                lookback=lookback,
                end_date=end_date,
                interval=interval,
            )
            if not bars.empty:
                ticker_bars[normalized_ticker] = bars
        return self.scan_daily_bars(
            ticker_bars,
            catalysts=normalized_catalysts,
            candidates_only=candidates_only,
        )

    def build_opening_range_plan(
        self,
        signal: EpisodicPivotSignal,
        intraday_bars: DataFrame,
        opening_range_minutes: Optional[int] = None,
    ) -> OpeningRangeTradePlan:
        if signal is None:
            raise ValueError('signal is required')

        minutes = opening_range_minutes or self.cfg.opening_range_minutes
        bars = self._normalize_intraday(intraday_bars)
        opening_range = self._opening_range_slice(bars, minutes)
        if opening_range.empty:
            raise ValueError('intraday_bars does not contain an opening range')

        opening_range_high = float(opening_range['high'].max())
        opening_range_low = float(opening_range['low'].min())
        entry = opening_range_high * (1 + self.cfg.entry_buffer_pct)
        stop = opening_range_low
        risk_pct = float((entry - stop) / entry) if entry > 0 else np.nan
        risk_adr_multiple = (
            float(risk_pct / signal.adr_pct)
            if signal.adr_pct and signal.adr_pct > 0 and not pd.isna(signal.adr_pct)
            else np.nan
        )

        reject_reasons: list[str] = []
        warnings: list[str] = []
        if not signal.is_candidate:
            reject_reasons.append('signal_not_candidate')
        if entry <= stop:
            reject_reasons.append('invalid_opening_range_risk')
        if risk_adr_multiple > self.cfg.max_stop_adr_multiple:
            reject_reasons.append('risk_exceeds_adr_limit')
            warnings.append('wide_opening_range')

        return OpeningRangeTradePlan(
            ticker=signal.ticker,
            trade_date=signal.trade_date,
            is_tradeable=len(reject_reasons) == 0,
            entry=round(entry, 4),
            stop=round(stop, 4),
            risk_pct=round(risk_pct, 6),
            risk_adr_multiple=round(risk_adr_multiple, 4),
            opening_range_high=round(opening_range_high, 4),
            opening_range_low=round(opening_range_low, 4),
            opening_range_minutes=minutes,
            reject_reasons=tuple(reject_reasons),
            warnings=tuple(warnings),
        )

    def _score(
        self,
        gap_pct: float,
        relative_volume: float,
        avg_dollar_volume: float,
        catalyst: Optional[EpisodicPivotCatalyst],
        pre_event_run_pct: float,
        base_range_pct: float,
        close_position: float,
    ) -> float:
        gap_score = self._clip01((gap_pct - self.cfg.min_gap_pct) / 0.15) * 20
        volume_score = self._clip01(relative_volume / 10.0) * 20
        liquidity_score = self._clip01(avg_dollar_volume / (self.cfg.min_avg_dollar_volume * 5)) * 10
        catalyst_score = (catalyst.quality_score() if catalyst else 0.0) * 25
        neglect_score = (
            (1 - self._clip01(pre_event_run_pct / max(self.cfg.max_pre_event_run_pct, 0.01))) * 7.5
            + (1 - self._clip01(base_range_pct / max(self.cfg.max_base_range_pct, 0.01))) * 7.5
        )
        close_score = self._clip01(close_position) * 10
        return round(gap_score + volume_score + liquidity_score + catalyst_score + neglect_score + close_score, 2)

    @staticmethod
    def _clip01(value: float) -> float:
        if pd.isna(value):
            return 0.0
        return float(min(max(value, 0.0), 1.0))

    @classmethod
    def _normalize_ohlcv(cls, bars: DataFrame) -> DataFrame:
        if bars is None or bars.empty:
            raise ValueError('bars must be a non-empty OHLCV dataframe')
        normalized = bars.copy()
        normalized.columns = [str(col).strip().lower() for col in normalized.columns]
        missing = [col for col in cls.REQUIRED_DAILY_COLUMNS if col not in normalized.columns]
        if missing:
            raise ValueError(f'bars missing required columns: {missing}')
        return normalized.sort_values(
            'trade_date' if 'trade_date' in normalized.columns else normalized.index.name,
            kind='stable',
        ) if 'trade_date' in normalized.columns else normalized

    @classmethod
    def _normalize_intraday(cls, bars: DataFrame) -> DataFrame:
        if bars is None or bars.empty:
            raise ValueError('intraday_bars must be a non-empty OHLCV dataframe')
        normalized = bars.copy()
        normalized.columns = [str(col).strip().lower() for col in normalized.columns]
        missing = [col for col in cls.REQUIRED_INTRADAY_COLUMNS if col not in normalized.columns]
        if missing:
            raise ValueError(f'intraday_bars missing required columns: {missing}')
        if 'timestamp' in normalized.columns:
            normalized = normalized.sort_values('timestamp', kind='stable')
        return normalized

    @staticmethod
    def _opening_range_slice(bars: DataFrame, minutes: int) -> DataFrame:
        if 'timestamp' not in bars.columns:
            return bars.head(minutes)
        timestamps = pd.to_datetime(bars['timestamp'])
        start = timestamps.iloc[0]
        cutoff = start + pd.Timedelta(minutes=minutes)
        opening_range = bars.loc[timestamps < cutoff]
        return opening_range if not opening_range.empty else bars.head(minutes)
