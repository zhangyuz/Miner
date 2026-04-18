"""
Format wedge-pop analysis payloads for Discord and send via Detonator notifier.

`result` should match the Mongo-backed aggregate from `WedgePopAnalyzer._get_result_from_mongo`
(including `analysis[]` rows with optional `extra_fields` merged).

Recipients and enable flag come from env (see Deploy/.env.example).

Notifications are sent from `WedgePopAnalyzer.analyze_today` after a successful Gemini run and
Mongo persist (not from `get_analysis`, which only reads the DB).

Formatting: Discord-style headings (`##` / `###`), blockquoted market posture (length-capped),
tighter truncations on long fields, and light emoji labels for scanability.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping

from detonator import DEFAULT_DISCORD_API_BASE, get_logger, send_discord_bot_messages

_logger = get_logger('OliverKellDiscord')

# Discord inline `code` is fragile if the payload contains backticks; strip them.
_INLINE_SOFT_MAX = 120
_LONG_TRUNC = 400
_REASONING_LINE_MAX = 280
_REPR_TRUNC = 700
_POSTURE_BLOCKQUOTE_MAX = 320

# Section hierarchy: ## / ### render in most Discord clients; use sparingly.
_DISPLAY_KEYS: tuple[tuple[str, str], ...] = (
    ('trend_template', '📈 Trend'),
    ('relative_strength', '💪 RS'),
    ('base_pattern', '🧱 Base'),
    ('volume_signal', '📊 Volume'),
    ('fundamental_signal', '📰 Fundamentals'),
    ('entry', '🎯 Entry'),
    ('stop', '🛑 Stop'),
    ('target', '🎪 Target'),
)

_CORE_KEYS = frozenset({
    'ticker', 'score', 'verdict', 'trend_template', 'relative_strength',
    'base_pattern', 'volume_signal', 'fundamental_signal', 'entry', 'stop', 'target', 'reasoning',
})


def _score_for_sort(item: Mapping[str, Any]) -> float:
    """Higher first; missing or non-numeric scores sort last."""
    sc = item.get('score')
    if sc is None:
        return float('-inf')
    try:
        return float(sc)
    except (TypeError, ValueError):
        return float('-inf')


def _truthy(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


def _split_ids(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.replace(';', ',').split(',') if x.strip()]


def _strip_backticks(s: str) -> str:
    return s.replace('`', "'")


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    if max_len < 2:
        return s[:max_len]
    return s[: max_len - 1] + '…'


def _md_repr_truncated(value: Any, max_len: int = _REPR_TRUNC) -> str:
    text = repr(value) if isinstance(value, (dict, list)) else str(value)
    return _strip_backticks(_truncate(text, max_len))


def _md_inline(value: Any) -> str:
    """Single-line short values in backticks; long or multiline as plain truncated text."""
    s = '' if value is None else str(value).strip()
    if not s:
        return ''
    s = _strip_backticks(s)
    if '\n' in s or len(s) > _INLINE_SOFT_MAX:
        return _truncate(s.replace('\n', ' '), _LONG_TRUNC)
    return f'`{s}`'


def _format_reasoning_md(reasoning: Any) -> List[str]:
    lines: List[str] = []
    if not reasoning:
        return lines
    if isinstance(reasoning, list):
        for r in reasoning:
            if r is None:
                continue
            for line in str(r).split('\n'):
                line = _strip_backticks(line.strip())
                if line:
                    line = _truncate(line, _REASONING_LINE_MAX)
                    lines.append(f'  • {line}')
    else:
        for line in str(reasoning).split('\n'):
            line = _strip_backticks(line.strip())
            if line:
                line = _truncate(line, _REASONING_LINE_MAX)
                lines.append(f'  • {line}')
    return lines


def _blockquote_posture(text: str, max_len: int = _POSTURE_BLOCKQUOTE_MAX) -> List[str]:
    """Single blockquote paragraph; truncates for channel density."""
    t = _strip_backticks(text.strip())
    if not t:
        return []
    t = _truncate(t.replace('\n', ' '), max_len)
    return [f'> 📝 {t}']


def _format_one_ticker_md(item: Mapping[str, Any]) -> str:
    lines: List[str] = []
    t = _strip_backticks(str(item.get('ticker') or '?'))
    sc = item.get('score')
    ver = _strip_backticks(str(item.get('verdict') or ''))
    head = f'### 📌 **`{t}`**'
    if sc is not None:
        head += f' · {_md_inline(sc)} pts'
    if ver:
        head += f' · **{ver}**'
    lines.append(head)
    lines.append('')
    for json_key, label in _DISPLAY_KEYS:
        v = item.get(json_key)
        if v is None or v == '':
            continue
        if isinstance(v, (dict, list)):
            lines.append(f'- **{label}** `{_md_repr_truncated(v)}`')
        else:
            lines.append(f'- **{label}** {_md_inline(v)}')
    rs = _format_reasoning_md(item.get('reasoning'))
    if rs:
        lines.append('')
        lines.append('**💬 Reasoning**')
        lines.extend(rs)
    extra_keys = sorted(k for k in item.keys() if k not in _CORE_KEYS)
    for k in extra_keys:
        v = item.get(k)
        if v is None or v == '':
            continue
        ks = _strip_backticks(str(k))
        if isinstance(v, (dict, list)):
            lines.append(f'- **🏷️ `{ks}`** `{_md_repr_truncated(v)}`')
        else:
            lines.append(f'- **🏷️ `{ks}`** {_md_inline(v)}')
    return '\n'.join(lines)


def format_oliver_kell_discord_message(result: Dict[str, Any]) -> str:
    """
    Build a Discord markdown message from the same dict shape stored/read from MongoDB
    (`trade_day`, `summary`, `analysis`; `methodology` / `source` are not shown).
    Per-ticker sections are ordered by score descending (highest first; missing scores last).
    """
    blocks: List[str] = []
    td = _strip_backticks(str(result.get('trade_day', '') or ''))
    blocks.append(f'## 📊 Wedge-Pop Analysis · `{td}`')
    blocks.append('')

    summary = result.get('summary') if isinstance(result.get('summary'), dict) else {}
    blocks.append('### 📋 Summary')
    mp = summary.get('market_posture', '')
    if mp:
        blocks.extend(_blockquote_posture(str(mp)))
        blocks.append('')
    tp = summary.get('top_picks') or []
    if tp:
        picks = ', '.join(f'`{_strip_backticks(str(x))}`' for x in tp[:25])
        blocks.append(f'- ⭐ **Top picks** {picks}')
    av = summary.get('avoid') or []
    if av:
        avoid = ', '.join(f'`{_strip_backticks(str(x))}`' for x in av[:25])
        blocks.append(f'- ⚠️ **Avoid / watch** {avoid}')

    raw_analyses = result.get('analysis') if isinstance(result.get('analysis'), list) else []
    analysis_dicts = [x for x in raw_analyses if isinstance(x, dict)]
    sorted_analyses = sorted(analysis_dicts, key=_score_for_sort, reverse=True)
    tickers_sorted = [_strip_backticks(str(x.get('ticker') or '?')) for x in sorted_analyses]
    if tickers_sorted:
        blocks.append(
            f"- 🧾 **Tickers ({len(tickers_sorted)})** "
            f"{', '.join(f'`{t}`' for t in tickers_sorted[:40])}",
        )
    else:
        tickers_fallback = result.get('tickers')
        if isinstance(tickers_fallback, list) and tickers_fallback:
            blocks.append(
                f"- 🧾 **Tickers ({len(tickers_fallback)})** "
                f"{', '.join(f'`{_strip_backticks(str(x))}`' for x in tickers_fallback[:40])}",
            )

    n = len(sorted_analyses)
    if not sorted_analyses:
        return '\n'.join(blocks)

    blocks.append('')
    blocks.append(f'### 📈 By ticker ({n}) · score high → low')
    for raw in sorted_analyses[:40]:
        blocks.append('')
        blocks.append(_format_one_ticker_md(raw))
    if n > 40:
        blocks.append('')
        blocks.append('*…📎 {0} more tickers (lowest scores omitted; full list in Mongo / API).*'.format(n - 40))

    return '\n'.join(blocks)


def notify_oliver_kell_analysis_if_configured(result: Dict[str, Any]) -> None:
    """
    If env enables Oliver Kell Discord notifications and token + recipients exist,
    send formatted content. Logs errors; never raises.

    Intended caller: `WedgePopAnalyzer.analyze_today` after Mongo persist. Callers that only
    read Mongo (e.g. `get_analysis`) do not invoke this unless wired explicitly.
    """
    if not _truthy(os.environ.get('DISCORD_OLIVER_KELL_ENABLED')):
        return
    token = (os.environ.get('DISCORD_BOT_TOKEN') or '').strip()
    if not token:
        _logger.warning('DISCORD_OLIVER_KELL_ENABLED set but DISCORD_BOT_TOKEN is empty')
        return
    channels = _split_ids(os.environ.get('DISCORD_OLIVER_KELL_CHANNEL_IDS'))
    users = _split_ids(os.environ.get('DISCORD_OLIVER_KELL_USER_IDS'))
    if not channels and not users:
        _logger.warning(
            'Oliver Kell Discord enabled but DISCORD_OLIVER_KELL_CHANNEL_IDS and '
            'DISCORD_OLIVER_KELL_USER_IDS are both empty',
        )
        return
    api_base = (os.environ.get('DISCORD_API_BASE') or '').strip() or DEFAULT_DISCORD_API_BASE
    text = format_oliver_kell_discord_message(result)
    try:
        send_result = send_discord_bot_messages(
            text,
            bot_token=token,
            channel_ids=channels,
            user_ids=users,
            api_base=api_base,
        )
        if not send_result.ok:
            _logger.error('Discord Oliver Kell notify completed with errors: %s', send_result.errors)
    except Exception as e:
        _logger.error('Discord Oliver Kell notify failed: %s', e, exc_info=True)
