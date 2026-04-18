"""
General-purpose Discord Bot REST notifier (HTTP API v10).

Send plain-text messages to guild channels and/or user DMs using a bot token.
Does not use the Gateway; safe for Celery and short-lived workers.

See https://discord.com/developers/docs/resources/channel#create-message
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

import requests

from ._log import get_logger

_logger = get_logger('Detonator.DiscordNotify')

DEFAULT_DISCORD_API_BASE = 'https://discord.com/api/v10'
DISCORD_CONTENT_MAX_LEN = 2000
_DEFAULT_TIMEOUT = 15.0
_MAX_429_RETRIES = 5


@dataclass
class DiscordSendResult:
    ok: bool
    errors: List[str] = field(default_factory=list)


def chunk_discord_content(text: str, max_len: int = DISCORD_CONTENT_MAX_LEN) -> List[str]:
    """Split text into chunks each at most max_len (Discord message content limit)."""
    if not text:
        return ['']
    if max_len < 1:
        raise ValueError('max_len must be >= 1')
    if len(text) <= max_len:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_len, len(text))
        piece = text[start:end]
        if end < len(text):
            nl = piece.rfind('\n')
            if nl > max_len // 4:
                piece = piece[: nl + 1]
                end = start + len(piece)
        chunks.append(piece.rstrip('\n') if piece.endswith('\n') and len(piece) > 1 else piece)
        if end <= start:
            end = start + 1
        start = end
    return chunks or ['']


def _auth_headers(bot_token: str) -> dict[str, str]:
    return {
        'Authorization': f'Bot {bot_token}',
        'Content-Type': 'application/json',
    }


def _post_message(
    api_base: str,
    bot_token: str,
    channel_id: str,
    content: str,
    timeout: float,
) -> Optional[str]:
    url = f'{api_base.rstrip("/")}/channels/{channel_id}/messages'
    for attempt in range(_MAX_429_RETRIES + 1):
        resp = requests.post(
            url,
            headers=_auth_headers(bot_token),
            json={'content': content},
            timeout=timeout,
        )
        if resp.status_code == 429 and attempt < _MAX_429_RETRIES:
            data: Any = {}
            try:
                data = resp.json()
            except json.JSONDecodeError:
                pass
            retry_after = data.get('retry_after') if isinstance(data, dict) else None
            if isinstance(retry_after, (int, float)):
                time.sleep(min(float(retry_after) + 0.1, 60.0))
            else:
                time.sleep(1.0)
            continue
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except json.JSONDecodeError:
                detail = resp.text[:500]
            return f'{channel_id}: HTTP {resp.status_code} {detail}'
        return None
    return f'{channel_id}: HTTP 429 rate limited after {_MAX_429_RETRIES} retries'


def _open_dm_channel(api_base: str, bot_token: str, user_id: str, timeout: float) -> tuple[Optional[str], Optional[str]]:
    url = f'{api_base.rstrip("/")}/users/@me/channels'
    resp = requests.post(
        url,
        headers=_auth_headers(bot_token),
        json={'recipient_id': user_id},
        timeout=timeout,
    )
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except json.JSONDecodeError:
            detail = resp.text[:500]
        return None, f'dm_open {user_id}: HTTP {resp.status_code} {detail}'
    try:
        data = resp.json()
        cid = data.get('id')
        if cid:
            return str(cid), None
        return None, f'dm_open {user_id}: no channel id in response'
    except json.JSONDecodeError:
        return None, f'dm_open {user_id}: invalid JSON'


def send_discord_bot_messages(
    content: str,
    *,
    bot_token: str,
    channel_ids: Sequence[str] = (),
    user_ids: Sequence[str] = (),
    api_base: str = DEFAULT_DISCORD_API_BASE,
    timeout_seconds: float = _DEFAULT_TIMEOUT,
) -> DiscordSendResult:
    """
    Send the same message (chunked) to each channel and each user's DM.

    Never raises; returns DiscordSendResult with aggregated error strings.
    Opens each DM channel once per call, then posts all chunks.

    If some destinations fail and others succeed, ``ok`` is False but earlier chunks may
    already have been delivered to successful targets.
    """
    errors: List[str] = []
    if not bot_token or not bot_token.strip():
        return DiscordSendResult(ok=False, errors=['missing bot token'])
    chans = [c.strip() for c in channel_ids if c and str(c).strip()]
    users = [u.strip() for u in user_ids if u and str(u).strip()]
    if not chans and not users:
        return DiscordSendResult(ok=False, errors=['no channel_ids or user_ids'])

    chunks = chunk_discord_content(content)
    token = bot_token.strip()
    base = api_base.strip() or DEFAULT_DISCORD_API_BASE

    dm_targets: List[tuple[str, str]] = []
    for uid in users:
        dm_id, open_err = _open_dm_channel(base, token, uid, timeout_seconds)
        if open_err:
            errors.append(open_err)
            _logger.error('Discord DM open failed: %s', open_err)
            continue
        if dm_id:
            dm_targets.append((uid, dm_id))

    for chunk in chunks:
        for cid in chans:
            err = _post_message(base, token, cid, chunk, timeout_seconds)
            if err:
                errors.append(err)
                _logger.error('Discord channel send failed: %s', err)
        for _uid, dm_id in dm_targets:
            err = _post_message(base, token, dm_id, chunk, timeout_seconds)
            if err:
                errors.append(err)
                _logger.error('Discord DM send failed: %s', err)

    return DiscordSendResult(ok=len(errors) == 0, errors=errors)
