"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — WHA BACKEND COMMODITY PROXY
  v1.0.0 (May 9 2026)
═══════════════════════════════════════════════════════════════════════

Thin proxy layer that fetches commodity data from the ME backend (where
commodity_tracker.py lives), caches it in WHA's Upstash Redis with a
12-hour TTL, and exposes WHA-native endpoints for stability page +
rhetoric tracker consumption.

Pattern parity with commodity_proxy_europe.py and commodity_proxy_asia.py
— same three-layer cascade, same TTL, same write-through caching.

NEW IN v1.0.0 (relative to Europe/Asia proxy):
  Adds the cross-tracker fingerprint passthrough endpoints, mirroring
  the contract shipped May 9 2026 in commodity_tracker.py:

    /api/commodity-fingerprint/<country>             — all commodities
    /api/commodity-fingerprint/<country>/<commodity> — single pair

  These let WHA-side rhetoric trackers (Peru, future Chile/Cuba/etc.)
  read commodity supply-risk fingerprints over a fast in-region call
  instead of reaching across to ME for every scan.

ARCHITECTURE:
  Frontend (peru-stability.html, etc.)
    └─→ WHA backend /api/wha/commodity/<target>
          └─→ WHA Redis cache (12hr TTL)
                └─[on miss]─→ ME backend /api/commodity-pressure/<target>
                                └─→ WHA Redis (write-through)

  Rhetoric Tracker (rhetoric_tracker_peru.py)
    └─→ WHA backend /api/wha/commodity-fingerprint/<country>
          └─→ WHA Redis cache (1hr TTL — fingerprints update faster)
                └─[on miss]─→ ME backend /api/commodity-fingerprint/<country>
                                └─→ WHA Redis (write-through)

WHY 12 HOURS for commodity-pressure / 1 HOUR for fingerprints:
  - Country-level commodity exposure (production rank, role, weight) is
    structural — doesn't change daily, so 12h freshness is fine.
  - Fingerprints reflect live signal-driven supply pressure, which can
    change scan-to-scan (every 12h on the ME backend). Fingerprint cache
    at 1h means we pick up new pressure signals within an hour without
    hammering ME on every WHA scan.

TARGETS SUPPORTED:
  Whatever ME backend's COUNTRY_COMMODITY_EXPOSURE has registered.
  Phase 1 WHA active set: peru, cuba (mexico, chile, panama, brazil,
  argentina, usa coming as their stability/rhetoric pages ship).

ENDPOINTS REGISTERED:
  GET /api/wha/commodity/<target>                            — country pressure
  GET /api/wha/commodity/<target>?force=true                 — bypass cache
  GET /api/wha/commodity-fingerprint/<country>               — all fingerprints
  GET /api/wha/commodity-fingerprint/<country>/<commodity>   — single fingerprint
  GET /api/wha/commodity-debug                               — diagnostic

USAGE FROM app.py:
    from commodity_proxy_wha import register_wha_commodity_proxy
    register_wha_commodity_proxy(app)
"""

import os
import json
import time
import threading
import requests
from datetime import datetime, timezone
from flask import jsonify, request

# ────────────────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────────────────

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

# ME backend address — override via env var for staging
ME_BACKEND_URL = os.environ.get(
    'ME_BACKEND_URL',
    'https://asifah-backend.onrender.com'
)

# TTLs differ by data type — see module header for rationale
COMMODITY_PRESSURE_TTL_SECONDS  = 12 * 3600   # 12h — structural country data
FINGERPRINT_TTL_SECONDS         =  1 * 3600   # 1h  — live signal-driven

# ────────────────────────────────────────────────────────────
# REDIS KEY HELPERS
# ────────────────────────────────────────────────────────────

def _pressure_redis_key(target):
    return f"wha:commodity:{target.lower()}"

def _fingerprint_redis_key_country(country):
    return f"wha:commodity_fp:{country.lower()}"

def _fingerprint_redis_key_pair(country, commodity):
    return f"wha:commodity_fp:{country.lower()}:{commodity.lower()}"


# ────────────────────────────────────────────────────────────
# REDIS HELPERS (generic load/save)
# ────────────────────────────────────────────────────────────

def _redis_load(key):
    """Load a JSON value from Upstash Redis. Returns None if missing/error."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5
        )
        body = resp.json()
        raw = body.get("result")
        if raw:
            return json.loads(raw)
    except Exception as e:
        print(f"[WHA Commodity Proxy] Redis load error ({key}): {str(e)[:120]}")
    return None


def _redis_save(key, payload, ttl_seconds):
    """Save a JSON value to Upstash Redis with TTL. Stamps proxy_cached_at."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        if isinstance(payload, dict):
            payload = dict(payload)
            payload['proxy_cached_at'] = datetime.now(timezone.utc).isoformat()
        url = f"{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl_seconds)}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(payload, default=str),
            timeout=8
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[WHA Commodity Proxy] Redis save error ({key}): {str(e)[:120]}")
        return False


def _is_cache_fresh(cached, ttl_seconds):
    """Check if cached entry is within TTL."""
    if not cached or not isinstance(cached, dict) or 'proxy_cached_at' not in cached:
        return False
    try:
        cached_at = datetime.fromisoformat(cached['proxy_cached_at'])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        return age < ttl_seconds
    except Exception:
        return False


# ────────────────────────────────────────────────────────────
# UPSTREAM FETCHERS (ME BACKEND)
# ────────────────────────────────────────────────────────────

def _fetch_pressure_from_me(target):
    """Fetch /api/commodity-pressure/<target> from ME backend."""
    try:
        url = f"{ME_BACKEND_URL}/api/commodity-pressure/{target.lower()}"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"[WHA Commodity Proxy] ME pressure HTTP {resp.status_code} for {target}")
            return None
        return resp.json()
    except Exception as e:
        print(f"[WHA Commodity Proxy] ME pressure fetch error for {target}: {str(e)[:120]}")
        return None


def _fetch_fingerprint_country_from_me(country):
    """Fetch /api/commodity-fingerprint/<country> from ME backend."""
    try:
        url = f"{ME_BACKEND_URL}/api/commodity-fingerprint/{country.lower()}"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            print(f"[WHA Commodity Proxy] ME fingerprint HTTP {resp.status_code} for {country}")
            return None
        return resp.json()
    except Exception as e:
        print(f"[WHA Commodity Proxy] ME fingerprint fetch error for {country}: {str(e)[:120]}")
        return None


def _fetch_fingerprint_pair_from_me(country, commodity):
    """Fetch /api/commodity-fingerprint/<country>/<commodity> from ME backend."""
    try:
        url = f"{ME_BACKEND_URL}/api/commodity-fingerprint/{country.lower()}/{commodity.lower()}"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            print(f"[WHA Commodity Proxy] ME fp pair HTTP {resp.status_code} for {country}/{commodity}")
            return None
        return resp.json()
    except Exception as e:
        print(f"[WHA Commodity Proxy] ME fp pair fetch error for {country}/{commodity}: {str(e)[:120]}")
        return None


# ────────────────────────────────────────────────────────────
# CORE PROXY FUNCTIONS — pressure (country-level) + fingerprints
# ────────────────────────────────────────────────────────────

def get_commodity_pressure(target, force=False):
    """
    Three-layer cascade for country-level commodity pressure:
      1. WHA Redis cache fresh? → return.
      2. Fetch from ME backend → write-through cache → return.
      3. ME unavailable + stale cache? → return stale with flag.
      4. Nothing → empty placeholder.
    """
    target = (target or '').lower().strip()
    if not target:
        return {
            'success':              False,
            'error':                'Target required',
            'commodity_pressure':   0,
            'commodity_summaries':  [],
        }

    if not force:
        cached = _redis_load(_pressure_redis_key(target))
        if cached and _is_cache_fresh(cached, COMMODITY_PRESSURE_TTL_SECONDS):
            cached['cache_status'] = 'hit'
            return cached

    fresh = _fetch_pressure_from_me(target)
    if fresh and fresh.get('success', True) is not False:
        _redis_save(_pressure_redis_key(target), fresh, COMMODITY_PRESSURE_TTL_SECONDS)
        fresh['cache_status'] = 'miss-fetched'
        return fresh

    # ME unavailable — stale fallback
    stale = _redis_load(_pressure_redis_key(target)) if not force else None
    if stale:
        stale['cache_status'] = 'stale-fallback'
        stale['warning']      = 'ME backend unavailable; serving stale cache'
        return stale

    return {
        'success':              True,
        'country':              target,
        'commodity_pressure':   0,
        'alert_level':          'normal',
        'commodity_summaries':  [],
        'top_signals':          [],
        'message':              'Commodity data not yet available. First scan pending.',
        'cache_status':         'empty',
    }


def get_commodity_fingerprints_for_country(country, force=False):
    """
    Three-layer cascade for the all-commodities fingerprint endpoint.
    Mirrors get_commodity_pressure() but with FINGERPRINT_TTL (1h).
    """
    country = (country or '').lower().strip()
    if not country:
        return {
            'success':                  False,
            'error':                    'Country required',
            'fingerprints':             {},
            'pressure_count':           0,
        }

    cache_key = _fingerprint_redis_key_country(country)

    if not force:
        cached = _redis_load(cache_key)
        if cached and _is_cache_fresh(cached, FINGERPRINT_TTL_SECONDS):
            cached['cache_status'] = 'hit'
            return cached

    fresh = _fetch_fingerprint_country_from_me(country)
    if fresh is not None:
        _redis_save(cache_key, fresh, FINGERPRINT_TTL_SECONDS)
        fresh['cache_status'] = 'miss-fetched'
        return fresh

    stale = _redis_load(cache_key) if not force else None
    if stale:
        stale['cache_status'] = 'stale-fallback'
        stale['warning']      = 'ME backend unavailable; serving stale fingerprints'
        return stale

    # Empty placeholder — registry default
    return {
        'country':                  country,
        'registered_commodities':   [],
        'commodities_with_pressure': [],
        'fingerprints':             {},
        'pressure_count':           0,
        'cache_status':             'empty',
    }


def get_commodity_fingerprint_pair(country, commodity, force=False):
    """Single (country, commodity) fingerprint with caching."""
    country   = (country or '').lower().strip()
    commodity = (commodity or '').lower().strip()
    if not country or not commodity:
        return {
            'country':       country,
            'commodity':     commodity,
            'fingerprint':   None,
            'has_pressure':  False,
            'error':         'Country and commodity required',
        }

    cache_key = _fingerprint_redis_key_pair(country, commodity)

    if not force:
        cached = _redis_load(cache_key)
        if cached and _is_cache_fresh(cached, FINGERPRINT_TTL_SECONDS):
            cached['cache_status'] = 'hit'
            return cached

    fresh = _fetch_fingerprint_pair_from_me(country, commodity)
    if fresh is not None:
        _redis_save(cache_key, fresh, FINGERPRINT_TTL_SECONDS)
        fresh['cache_status'] = 'miss-fetched'
        return fresh

    stale = _redis_load(cache_key) if not force else None
    if stale:
        stale['cache_status'] = 'stale-fallback'
        stale['warning']      = 'ME backend unavailable; serving stale fingerprint'
        return stale

    return {
        'country':         country,
        'commodity':       commodity,
        'fingerprint':     None,
        'has_pressure':    False,
        'cache_status':    'empty',
    }


# ────────────────────────────────────────────────────────────
# BACKGROUND REFRESH WORKER
# ────────────────────────────────────────────────────────────

# WHA-active stability/rhetoric pages get their commodity pressure +
# fingerprints proactively refreshed so users don't see slow first-loads.
# Add new countries here as their pages ship.
PROACTIVE_REFRESH_TARGETS = ['peru', 'cuba', 'chile']

_refresh_lock = threading.Lock()
_last_pressure_refresh    = {}   # target -> ts
_last_fingerprint_refresh = {}   # country -> ts


def _background_refresh_loop():
    """
    Background daemon: every hour, check if any cached target is overdue
    and refresh from ME backend. Spreads load with brief sleeps between
    targets so we don't hammer ME backend.
    """
    time.sleep(120)  # 2 min initial warm-up

    while True:
        try:
            now = time.time()
            for target in PROACTIVE_REFRESH_TARGETS:
                # Pressure refresh (12h cadence)
                with _refresh_lock:
                    last_p = _last_pressure_refresh.get(target, 0)
                if (now - last_p) > COMMODITY_PRESSURE_TTL_SECONDS:
                    print(f"[WHA Commodity Proxy] Background pressure refresh: {target}")
                    fresh = _fetch_pressure_from_me(target)
                    if fresh:
                        _redis_save(_pressure_redis_key(target), fresh,
                                    COMMODITY_PRESSURE_TTL_SECONDS)
                        with _refresh_lock:
                            _last_pressure_refresh[target] = now
                    time.sleep(2)

                # Fingerprint refresh (1h cadence)
                with _refresh_lock:
                    last_f = _last_fingerprint_refresh.get(target, 0)
                if (now - last_f) > FINGERPRINT_TTL_SECONDS:
                    print(f"[WHA Commodity Proxy] Background fingerprint refresh: {target}")
                    fresh = _fetch_fingerprint_country_from_me(target)
                    if fresh is not None:
                        _redis_save(_fingerprint_redis_key_country(target), fresh,
                                    FINGERPRINT_TTL_SECONDS)
                        with _refresh_lock:
                            _last_fingerprint_refresh[target] = now
                    time.sleep(2)

            # Loop every hour — fingerprint TTL is 1h so this is the right cadence
            time.sleep(3600)
        except Exception as e:
            print(f"[WHA Commodity Proxy] Background loop error: {str(e)[:120]}")
            time.sleep(600)


def _start_background_worker():
    t = threading.Thread(target=_background_refresh_loop,
                         daemon=True, name='WhaCommodityProxyBG')
    t.start()
    print("[WHA Commodity Proxy] ✅ Background refresh worker started "
          "(pressure 12h / fingerprints 1h)")


# ────────────────────────────────────────────────────────────
# FLASK ENDPOINT REGISTRATION
# ────────────────────────────────────────────────────────────

def register_wha_commodity_proxy(app, start_background=True):
    """
    Register WHA commodity proxy endpoints.
    Call from app.py: register_wha_commodity_proxy(app)
    """

    @app.route('/api/wha/commodity/<target>', methods=['GET', 'OPTIONS'])
    def api_wha_commodity_target(target):
        """Country-level commodity pressure (12h cache)."""
        if request.method == 'OPTIONS':
            return '', 200
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            data  = get_commodity_pressure(target, force=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   str(e)[:200],
                'country': target,
            }), 500

    @app.route('/api/wha/commodity-fingerprint/<country>', methods=['GET', 'OPTIONS'])
    def api_wha_commodity_fp_country(country):
        """All commodity supply-risk fingerprints for a country (1h cache)."""
        if request.method == 'OPTIONS':
            return '', 200
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            data  = get_commodity_fingerprints_for_country(country, force=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'country':      country,
                'fingerprints': {},
                'error':        str(e)[:200],
            }), 500

    @app.route('/api/wha/commodity-fingerprint/<country>/<commodity>', methods=['GET', 'OPTIONS'])
    def api_wha_commodity_fp_pair(country, commodity):
        """Single (country, commodity) supply-risk fingerprint (1h cache)."""
        if request.method == 'OPTIONS':
            return '', 200
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            data  = get_commodity_fingerprint_pair(country, commodity, force=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'country':     country,
                'commodity':   commodity,
                'fingerprint': None,
                'error':       str(e)[:200],
            }), 500

    @app.route('/api/wha/commodity-debug', methods=['GET'])
    def api_wha_commodity_debug():
        """Diagnostic — what's cached, how old, ME reachability."""
        debug = {
            'version':                  '1.0.0',
            'me_backend_url':           ME_BACKEND_URL,
            'pressure_cache_ttl_hours': COMMODITY_PRESSURE_TTL_SECONDS / 3600,
            'fingerprint_cache_ttl_hours': FINGERPRINT_TTL_SECONDS / 3600,
            'proactive_targets':        PROACTIVE_REFRESH_TARGETS,
            'redis_configured':         bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'cached_targets':           {},
        }
        for tgt in PROACTIVE_REFRESH_TARGETS:
            entry = {}
            p = _redis_load(_pressure_redis_key(tgt))
            if p:
                entry['pressure'] = {
                    'cached_at':       p.get('proxy_cached_at'),
                    'fresh':           _is_cache_fresh(p, COMMODITY_PRESSURE_TTL_SECONDS),
                    'commodity_count': len(p.get('commodity_summaries', [])),
                    'pressure_score':  p.get('commodity_pressure'),
                }
            else:
                entry['pressure'] = None

            f = _redis_load(_fingerprint_redis_key_country(tgt))
            if f:
                entry['fingerprints'] = {
                    'cached_at':                 f.get('proxy_cached_at'),
                    'fresh':                     _is_cache_fresh(f, FINGERPRINT_TTL_SECONDS),
                    'pressure_count':            f.get('pressure_count', 0),
                    'commodities_with_pressure': f.get('commodities_with_pressure', []),
                }
            else:
                entry['fingerprints'] = None
            debug['cached_targets'][tgt] = entry

        # ME reachability ping
        try:
            r = requests.get(f"{ME_BACKEND_URL}/api/commodity-debug", timeout=5)
            debug['me_backend_reachable'] = (r.status_code == 200)
        except Exception:
            debug['me_backend_reachable'] = False
        return jsonify(debug)

    # ========================================================================
    # LEADER COMMODITY INTERVENTIONS — Proxy passthroughs to ME backend
    # ========================================================================
    # Detection + fingerprints live on the ME backend (canonical source). These
    # passthroughs let WHA country-stability pages call their own regional
    # backend without needing to know where the data lives. No local caching —
    # ME fingerprint already has 12h TTL.

    @app.route('/api/wha/leader-interventions/<country>', methods=['GET', 'OPTIONS'])
    def api_wha_leader_interventions_country(country):
        """Proxy: per-country leader interventions, forwards to ME backend."""
        if request.method == 'OPTIONS':
            return '', 200
        country = (country or '').lower().strip()
        try:
            r = requests.get(
                f"{ME_BACKEND_URL}/api/leader-interventions/{country}",
                timeout=8
            )
            if r.status_code == 200:
                return jsonify(r.json())
            return jsonify({
                'success': False,
                'country': country,
                'intervention_count': 0,
                'interventions': [],
                'error': f'ME backend returned {r.status_code}',
            }), 200
        except Exception as e:
            return jsonify({
                'success': False,
                'country': country,
                'intervention_count': 0,
                'interventions': [],
                'error': f'ME backend unreachable: {str(e)[:120]}',
            }), 200

    @app.route('/api/wha/leader-interventions/commodity/<commodity>', methods=['GET', 'OPTIONS'])
    def api_wha_leader_interventions_commodity(commodity):
        """Proxy: cross-country interventions for one commodity, forwards to ME backend."""
        if request.method == 'OPTIONS':
            return '', 200
        commodity = (commodity or '').lower().strip()
        try:
            r = requests.get(
                f"{ME_BACKEND_URL}/api/leader-interventions/commodity/{commodity}",
                timeout=8
            )
            if r.status_code == 200:
                return jsonify(r.json())
            return jsonify({
                'success': False,
                'commodity': commodity,
                'intervention_count': 0,
                'interventions': [],
                'error': f'ME backend returned {r.status_code}',
            }), 200
        except Exception as e:
            return jsonify({
                'success': False,
                'commodity': commodity,
                'intervention_count': 0,
                'interventions': [],
                'error': f'ME backend unreachable: {str(e)[:120]}',
            }), 200

    @app.route('/api/wha/leader-interventions', methods=['GET', 'OPTIONS'])
    def api_wha_leader_interventions_global():
        """Proxy: global leader interventions feed, forwards to ME backend."""
        if request.method == 'OPTIONS':
            return '', 200
        try:
            r = requests.get(
                f"{ME_BACKEND_URL}/api/leader-interventions",
                timeout=8
            )
            if r.status_code == 200:
                return jsonify(r.json())
            return jsonify({
                'success': False,
                'intervention_count': 0,
                'interventions': [],
                'error': f'ME backend returned {r.status_code}',
            }), 200
        except Exception as e:
            return jsonify({
                'success': False,
                'intervention_count': 0,
                'interventions': [],
                'error': f'ME backend unreachable: {str(e)[:120]}',
            }), 200

    if start_background:
        _start_background_worker()

    print("[WHA Commodity Proxy] ✅ Endpoints registered:")
    print("  GET /api/wha/commodity/<target>")
    print("  GET /api/wha/commodity-fingerprint/<country>")
    print("  GET /api/wha/commodity-fingerprint/<country>/<commodity>")
    print("  GET /api/wha/commodity-debug")
    print("  GET /api/wha/leader-interventions")
    print("  GET /api/wha/leader-interventions/<country>")
    print("  GET /api/wha/leader-interventions/commodity/<commodity>")
