"""
Telegram Signal Source for Asifah Analytics — Western Hemisphere Backend
v1.0.0 — April 25, 2026

Bridges Telethon (async) with Flask (sync) to pull messages
from monitored Telegram channels across WHA theatres.

INITIAL THEATRE COVERAGE:
- Cuba: regime, dissident, US sanctions, RU/CN/IR axis, maritime/migration

Future theatres (placeholders ready, channels TBD):
- Mexico
- Venezuela
- Haiti
- Colombia
- Brazil

Usage:
    from telegram_signals_wha import fetch_telegram_signals_cuba
    messages = fetch_telegram_signals_cuba(hours_back=24)

Returns articles in the same shape as RSS / GDELT / Bluesky output:
    {
      'title': str,        # first 500 chars of message
      'body':  str,        # full message
      'url':   str,        # https://t.me/{channel}/{msg_id}
      'published': str,    # ISO 8601 UTC
      'source':    str,    # 'Telegram @{channel}'
      'feed_type': 'telegram',
      'language':  'en'/'es',
      'views':     int,
      'forwards':  int,
    }
"""

import os
import asyncio
import base64
from datetime import datetime, timezone, timedelta

try:
    from telethon import TelegramClient
    from telethon.tl.functions.messages import GetHistoryRequest
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    print("[Telegram WHA] ⚠️ telethon not installed — Telegram signals disabled")


# ========================================
# CONFIGURATION
# ========================================
TELEGRAM_API_ID   = os.environ.get('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.environ.get('TELEGRAM_API_HASH')
TELEGRAM_PHONE    = os.environ.get('TELEGRAM_PHONE')
SESSION_NAME      = 'asifah_wha_session'


# ========================================
# CHANNEL GROUPS
# ========================================
#
# CUBA — v1.0 starter set.
#
# HONEST CONTEXT: Cuba's Telegram footprint is sparser than Iran/Yemen/Russia
# because the regime restricts mobile data and most Cuban dissident reporting
# flows through web outlets (CubaNet, 14ymedio) which we already capture via
# RSS. The biggest Telegram value-add for Cuba is:
#
#   1. Cross-theater RU / IR / CN channels mentioning Cuba (axis signals)
#   2. US sanctions/Treasury channels (OFAC SDN designations)
#   3. Regional military / SOUTHCOM
#   4. Spanish-language regional aggregators
#
# Many handles are unverified — Telethon will silently skip channels that
# don't exist or aren't accessible. Channels that fail consistently across
# scans should be commented out with a note (do NOT delete — keeps the
# audit trail of what we tried).
#
CUBA_CHANNELS = [
    # ── Cross-theater axis: Russia / Iran / China saying things about Cuba ──
    'IntelSlava',           # Intel Slava — multilingual OSINT, frequently covers RU-Cuba
    'tasnimnews_en',        # Tasnim News English — IRGC-affiliated, catches Iran-Cuba MOUs
    'PressTV',              # Press TV — Iranian state, Cuba solidarity statements
    'FarsNewsAgency',       # Fars News English — IRGC-affiliated
    'ManarNewsEN',          # Al-Manar — anti-imperialist axis, frequently anti-US-Cuba framing

    # ── US government / sanctions / military posture ──
    'CentcomOfficial',      # CENTCOM — broader regional ops (occasional Caribbean ref)
    'OSINTdefender',        # OSINT Defender — multi-theater incident tracking
    'WarMonitors',          # War Monitor — global incidents

    # ── Regional / Caribbean / Spanish aggregators (potential, may need verification) ──
    'ClashReport',          # Clash Report — global incidents, sometimes WHA
    # The following are aspirational — Telethon will skip if they don't resolve.
    # We track failures via the per-channel error log and prune later.
    'CubaInternaCom',       # Independent Cuba journalism (verification pending)
    'DiariodeCubaCanal',    # Diario de Cuba official channel (verification pending)
    'ADNCubaNoticias',      # ADN Cuba (verification pending)
    'cubanetnoticias',      # CubaNet (verification pending)

    # ── Maritime / port traffic (oil tanker arrivals critical for Cuba) ──
    # Note: we're already capturing tanker signals via Bluesky + RSS.
    # Adding TG channels that focus on Caribbean maritime would be ideal.
    # For v1.0, none confirmed.
]


# ========================================
# HELPERS
# ========================================

def _telegram_available():
    if not TELETHON_AVAILABLE:
        return False
    if not all([TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE]):
        print("[Telegram WHA] ⚠️ Missing env vars (TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE)")
        return False
    return True


def _ensure_session_file():
    """Decode the base64-encoded Telethon session from env if no .session file present."""
    session_path = f'{SESSION_NAME}.session'
    if os.path.exists(session_path):
        return True
    # Try WHA-specific env first, then fall back to shared (so a single session can serve both backends)
    session_b64 = (
        os.environ.get('TELEGRAM_SESSION_BASE64_WHA') or
        os.environ.get('TELEGRAM_SESSION_BASE64')
    )
    if session_b64:
        try:
            session_data = base64.b64decode(session_b64)
            with open(session_path, 'wb') as f:
                f.write(session_data)
            print(f"[Telegram WHA] ✅ Session file decoded ({len(session_data)} bytes)")
            return True
        except Exception as e:
            print(f"[Telegram WHA] ❌ Session decode error: {str(e)[:100]}")
            return False
    print("[Telegram WHA] ⚠️ No session file and no TELEGRAM_SESSION_BASE64 / _WHA env var")
    return False


async def _async_fetch_messages(channels, hours_back=24, theatre_label='wha'):
    """Pull recent messages from a list of Telegram channels."""
    if not _ensure_session_file():
        return []

    messages = []
    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    client = None
    try:
        client = TelegramClient(SESSION_NAME, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            print(f"[Telegram WHA/{theatre_label}] ❌ Session not authorized — re-auth required")
            await client.disconnect()
            return []

        # Deduplicate channel list (preserve order)
        seen = set()
        unique_channels = []
        for ch in channels:
            if ch not in seen:
                seen.add(ch)
                unique_channels.append(ch)

        print(f"[Telegram WHA/{theatre_label}] ✅ Connected, fetching from {len(unique_channels)} channels...")

        for channel in unique_channels:
            try:
                entity = await client.get_entity(channel)
                history = await client(GetHistoryRequest(
                    peer=entity,
                    limit=50,
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0
                ))

                channel_count = 0
                for msg in history.messages:
                    if msg.date and msg.date.replace(tzinfo=timezone.utc) > since and msg.message:
                        body = msg.message
                        # Heuristic language detection (cheap — looking at first 200 chars)
                        # Most of our keyword matching is lowercase substring anyway
                        sample = body[:200].lower()
                        spanish_markers = ['cuba', 'el ', 'la ', ' de ', ' en ', 'régimen', 'apagón', 'cubano']
                        is_spanish = sum(1 for m in spanish_markers if m in sample) >= 3
                        lang = 'es' if is_spanish else 'en'

                        messages.append({
                            'title':       body[:500],
                            'description': body,           # full message body for keyword classification
                            'body':        body,
                            'url':         f'https://t.me/{channel}/{msg.id}',
                            'published':   msg.date.replace(tzinfo=timezone.utc).isoformat(),
                            'publishedAt': msg.date.replace(tzinfo=timezone.utc).isoformat(),
                            'source':      {'name': f'Telegram @{channel}'},
                            'feed_type':   'telegram',
                            'language':    lang,
                            'views':       getattr(msg, 'views', 0) or 0,
                            'forwards':    getattr(msg, 'forwards', 0) or 0,
                            'source_weight_override': 0.85,  # Telegram is high-signal but unverified
                        })
                        channel_count += 1

                print(f"[Telegram WHA/{theatre_label}] @{channel}: {channel_count} messages (last {hours_back}h)")

            except Exception as e:
                # Common failures: channel doesn't exist, account was banned, no access.
                # Log + continue. This is normal — see comments in CUBA_CHANNELS.
                print(f"[Telegram WHA/{theatre_label}] @{channel} skipped: {str(e)[:100]}")
                continue

        await client.disconnect()
        print(f"[Telegram WHA/{theatre_label}] ✅ Total: {len(messages)} messages from {len(unique_channels)} channels")

    except Exception as e:
        print(f"[Telegram WHA/{theatre_label}] ❌ Connection error: {str(e)[:200]}")
        try:
            if client:
                await client.disconnect()
        except Exception:
            pass

    return messages


def _run_async(channels, hours_back, theatre_label):
    """Bridge async to sync; tolerate already-running event loops (Flask context)."""
    try:
        asyncio.get_running_loop()
        # We're inside an event loop — run via thread pool
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _async_fetch_messages(channels, hours_back, theatre_label)
            )
            return future.result(timeout=120)
    except RuntimeError:
        # No event loop running — create one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                _async_fetch_messages(channels, hours_back, theatre_label)
            )
        finally:
            loop.close()


# ========================================
# PUBLIC FETCH FUNCTIONS — per theatre
# ========================================

def fetch_telegram_signals_cuba(hours_back=24):
    """Cuba theatre fetch — regime, dissidents, US posture, RU/CN/IR axis, maritime."""
    if not _telegram_available():
        return []
    try:
        return _run_async(CUBA_CHANNELS.copy(), hours_back, 'cuba')
    except Exception as e:
        print(f"[Telegram WHA/cuba] ❌ fetch error: {str(e)[:200]}")
        return []


# ========================================
# HEALTH CHECK
# ========================================

def get_telegram_wha_status():
    return {
        'telethon_installed': TELETHON_AVAILABLE,
        'api_configured':     bool(TELEGRAM_API_ID and TELEGRAM_API_HASH),
        'phone_configured':   bool(TELEGRAM_PHONE),
        'session_available':  os.path.exists(f'{SESSION_NAME}.session') or bool(
            os.environ.get('TELEGRAM_SESSION_BASE64_WHA') or
            os.environ.get('TELEGRAM_SESSION_BASE64')
        ),
        'channels_cuba': CUBA_CHANNELS,
        'ready': _telegram_available() and (
            os.path.exists(f'{SESSION_NAME}.session') or bool(
                os.environ.get('TELEGRAM_SESSION_BASE64_WHA') or
                os.environ.get('TELEGRAM_SESSION_BASE64')
            )
        ),
    }
