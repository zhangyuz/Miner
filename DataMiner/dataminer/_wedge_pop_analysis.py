import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import pytz
from detonator import SingletonParent, get_logger, make_db_connection, mongo_2_df, run_gemini_prompt
from detonator import GeminiCLIConfig

from ._trade_cal import TradeCalendarShovel
from ._wedge_pop import WedgePop
from .models import TickerDailyInfo, WedgePopAiAnalysis

_logger = get_logger('WedgePopAnalyzer')

_NY_TZ = pytz.timezone('America/New_York')


class WedgePopAnalyzer(SingletonParent):
    """AI analysis for wedge-pop tickers; trade date matches WedgePop / US calendar."""

    def _trade_date_from_key(self, day_key: str) -> datetime:
        return datetime.strptime(day_key, '%Y%m%d')

    def _resolve_wedge_trade_day_key(self, day: Optional[Union[str, datetime]] = None) -> str:
        """
        Same calendar semantics as WedgePop.get_wedge_tickers_on: last closed US session
        on or before the reference day (XNYS).
        """
        cal = TradeCalendarShovel.get_instance()
        make_db_connection()
        if day is None:
            ref = datetime.now(tz=_NY_TZ)
        elif isinstance(day, str):
            ref = datetime.strptime(day, '%Y%m%d').replace(tzinfo=_NY_TZ)
        else:
            ref = day.astimezone(_NY_TZ) if day.tzinfo else day.replace(tzinfo=_NY_TZ)
        return cal.get_last_closed_trade_date_before(ref, country='us', exchange='XNYS')

    def _persist_analysis_records(self, day_key: str, result: Dict[str, Any]) -> None:
        analyses = result.get('analysis', [])
        if not analyses:
            return
        try:
            make_db_connection()
            trade_date = self._trade_date_from_key(day_key)
            summary = result.get('summary', {}) if isinstance(result.get('summary', {}), dict) else {}
            for item in analyses:
                if not isinstance(item, dict) or not item.get('ticker'):
                    continue
                ticker = str(item['ticker']).upper()
                known_keys = {
                    'ticker', 'score', 'verdict', 'trend_template', 'relative_strength',
                    'base_pattern', 'volume_signal', 'fundamental_signal',
                    'entry', 'stop', 'target', 'reasoning'
                }
                extra_fields = {k: v for k, v in item.items() if k not in known_keys}
                WedgePopAiAnalysis.objects(
                    ticker=ticker,
                    trade_date=trade_date,
                    methodology=result.get('methodology', 'oliver_kell'),
                ).update_one(
                    upsert=True,
                    set__score=item.get('score'),
                    set__verdict=item.get('verdict'),
                    set__trend_template=item.get('trend_template'),
                    set__relative_strength=item.get('relative_strength'),
                    set__base_pattern=item.get('base_pattern'),
                    set__volume_signal=item.get('volume_signal'),
                    set__fundamental_signal=item.get('fundamental_signal'),
                    set__entry=item.get('entry'),
                    set__stop=item.get('stop'),
                    set__target=item.get('target'),
                    set__reasoning=item.get('reasoning') if isinstance(item.get('reasoning'), list) else [],
                    set__market_posture=summary.get('market_posture'),
                    set__top_picks=summary.get('top_picks') if isinstance(summary.get('top_picks'), list) else [],
                    set__avoid=summary.get('avoid') if isinstance(summary.get('avoid'), list) else [],
                    set__extra_fields=extra_fields,
                )
        except Exception as e:
            _logger.error('Failed persisting wedge analysis records %s: %s', day_key, e, exc_info=True)

    def _get_result_from_mongo(self, day_key: str) -> Optional[Dict[str, Any]]:
        try:
            make_db_connection()
            trade_date = self._trade_date_from_key(day_key)
            docs = WedgePopAiAnalysis.objects(trade_date=trade_date).order_by('ticker')
            if docs.count() == 0:
                return None
            analyses: List[Dict[str, Any]] = []
            top_picks: List[str] = []
            avoid: List[str] = []
            market_posture = ''
            methodology = 'oliver_kell'
            for doc in docs:
                methodology = doc.methodology or methodology
                if not market_posture and doc.market_posture:
                    market_posture = doc.market_posture
                if not top_picks and doc.top_picks:
                    top_picks = list(doc.top_picks)
                if not avoid and doc.avoid:
                    avoid = list(doc.avoid)
                item = {
                    'ticker': doc.ticker,
                    'score': doc.score,
                    'verdict': doc.verdict,
                    'trend_template': doc.trend_template,
                    'relative_strength': doc.relative_strength,
                    'base_pattern': doc.base_pattern,
                    'volume_signal': doc.volume_signal,
                    'fundamental_signal': doc.fundamental_signal,
                    'entry': doc.entry,
                    'stop': doc.stop,
                    'target': doc.target,
                    'reasoning': doc.reasoning or [],
                }
                if doc.extra_fields:
                    item.update(doc.extra_fields)
                analyses.append(item)
            return {
                'success': True,
                'trade_day': day_key,
                'methodology': methodology,
                'tickers': [i['ticker'] for i in analyses],
                'analysis': analyses,
                'summary': {
                    'market_posture': market_posture,
                    'top_picks': top_picks,
                    'avoid': avoid,
                },
                'source': 'mongodb',
            }
        except Exception as e:
            _logger.error('Failed loading wedge analysis from mongo %s: %s', day_key, e)
            return None

    def _get_ticker_snapshots(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        make_db_connection()
        snapshots: Dict[str, Dict[str, Any]] = {}
        for ticker in tickers:
            docs = TickerDailyInfo.objects(
                ticker=ticker,
                interval='1d',
            ).order_by('-trade_date').limit(260)
            df = mongo_2_df(docs)
            if df.empty:
                snapshots[ticker] = {'ticker': ticker, 'error': 'no_data'}
                continue
            df = df.sort_values('trade_date')
            latest = df.iloc[-1]
            low_52w = float(df['low'].min()) if 'low' in df.columns else None
            high_52w = float(df['high'].max()) if 'high' in df.columns else None
            last_close = float(latest['close']) if 'close' in latest else None
            snapshots[ticker] = {
                'ticker': ticker,
                'trade_date': str(latest.get('trade_date')),
                'close': last_close,
                'volume': float(latest['volume']) if 'volume' in latest else None,
                'ema10': float(latest['ema10']) if 'ema10' in latest and latest['ema10'] is not None else None,
                'ema20': float(latest['ema20']) if 'ema20' in latest and latest['ema20'] is not None else None,
                'sma50': float(latest['sma50']) if 'sma50' in latest and latest['sma50'] is not None else None,
                'sma200': float(latest['sma200']) if 'sma200' in latest and latest['sma200'] is not None else None,
                'fiftyTwoWeekLow': low_52w,
                'fiftyTwoWeekHigh': high_52w,
                'revenueGrowth': float(latest['revenueGrowth']) if 'revenueGrowth' in latest and latest['revenueGrowth'] is not None else None,
                'earningsGrowth': float(latest['earningsGrowth']) if 'earningsGrowth' in latest and latest['earningsGrowth'] is not None else None,
                'fiftyTwoWeekChange': float(latest['fiftyTwoWeekChange']) if 'fiftyTwoWeekChange' in latest and latest['fiftyTwoWeekChange'] is not None else None,
            }
        return snapshots

    def _build_prompt(self, tickers: List[str], ticker_data: Dict[str, Dict[str, Any]], day_key: str) -> str:
        methodology = """
Use Oliver Kell-inspired growth breakout methodology:
1) Trend template: price above 50/150/200 moving averages where possible, and long-term trend positive.
2) Relative strength: prefer leaders outperforming market peers.
3) Base quality: tighter consolidation and constructive pullbacks are better.
4) Volume: breakout confirmation with above-average volume, and volume dry-up in base.
5) Fundamentals: prefer accelerating revenue/earnings where data exists.
6) Risk management: suggest entry zone, invalidation/stop, and first target.
"""
        payload = {
            'trade_day': day_key,
            'tickers': tickers,
            'ticker_data': ticker_data,
        }
        return (
            'You are an elite US growth stock analyst.\n'
            f'{methodology}\n'
            'Analyze ONLY the provided wedge-pop tickers and return STRICT JSON (no markdown, no prose outside JSON).\n'
            'Required JSON schema:\n'
            '{\n'
            '  "trade_day": "YYYYMMDD",\n'
            '  "methodology": "oliver_kell",\n'
            '  "summary": {"market_posture": "...", "top_picks": ["..."], "avoid": ["..."]},\n'
            '  "analysis": [\n'
            '    {\n'
            '      "ticker": "AAPL",\n'
            '      "score": 0,\n'
            '      "verdict": "buy_watch|watch|avoid",\n'
            '      "trend_template": "...",\n'
            '      "relative_strength": "...",\n'
            '      "base_pattern": "...",\n'
            '      "volume_signal": "...",\n'
            '      "fundamental_signal": "...",\n'
            '      "entry": "...",\n'
            '      "stop": "...",\n'
            '      "target": "...",\n'
            '      "reasoning": ["...", "..."]\n'
            '    }\n'
            '  ]\n'
            '}\n'
            f'Input data JSON:\n{json.dumps(payload, default=str)}'
        )

    def _parse_gemini_json(self, output: str) -> Dict[str, Any]:
        if not output:
            raise ValueError('Empty Gemini output')
        stripped = output.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
        match = re.search(r'```json\s*(.*?)```', stripped, flags=re.DOTALL)
        if match:
            return json.loads(match.group(1).strip())
        match = re.search(r'(\{.*\})', stripped, flags=re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise ValueError('Unable to parse Gemini JSON output')

    def get_analysis(self, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        day_key = self._resolve_wedge_trade_day_key(date)
        return self._get_result_from_mongo(day_key)

    def analyze_today(self) -> Dict[str, Any]:
        day_key = self._resolve_wedge_trade_day_key(None)
        if existing := self._get_result_from_mongo(day_key):
            return existing

        ref_dt = self._trade_date_from_key(day_key)
        wedge = WedgePop.get_instance()
        pop_tickers = sorted(wedge.get_wedge_tickers_on(ref_dt, status='pop'))
        if not pop_tickers:
            return {
                'success': True,
                'trade_day': day_key,
                'methodology': 'oliver_kell',
                'tickers': [],
                'analysis': [],
                'summary': {'market_posture': 'no_wedge_pops', 'top_picks': [], 'avoid': []},
                'source': 'no-op',
            }

        ticker_data = self._get_ticker_snapshots(pop_tickers)
        prompt = self._build_prompt(pop_tickers, ticker_data, day_key)
        model = os.environ.get('WEDGE_POP_ANALYSIS_MODEL')
        if model:
            result = run_gemini_prompt(prompt, config=GeminiCLIConfig(timeout_seconds=600, model=model))
        else:
            result = run_gemini_prompt(prompt, config=GeminiCLIConfig(timeout_seconds=600))

        if not result.success:
            return {
                'success': False,
                'trade_day': day_key,
                'methodology': 'oliver_kell',
                'tickers': pop_tickers,
                'analysis': [],
                'summary': {'market_posture': 'gemini_failed', 'top_picks': [], 'avoid': pop_tickers[:5]},
                'error': result.error,
                'raw_output': result.output,
                'source': 'gemini',
            }

        try:
            parsed = self._parse_gemini_json(result.output)
            output = {
                'success': True,
                'trade_day': day_key,
                'methodology': 'oliver_kell',
                'tickers': pop_tickers,
                **parsed,
                'source': 'gemini',
            }
        except Exception as e:
            _logger.error('Failed parsing Gemini output as JSON: %s', e)
            output = {
                'success': True,
                'trade_day': day_key,
                'methodology': 'oliver_kell',
                'tickers': pop_tickers,
                'analysis': [],
                'summary': {'market_posture': 'unstructured_output', 'top_picks': [], 'avoid': []},
                'raw_output': result.output,
                'source': 'gemini',
            }

        self._persist_analysis_records(day_key, output)
        return self._get_result_from_mongo(day_key) or output
