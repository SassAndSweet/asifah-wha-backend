"""
Telegram Signal Source for Asifah Analytics -- Western Hemisphere Backend
v1.1.0 -- May 8, 2026

Bridges Telethon (async) with Flask (sync) to pull messages
from monitored Telegram channels across WHA theatres.

THEATRE COVERAGE (v1.1.0):
- Cuba:       regime, dissident, US sanctions, RU/CN/IR axis, maritime/migration
- Mexico:     cartels, border, USMCA, lithium/oil
- Venezuela:  regime, opposition, US sanctions, oil
- Chile:      copper, lithium, mining, regional politics  [NEW]
- Peru:       copper, mining, political instability       [NEW]
- Brazil:     iron ore, soybeans, BRICS, regional balance [NEW]

Future theatres (placeholders ready, channels TBD):
- Haiti, Colombia, Panama

────────────────────────────────────────────────────────────────────────
v1.1.0 CHANGES (May 8, 2026)
────────────────────────────────────────────────────────────────────────
  • Added Chile and Peru channel groups (copper convergence pathway)
  • Added Mexico, Venezuela, Brazil channel groups (architecture parity
    -- previously had placeholders only)
  • Added commodity-specialist channels (cross-target)
  • Restructured to use shared CROSS_THEATER list for multi-target signals
  • Added per-theatre fetch functions (mirroring Cuba pattern)

Usage:
    from telegram_signals_wha import (
        fetch_telegram_signals_cuba,
        fetch_telegram_signals_mexico,
        fetch_telegram_signals_venezuela,
        fetch_telegram_signals_chile,
        fetch_telegram_signals_peru,
        fetch_telegram_signals_brazil,
    )
    messages = fetch_telegram_signals_cuba(hours_back=24)

Returns articles in the same shape as RSS / GDELT / Bluesky output:
    {
      'title': str,        # first 500 chars of message
      'body':  str,        # full message
      'url':   str,        # https://t.me/{channel}/{msg_id}
      'published': str,    # ISO 8601 UTC
      'source':    str,    # 'Telegram @{channel}'
      'feed_type': 'telegram',
      'language':  'en'/'es'/'pt',
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
    print("[Telegram WHA] ⚠️ telethon not installed -- Telegram signals disabled")


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
# HONEST CONTEXT (preserved from v1.0):
# Cuba's Telegram footprint is sparser than Iran/Yemen/Russia because the
# regime restricts mobile data and most Cuban dissident reporting flows
# through web outlets (CubaNet, 14ymedio) which we already capture via RSS.
# The biggest Telegram value-add for WHA is:
#
#   1. Cross-theater RU / IR / CN channels mentioning WHA countries
#   2. US sanctions/Treasury channels (OFAC SDN designations)
#   3. Regional military / SOUTHCOM
#   4. Spanish-language regional aggregators
#   5. Commodity-specialist channels (NEW v1.1.0)
#
# Many handles are unverified -- Telethon will silently skip channels
# that don't exist or aren't accessible. Channels that fail consistently
# across scans should be commented out with a note (do NOT delete --
# keeps the audit trail of what we tried).
#
# STATUS COMMENT GLOSSARY:
#   [CONFIRMED]    Verified responsive in production
#   [UNVERIFIED]   Returned errors in past scans -- kept for audit trail
#   [SPECULATIVE]  Never confirmed; included on architectural completeness
#                  grounds. Re-verify on first deploy.
#   [NEW]          Added v1.1.0 -- not yet production-tested
#
# ========================================

# ── Cross-theater channels (mentioned across multiple WHA targets) ──
# These are *added on top of* per-theatre lists in fetch functions.
CROSS_THEATER_GLOBAL = [
    # ── Multi-theater axis: Russia / Iran / China saying things about WHA ──
    'IntelSlava',           # Intel Slava -- multilingual OSINT, frequently covers RU-Cuba/Venezuela
    'tasnimnews_en',        # Tasnim News English -- IRGC-affiliated, catches Iran-WHA MOUs
    'PressTV',              # Press TV -- Iranian state, anti-imperialist framing on WHA
    'FarsNewsAgency',       # Fars News English -- IRGC-affiliated
    'ManarNewsEN',          # Al-Manar -- anti-imperialist axis, frequent WHA framing

    # ── US government / sanctions / military posture ──
    'CentcomOfficial',      # CENTCOM -- broader regional ops (occasional Caribbean ref)
    'OSINTdefender',        # OSINT Defender -- multi-theater incident tracking
    'WarMonitors',          # War Monitor -- global incidents
    'ClashReport',          # Clash Report -- global incidents, sometimes WHA
]

# ── Commodity-specialist channels (NEW v1.1.0) ──
# Cross-target -- relevant whenever commodity convergence alerts fire.
# Most are speculative; pruning happens after first deploy.
COMMODITY_SPECIALIST = [
    'mining_news',          # Mining news aggregator [SPECULATIVE NEW]
    'oilprice_com',         # OilPrice.com -- daily oil/gas reporting [SPECULATIVE NEW]
    'argusmedia',           # Argus Media -- commodity prices [SPECULATIVE NEW]
    'shippingwatch',        # Shipping Watch -- maritime/tanker/freight [SPECULATIVE NEW]
    'reutersbusiness',      # Reuters Business / Markets [SPECULATIVE NEW]
]

# ========================================
# CUBA -- v1.0 starter set (refined v1.1.0)
# ========================================
CUBA_CHANNELS = [
    # Cuba-specific only -- cross-theater added by fetch function
    # ── Regional / Caribbean / Spanish aggregators ──
    'CubaInternaCom',       # Independent Cuba journalism [UNVERIFIED]
    'DiariodeCubaCanal',    # Diario de Cuba official channel [UNVERIFIED]
    'ADNCubaNoticias',      # ADN Cuba [UNVERIFIED]
    'cubanetnoticias',      # CubaNet [UNVERIFIED]

    # ── Maritime / port traffic (oil tanker arrivals critical for Cuba) ──
    # Most maritime signal currently captured via Bluesky + RSS.
]

# ========================================
# MEXICO (NEW v1.1.0)
# ========================================
# Cartel kinetic ops + USMCA + migration + lithium/oil/silver dependency.
# Mexican government has mixed Telegram presence. Cartel channels exist
# but won't be added (operational opsec issue + extremist content risk).
MEXICO_CHANNELS = [
    # ── Spanish-language regional news ──
    'milenio',              # Milenio Diario [SPECULATIVE NEW]
    'eluniversalmx',        # El Universal MX [SPECULATIVE NEW]
    'reformamx',            # Reforma [SPECULATIVE NEW]
    'aristeguinoticias',    # Aristegui Noticias [SPECULATIVE NEW]

    # ── Border / migration specialists ──
    'borderreport',         # Border Report -- US-MX border [SPECULATIVE NEW]

    # ── Mexico government (limited TG presence) ──
    'GobiernoMx',           # Mexican federal government [SPECULATIVE NEW]
]

# ========================================
# VENEZUELA (NEW v1.1.0)
# ========================================
# Venezuela has limited official TG presence; opposition uses TG more.
# Heavy oil signal -- PDVSA, sanctions, Russia/Iran/China oil deals.
VENEZUELA_CHANNELS = [
    # ── Spanish-language news ──
    'eluniversalvenezuela', # El Universal VE [SPECULATIVE NEW]
    'ntn24',                # NTN24 -- regional news [SPECULATIVE NEW]
    'efectococuyo',         # Efecto Cocuyo -- independent Venezuelan journalism [SPECULATIVE NEW]
    'caraotadigital',       # Caraota Digital [SPECULATIVE NEW]

    # ── Opposition / human rights ──
    'foroPenalCanal',       # Foro Penal -- political prisoner tracking [SPECULATIVE NEW]
]

# ========================================
# CHILE (NEW v1.1.0) -- Copper Convergence Anchor
# ========================================
# World's #1 copper producer (~24% global supply). Lithium Triangle.
# Strong Spanish-language press; Codelco strategic state asset.
# Critical for: WHA<->Asia commodity convergence (China is #1 copper buyer)
CHILE_CHANNELS = [
    # ── Mainstream Spanish press ──
    'latercerachile',       # La Tercera [SPECULATIVE NEW]
    'biobiochile',           # BioBioChile [SPECULATIVE NEW]
    'emol_chile',            # Emol [SPECULATIVE NEW]

    # ── Mining / commodity specialist ──
    'codelco_oficial',       # Codelco -- state copper company [SPECULATIVE NEW]
    'mineriachile',          # Chile Mining Ministry [SPECULATIVE NEW]

    # ── Regional / Andean ──
    'pulsoeconomicocl',      # Pulso -- Chilean economic news [SPECULATIVE NEW]
]

# ========================================
# PERU (NEW v1.1.0) -- Copper Convergence + Political Instability
# ========================================
# World's #2 copper producer (~10%). Las Bambas mine = critical site.
# Political volatility (multiple presidents in 5 years) creates regular
# kinetic risk to mining operations.
PERU_CHANNELS = [
    # ── Mainstream Spanish press ──
    'elcomerciope',          # El Comercio Peru [SPECULATIVE NEW]
    'rppnoticias',           # RPP Noticias [SPECULATIVE NEW]

    # ── Mining specialist ──
    'rumbominero',           # Rumbo Minero -- Peru mining trade press [SPECULATIVE NEW]
    'minemperu',             # Peru Energy & Mines Ministry [SPECULATIVE NEW]
]

# ========================================
# BRAZIL (NEW v1.1.0) -- BRICS + Iron Ore + Soybeans
# ========================================
# Largest WHA economy. Iron ore #1, soybeans #1, BRICS founding member.
# Significant Portuguese-language signal -- distinct from Spanish WHA.
BRAZIL_CHANNELS = [
    # ── Mainstream Portuguese press ──
    'g1globo',               # G1 Globo [SPECULATIVE NEW]
    'folha_uol',             # Folha de São Paulo [SPECULATIVE NEW]
    'estadao',               # Estadão [SPECULATIVE NEW]

    # ── BRICS / commodity ──
    'brasilbrics',           # Brazil BRICS specialist (handle uncertain) [SPECULATIVE NEW]
    'agronegociocom',        # Agronegócio -- soybeans/agribusiness [SPECULATIVE NEW]
    'valeoficial',           # Vale -- iron ore producer [SPECULATIVE NEW]
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


def _detect_language(body):
    """Heuristic language detection (cheap -- looking at first 200 chars)."""
    sample = body[:200].lower()
    spanish_markers = ['cuba', 'el ', 'la ', ' de ', ' en ', 'régimen', 'apagón',
                       'cubano', 'venezolano', 'mexicano', 'cobre', 'minería', 'petróleo']
    portuguese_markers = ['é ', 'são ', 'não ', 'cobre', 'mineração', 'petróleo brasileiro',
                          'governo', 'ministério', 'região']
    es_count = sum(1 for m in spanish_markers if m in sample)
    pt_count = sum(1 for m in portuguese_markers if m in sample)
    if pt_count >= 3 and pt_count > es_count:
        return 'pt'
    if es_count >= 3:
        return 'es'
    return 'en'


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
            print(f"[Telegram WHA/{theatre_label}] ❌ Session not authorized -- re-auth required")
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
                        lang = _detect_language(body)

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
                # Log + continue. This is normal -- see comments at file top.
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
        # We're inside an event loop -- run via thread pool
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _async_fetch_messages(channels, hours_back, theatre_label)
            )
            return future.result(timeout=120)
    except RuntimeError:
        # No event loop running -- create one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                _async_fetch_messages(channels, hours_back, theatre_label)
            )
        finally:
            loop.close()


def _build_channel_list(theatre_specific):
    """Combine theatre-specific channels with cross-theater + commodity specialists."""
    return theatre_specific + CROSS_THEATER_GLOBAL + COMMODITY_SPECIALIST


# ========================================
# PUBLIC FETCH FUNCTIONS -- per theatre
# ========================================

def fetch_telegram_signals_cuba(hours_back=24):
    """Cuba theatre fetch -- regime, dissidents, US posture, RU/CN/IR axis, maritime."""
    if not _telegram_available():
        return []
    try:
        channels = _build_channel_list(CUBA_CHANNELS)
        return _run_async(channels, hours_back, 'cuba')
    except Exception as e:
        print(f"[Telegram WHA/cuba] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_mexico(hours_back=24):
    """Mexico theatre fetch -- cartels, USMCA, border, lithium/oil."""
    if not _telegram_available():
        return []
    try:
        channels = _build_channel_list(MEXICO_CHANNELS)
        return _run_async(channels, hours_back, 'mexico')
    except Exception as e:
        print(f"[Telegram WHA/mexico] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_venezuela(hours_back=24):
    """Venezuela theatre fetch -- regime, opposition, oil, US sanctions."""
    if not _telegram_available():
        return []
    try:
        channels = _build_channel_list(VENEZUELA_CHANNELS)
        return _run_async(channels, hours_back, 'venezuela')
    except Exception as e:
        print(f"[Telegram WHA/venezuela] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_chile(hours_back=24):
    """Chile theatre fetch -- copper, lithium, mining, regional politics. (NEW v1.1.0)"""
    if not _telegram_available():
        return []
    try:
        channels = _build_channel_list(CHILE_CHANNELS)
        return _run_async(channels, hours_back, 'chile')
    except Exception as e:
        print(f"[Telegram WHA/chile] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_peru(hours_back=24):
    """Peru theatre fetch -- copper, mining, political instability. (NEW v1.1.0)"""
    if not _telegram_available():
        return []
    try:
        channels = _build_channel_list(PERU_CHANNELS)
        return _run_async(channels, hours_back, 'peru')
    except Exception as e:
        print(f"[Telegram WHA/peru] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_telegram_signals_brazil(hours_back=24):
    """Brazil theatre fetch -- iron ore, soybeans, BRICS. (NEW v1.1.0)"""
    if not _telegram_available():
        return []
    try:
        channels = _build_channel_list(BRAZIL_CHANNELS)
        return _run_async(channels, hours_back, 'brazil')
    except Exception as e:
        print(f"[Telegram WHA/brazil] ❌ fetch error: {str(e)[:200]}")
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
        'channels_cuba':       CUBA_CHANNELS,
        'channels_mexico':     MEXICO_CHANNELS,
        'channels_venezuela':  VENEZUELA_CHANNELS,
        'channels_chile':      CHILE_CHANNELS,
        'channels_peru':       PERU_CHANNELS,
        'channels_brazil':     BRAZIL_CHANNELS,
        'cross_theater_count': len(CROSS_THEATER_GLOBAL),
        'commodity_count':     len(COMMODITY_SPECIALIST),
        'ready': _telegram_available() and (
            os.path.exists(f'{SESSION_NAME}.session') or bool(
                os.environ.get('TELEGRAM_SESSION_BASE64_WHA') or
                os.environ.get('TELEGRAM_SESSION_BASE64')
            )
        ),
    }
