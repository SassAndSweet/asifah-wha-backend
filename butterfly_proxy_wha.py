"""
================================================================================
butterfly_proxy_wha.py — Asifah Analytics
================================================================================
BUTTERFLY PROXY (WHA Backend)

Mirrors jawboning_proxy_wha.py architecture. The WHA backend's trackers (US,
Cuba, Mexico, Venezuela, Peru, Chile, etc.) call this proxy to fetch their
butterfly signal bundle. Proxy:
  1. Checks WHA local Redis for cached bundle
  2. If fresh (< 1h), returns it immediately
  3. If stale or missing, HTTP-fetches from ME backend's /api/butterfly/read
  4. Caches the fresh bundle to WHA local Redis
  5. Returns the bundle

CACHE BEHAVIOR
--------------
- TTL = 1 hour (butterfly signals shift faster than commodity tiles)
- Stale-while-revalidate: NOT implemented in v1 (simple is better than clever)
- Cache miss = blocking HTTP fetch (~1-3s typical, 25s hard timeout)
- Fail-open: any error returns an empty bundle so consumer trackers don't crash

USAGE FROM A TRACKER
--------------------
    from butterfly_proxy_wha import read_butterfly_signals_via_proxy

    bundle = read_butterfly_signals_via_proxy(consumer_theater='us')
    upstream = bundle.get('upstream_fingerprints', {})
    deltas   = bundle.get('amplifier_actor_deltas', {})
    notes    = bundle.get('context_notes', [])
    stressors = bundle.get('upstream_stressors', [])

ENDPOINT REGISTRATION
---------------------
    GET /api/wha/butterfly/<consumer_theater>     — proxy passthrough
    GET /api/wha/butterfly-debug                  — diagnostic

v1.0.0 — May 16 2026
================================================================================
"""

import os
import json
import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

# ============================================================================
# CONFIGURATION
# ============================================================================

ME_BACKEND_URL = os.environ.get(
    'ME_BACKEND_URL',
    'https://asifah-backend.onrender.com'
)
CACHE_TTL_SECONDS = 1 * 3600   # 1 hour
FETCH_TIMEOUT_SECONDS = 25     # hard timeout for ME backend HTTP call

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')


# ============================================================================
# REDIS HELPERS (local WHA Redis — for caching the proxy response)
# ============================================================================

def _cache_key(consumer_theater):
    return f"butterfly:wha:{consumer_theater}:cached"


def _redis_load(consumer_theater):
    """Load cached butterfly bundle from WHA Redis. Returns None if missing or stale."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{_cache_key(consumer_theater)}",
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        if not resp.ok:
            return None
        data = resp.json()
        raw = data.get('result')
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        print(f"[Butterfly Proxy WHA] Redis load error: {e}")
        return None


def _redis_save(consumer_theater, bundle):
    """Save butterfly bundle to WHA Redis with TTL."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return
    try:
        payload = json.dumps(bundle, default=str)
        url = (f"{UPSTASH_REDIS_URL}/setex/{_cache_key(consumer_theater)}/"
               f"{CACHE_TTL_SECONDS}")
        requests.post(
            url,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            data=payload,
            timeout=5,
        )
    except Exception as e:
        print(f"[Butterfly Proxy WHA] Redis save error: {e}")


def _is_fresh(bundle):
    """Check if cached bundle is still within TTL."""
    if not isinstance(bundle, dict):
        return False
    cached_at = bundle.get('cached_at')
    if not cached_at:
        return False
    try:
        cached_ts = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - cached_ts).total_seconds()
        return age < CACHE_TTL_SECONDS
    except Exception:
        return False


# ============================================================================
# HTTP FETCH FROM ME BACKEND
# ============================================================================

def _fetch_from_me(consumer_theater):
    """Direct HTTP call to ME backend's butterfly reader endpoint."""
    url = f"{ME_BACKEND_URL}/api/butterfly/read/{consumer_theater}"
    try:
        resp = requests.get(url, timeout=FETCH_TIMEOUT_SECONDS)
        if not resp.ok:
            print(f"[Butterfly Proxy WHA] ME backend HTTP {resp.status_code} "
                  f"for {consumer_theater}")
            return None
        return resp.json()
    except requests.Timeout:
        print(f"[Butterfly Proxy WHA] Timeout calling ME backend "
              f"for {consumer_theater} (>{FETCH_TIMEOUT_SECONDS}s)")
        return None
    except Exception as e:
        print(f"[Butterfly Proxy WHA] ME backend error for {consumer_theater}: "
              f"{type(e).__name__}: {str(e)[:120]}")
        return None


def _empty_bundle(consumer_theater, error=None):
    """Fail-open: return empty 4-field bundle so consumers don't crash."""
    return {
        'upstream_fingerprints':  {},
        'amplifier_actor_deltas': {},
        'context_notes':          [],
        'upstream_stressors':     [],
        'consumer_theater':       consumer_theater,
        'success':                False,
        'error':                  error,
        'cached':                 False,
        'read_at':                datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# PUBLIC API
# ============================================================================

def read_butterfly_signals_via_proxy(consumer_theater, force=False):
    """
    Main entry. Cache-first; HTTP-fetch on miss.

    Args:
        consumer_theater: str — 'us', 'cuba', 'mexico', etc.
        force: bool — bypass cache, force fresh fetch from ME

    Returns:
        dict — butterfly bundle (success path) or empty bundle (fail-open path)
    """
    consumer_theater = (consumer_theater or '').lower().strip()
    if not consumer_theater:
        return _empty_bundle(consumer_theater, error='no consumer_theater provided')

    # Step 1: cache check (unless forced)
    if not force:
        cached = _redis_load(consumer_theater)
        if cached and _is_fresh(cached):
            cached['cached'] = True
            return cached

    # Step 2: bounded fetch from ME backend
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_fetch_from_me, consumer_theater)
        try:
            fresh = future.result(timeout=FETCH_TIMEOUT_SECONDS + 2)
        except FutureTimeout:
            print(f"[Butterfly Proxy WHA] ⏱️ Hard timeout fetching {consumer_theater}")
            fresh = None
    except Exception as e:
        print(f"[Butterfly Proxy WHA] Fetch executor error: {e}")
        fresh = None
    finally:
        executor.shutdown(wait=False)

    if not isinstance(fresh, dict) or not fresh.get('success'):
        # Fail-open: try stale cache, otherwise empty
        stale = _redis_load(consumer_theater)
        if isinstance(stale, dict):
            stale['cached'] = True
            stale['stale']  = True
            return stale
        return _empty_bundle(consumer_theater, error='ME backend unreachable or returned no data')

    # Step 3: cache and return
    fresh['cached_at'] = datetime.now(timezone.utc).isoformat()
    fresh['cached']    = False
    _redis_save(consumer_theater, fresh)
    return fresh


# ============================================================================
# FLASK ENDPOINT REGISTRATION
# ============================================================================

def register_butterfly_proxy(app):
    """Register butterfly proxy endpoints on the WHA backend Flask app."""
    from flask import jsonify, request

    @app.route('/api/wha/butterfly/<consumer_theater>', methods=['GET', 'OPTIONS'])
    def api_wha_butterfly(consumer_theater):
        if request.method == 'OPTIONS':
            return '', 200
        force = request.args.get('force', 'false').lower() == 'true'
        try:
            bundle = read_butterfly_signals_via_proxy(consumer_theater, force=force)
            return jsonify(bundle)
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify(_empty_bundle(consumer_theater, error=str(e)[:200])), 500

    @app.route('/api/wha/butterfly-debug', methods=['GET'])
    def api_wha_butterfly_debug():
        return jsonify({
            'success':           True,
            'me_backend_url':    ME_BACKEND_URL,
            'cache_ttl_hours':   CACHE_TTL_SECONDS / 3600,
            'fetch_timeout_s':   FETCH_TIMEOUT_SECONDS,
            'redis_configured':  bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'service':           'butterfly_proxy_wha',
            'version':           '1.0.0',
        })

    print("[Butterfly Proxy WHA] ✅ Endpoints registered:")
    print("  GET /api/wha/butterfly/<consumer_theater>")
    print("  GET /api/wha/butterfly-debug")
