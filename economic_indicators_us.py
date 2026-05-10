"""
Asifah Analytics — U.S. Economic Stability Indicators v1.0.0
May 11, 2026

Standalone module that fetches U.S. economic data from FRED (Federal Reserve
Economic Data) as primary source, with Yahoo Finance as fallback for
market-data series. Outputs structured indicator data consumable by
us_stability.py for the Economic Stability dimension scoring.

CRITICAL FRAMING:
  This module is SCOPED FOR STABILITY ANALYSIS, NOT INVESTMENT COMMENTARY.
  Outputs measure "how stable is the average American's economic situation?"
  not "should you buy/sell anything?". Strictly Asifah-side; CAVE (the
  separate investment-product) will consume this same data later from a
  different analytical lens.

  Examples of correct framing:
    ✓ "Inflation pressure on consumer purchasing power"
    ✓ "Cost of housing relative to median income"
    ✓ "Federal sovereign-credit signals"
    ✗ "Watch energy stocks"  (← that's CAVE territory, not Asifah)
    ✗ "Buy gold as hedge"    (← never)

INDICATORS TRACKED (18 total):

  Top-line (always visible on stability card):
    1. S&P 500 — broad equity market level
    2. National avg gas price (regular grade)
    3. Consumer Price Index (CPI) YoY change
    4. Unemployment rate
    5. 30-year fixed mortgage rate

  Expanded (visible on card expand):
    6. NASDAQ Composite
    7. Dow Jones Industrial Average
    8. Dollar Index (DXY)
    9. 10-year Treasury yield (sovereign credit signal)
    10. Federal Funds Rate (Fed policy rate)
    11. Initial unemployment claims (weekly)
    12. Crude oil (WTI) price
    13. Natural gas (Henry Hub) price
    14. Gold price ($/oz)
    15. Bitcoin price (alt-stability signal)
    16. Federal deficit-to-GDP (latest available)
    17. Median home price
    18. Consumer confidence index (latest)

ARCHITECTURE:
  - FRED is the canonical source for macroeconomic series (CPI, unemployment,
    rates, GDP, federal data). Free API, generous rate limits, gold-standard.
  - Yahoo Finance fills gaps where FRED is delayed or unavailable: real-time
    market data (S&P/NASDAQ/Dow tick prices, BTC, etc.) is faster on Yahoo.
  - Each indicator function tries FRED first, falls back to Yahoo if
    FRED fails or returns stale data.
  - Results are cached in Upstash Redis for 12h to avoid hammering APIs.

USAGE:
    from economic_indicators_us import fetch_economic_indicators
    result = fetch_economic_indicators()
    # → {success: True, indicators: {...}, source_breakdown: {...}, ...}

GRACEFUL DEGRADATION:
  - If FRED_API_KEY env var missing → logs warning, uses Yahoo only
  - If both fail for an indicator → indicator returns null with error tag
  - If Redis missing → in-memory cache only (works in dev, less efficient)

COPYRIGHT © 2025-2026 Asifah Analytics. All rights reserved.
"""

# ============================================================
# IMPORTS
# ============================================================

import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta


# ============================================================
# CONFIGURATION
# ============================================================

print("[Economic Indicators US] Module loading...")

FRED_API_KEY = os.environ.get('FRED_API_KEY')
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

CACHE_KEY = 'economic_indicators_us_cache'
CACHE_TTL_SECONDS = 12 * 3600    # 12h

# In-memory fallback when Redis unavailable
_memory_cache = {'data': None, 'cached_at': 0}

# Generous default timeout — FRED can be slow during peak times
DEFAULT_TIMEOUT = 12

if FRED_API_KEY:
    print("[Economic Indicators US] ✅ FRED API key configured")
else:
    print("[Economic Indicators US] ⚠️  FRED_API_KEY missing — Yahoo-only fallback mode")


# ============================================================
# INDICATOR REGISTRY — defines what we track and how
# ============================================================

# Each indicator has:
#   - 'id': stable internal id used in output dict
#   - 'name': display name (English; UI handles i18n separately)
#   - 'unit': '%', '$', 'index', 'bps', etc. (for display formatting)
#   - 'fred_series': FRED series ID (None if FRED-unsupported)
#   - 'yahoo_symbol': Yahoo Finance ticker (None if not market-traded)
#   - 'tier': 'top' (always visible) or 'expanded' (on expand)
#   - 'frame': stability framing — what does this measure for stability?
#   - 'good_direction': 'up' or 'down' — which direction is good for stability?
#       (e.g., S&P up = stability good; CPI up = stability bad; unemployment up = bad)
#       Used for trend-arrow coloring; NOT for any investment recommendation.

INDICATORS = {
    # ── TOP TIER — always visible on stability card ──
    'sp500': {
        'name':           'S&P 500',
        'unit':           'index',
        'fred_series':    'SP500',
        'yahoo_symbol':   '^GSPC',
        'tier':           'top',
        'frame':          'Broad equity market level — proxy for U.S. corporate earnings expectations.',
        'good_direction': 'up',
    },
    'gas_price': {
        'name':           'National Avg Gas Price',
        'unit':           '$/gal',
        'fred_series':    'GASREGW',     # Regular All Formulations Gas Price
        'yahoo_symbol':   None,
        'tier':           'top',
        'frame':          'Cost of household transportation. Tracks consumer-felt energy prices.',
        'good_direction': 'down',
    },
    'cpi_yoy': {
        'name':           'Consumer Price Index (YoY)',
        'unit':           '%',
        'fred_series':    'CPIAUCSL',    # CPI All Urban Consumers — we compute YoY
        'yahoo_symbol':   None,
        'tier':           'top',
        'frame':          'Inflation rate. Above 2% Fed target = sustained pressure on purchasing power.',
        'good_direction': 'down',
        'compute':        'yoy_change',
    },
    'unemployment': {
        'name':           'Unemployment Rate',
        'unit':           '%',
        'fred_series':    'UNRATE',
        'yahoo_symbol':   None,
        'tier':           'top',
        'frame':          'Headline unemployment. Above 5% = sustained labor-market stress.',
        'good_direction': 'down',
    },
    'mortgage_30yr': {
        'name':           '30-Year Fixed Mortgage Rate',
        'unit':           '%',
        'fred_series':    'MORTGAGE30US',
        'yahoo_symbol':   None,
        'tier':           'top',
        'frame':          'Cost of housing. Direct hit to household formation, housing market.',
        'good_direction': 'down',
    },

    # ── EXPANDED TIER — visible on card expand ──
    'nasdaq': {
        'name':           'NASDAQ Composite',
        'unit':           'index',
        'fred_series':    'NASDAQCOM',
        'yahoo_symbol':   '^IXIC',
        'tier':           'expanded',
        'frame':          'Tech-heavy equity index. Sentiment proxy for innovation sector.',
        'good_direction': 'up',
    },
    'dow': {
        'name':           'Dow Jones Industrial Average',
        'unit':           'index',
        'fred_series':    'DJIA',
        'yahoo_symbol':   '^DJI',
        'tier':           'expanded',
        'frame':          'Industrial-heavy equity index. Old-economy sentiment.',
        'good_direction': 'up',
    },
    'dxy': {
        'name':           'Dollar Index (DXY)',
        'unit':           'index',
        'fred_series':    'DTWEXBGS',    # Trade Weighted Dollar Index
        'yahoo_symbol':   'DX-Y.NYB',
        'tier':           'expanded',
        'frame':          'Dollar strength vs basket. High = exports stressed but imports cheaper.',
        'good_direction': None,    # neither direction strictly "good" for stability
    },
    'treasury_10y': {
        'name':           '10-Year Treasury Yield',
        'unit':           '%',
        'fred_series':    'DGS10',
        'yahoo_symbol':   '^TNX',
        'tier':           'expanded',
        'frame':          'Sovereign credit signal. Long-term rate driver. Above 5% = elevated borrowing costs across the economy.',
        'good_direction': 'down',
    },
    'fed_funds': {
        'name':           'Federal Funds Rate',
        'unit':           '%',
        'fred_series':    'FEDFUNDS',
        'yahoo_symbol':   None,
        'tier':           'expanded',
        'frame':          'Fed policy rate — measures monetary tightness.',
        'good_direction': None,    # context-dependent
    },
    'jobless_claims': {
        'name':           'Initial Jobless Claims (weekly)',
        'unit':           'count',
        'fred_series':    'ICSA',
        'yahoo_symbol':   None,
        'tier':           'expanded',
        'frame':          'Leading labor-market signal. Above 250K sustained = recession watch.',
        'good_direction': 'down',
    },
    'crude_oil': {
        'name':           'Crude Oil (WTI)',
        'unit':           '$/bbl',
        'fred_series':    'DCOILWTICO',
        'yahoo_symbol':   'CL=F',
        'tier':           'expanded',
        'frame':          'Energy supply pressure. High = transmission to gas pump + transport costs.',
        'good_direction': 'down',
    },
    'natgas': {
        'name':           'Natural Gas (Henry Hub)',
        'unit':           '$/mmbtu',
        'fred_series':    'DHHNGSP',
        'yahoo_symbol':   'NG=F',
        'tier':           'expanded',
        'frame':          'Heating + electricity-generation cost driver.',
        'good_direction': 'down',
    },
    'gold': {
        'name':           'Gold Spot',
        'unit':           '$/oz',
        'fred_series':    None,           # FRED doesn't carry spot gold reliably
        'yahoo_symbol':   'GC=F',
        'tier':           'expanded',
        'frame':          'Macro-uncertainty signal. Persistent rises = institutional hedging.',
        'good_direction': None,
    },
    'bitcoin': {
        'name':           'Bitcoin',
        'unit':           '$',
        'fred_series':    None,
        'yahoo_symbol':   'BTC-USD',
        'tier':           'expanded',
        'frame':          'Alt-stability signal. High beta vs traditional markets.',
        'good_direction': None,
    },
    'deficit_gdp': {
        'name':           'Federal Deficit / GDP',
        'unit':           '%',
        'fred_series':    'FYFSGDA188S',   # Federal surplus or deficit as % of GDP (annual)
        'yahoo_symbol':   None,
        'tier':           'expanded',
        'frame':          'Sovereign fiscal stance. Deeper deficits = future fiscal pressure.',
        'good_direction': 'up',           # deficit-as-% of GDP — closer to 0 (or positive surplus) is better
    },
    'home_price': {
        'name':           'Median New Home Sale Price',
        'unit':           '$',
        'fred_series':    'MSPNHSUS',     # Median Sales Price of New Houses Sold
        'yahoo_symbol':   None,
        'tier':           'expanded',
        'frame':          'Housing-affordability driver. Trends affect household formation.',
        'good_direction': None,           # depends on perspective (homeowner vs prospective buyer)
    },
    'consumer_confidence': {
        'name':           'Consumer Sentiment (UMich)',
        'unit':           'index',
        'fred_series':    'UMCSENT',     # University of Michigan Consumer Sentiment
        'yahoo_symbol':   None,
        'tier':           'expanded',
        'frame':          'Household-felt economic mood. Leading indicator for consumption.',
        'good_direction': 'up',
    },
}


# ============================================================
# REDIS HELPERS
# ============================================================

def _redis_get(key):
    """Read JSON value from Redis. Returns None on miss/error."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        body = resp.json()
        if body.get('result'):
            return json.loads(body['result'])
    except Exception as e:
        print(f"[Economic Indicators US] Redis get error: {str(e)[:120]}")
    return None


def _redis_set(key, value, ttl_seconds=CACHE_TTL_SECONDS):
    """Write JSON value to Redis with TTL. Best-effort — never raises."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl_seconds)}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(value, default=str),
            timeout=8,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Economic Indicators US] Redis set error: {str(e)[:120]}")
        return False


# ============================================================
# FRED API CLIENT
# ============================================================

def _fred_fetch(series_id, observations=2, units=None):
    """Fetch a FRED series. Returns list of {date, value} dicts (most recent first)
    or None on any error.

    Parameters:
        series_id: FRED series ID (e.g., 'CPIAUCSL', 'UNRATE')
        observations: how many recent observations to return
        units: 'lin' (default), 'pc1' (% change YoY), 'pch' (% change MoM)
    """
    if not FRED_API_KEY:
        return None
    try:
        params = {
            'series_id':        series_id,
            'api_key':          FRED_API_KEY,
            'file_type':        'json',
            'sort_order':       'desc',
            'limit':            observations,
        }
        if units:
            params['units'] = units
        resp = requests.get(FRED_BASE_URL, params=params, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            print(f"[FRED] {series_id}: HTTP {resp.status_code}")
            return None
        data = resp.json()
        observations_list = data.get('observations', [])
        # Filter out FRED's "." sentinel values (no data) and convert to float
        cleaned = []
        for obs in observations_list:
            try:
                v = obs.get('value', '')
                if v in ('.', '', None):
                    continue
                cleaned.append({
                    'date':  obs.get('date'),
                    'value': float(v),
                })
            except (ValueError, TypeError):
                continue
        return cleaned if cleaned else None
    except Exception as e:
        print(f"[FRED] {series_id}: error — {str(e)[:120]}")
        return None


def _fred_compute_yoy(series_id):
    """Compute year-over-year % change for a series.
    Uses FRED's built-in 'pc1' transformation when possible (cleanest)."""
    obs = _fred_fetch(series_id, observations=1, units='pc1')
    if obs and len(obs) > 0:
        return obs[0]
    return None


# ============================================================
# YAHOO FINANCE CLIENT (fallback for market data)
# ============================================================

def _yahoo_fetch(symbol):
    """Fetch latest quote from Yahoo Finance. Returns {price, prev_close, date}
    dict or None on error.

    Uses the v7/finance/spark endpoint as primary and chart endpoint as backup.
    Yahoo has been increasingly rate-limiting; we use rotating User-Agents and
    multiple endpoint strategies for resilience."""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
            '(KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    ]

    # ── Strategy 1: v7 spark endpoint (lighter, less aggressive blocking) ──
    for ua in user_agents:
        try:
            url = "https://query1.finance.yahoo.com/v7/finance/spark"
            params = {
                'symbols':  symbol,
                'range':    '5d',
                'interval': '1d',
            }
            headers = {
                'User-Agent':       ua,
                'Accept':           'application/json,text/plain,*/*',
                'Accept-Language':  'en-US,en;q=0.9',
            }
            resp = requests.get(url, params=params, headers=headers,
                                timeout=DEFAULT_TIMEOUT)
            if resp.status_code != 200:
                continue
            data = resp.json()
            spark = (data.get('spark') or {}).get('result') or []
            if not spark:
                continue
            sym_data = spark[0].get('response') or []
            if not sym_data:
                continue
            sym_data = sym_data[0]
            meta = sym_data.get('meta') or {}
            price = meta.get('regularMarketPrice')
            prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
            timestamp = meta.get('regularMarketTime')
            if price is not None:
                return {
                    'price':       float(price),
                    'prev_close':  float(prev_close) if prev_close else None,
                    'date':        (datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
                                    if timestamp else None),
                }
        except Exception:
            continue

    # ── Strategy 2: v8 chart endpoint (original) ──
    for ua in user_agents:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            params = {
                'interval': '1d',
                'range':    '5d',
            }
            headers = {
                'User-Agent':       ua,
                'Accept':           'application/json,text/plain,*/*',
                'Accept-Language':  'en-US,en;q=0.9',
                'Referer':          'https://finance.yahoo.com/',
            }
            resp = requests.get(url, params=params, headers=headers,
                                timeout=DEFAULT_TIMEOUT)
            if resp.status_code != 200:
                continue
            data = resp.json()
            result = (data.get('chart') or {}).get('result') or []
            if not result:
                continue
            result = result[0]
            meta = result.get('meta') or {}
            price = meta.get('regularMarketPrice')
            prev_close = meta.get('previousClose') or meta.get('chartPreviousClose')
            timestamp = meta.get('regularMarketTime')
            if price is not None:
                return {
                    'price':       float(price),
                    'prev_close':  float(prev_close) if prev_close else None,
                    'date':        (datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
                                    if timestamp else None),
                }
        except Exception:
            continue

    print(f"[Yahoo] {symbol}: all fetch strategies failed")
    return None


# ============================================================
# INDICATOR FETCHERS — FRED-first, Yahoo fallback
# ============================================================

def _fetch_indicator(indicator_id):
    """Fetch a single indicator using its registry config.
    Returns dict with {value, prev_value, change, change_pct, source, asof, ...}
    or None on total failure."""
    cfg = INDICATORS.get(indicator_id)
    if not cfg:
        return None

    fred_series = cfg.get('fred_series')
    yahoo_symbol = cfg.get('yahoo_symbol')
    compute = cfg.get('compute')

    result = {
        'id':          indicator_id,
        'name':        cfg['name'],
        'unit':        cfg['unit'],
        'tier':        cfg['tier'],
        'frame':       cfg['frame'],
        'good_direction': cfg.get('good_direction'),
        'value':       None,
        'prev_value':  None,
        'change':      None,
        'change_pct':  None,
        'source':      None,
        'asof':        None,
        'error':       None,
    }

    # ── PRIMARY: FRED ──
    if fred_series and FRED_API_KEY:
        try:
            if compute == 'yoy_change':
                obs = _fred_compute_yoy(fred_series)
                if obs:
                    result['value']  = round(obs['value'], 2)
                    result['source'] = 'FRED (YoY)'
                    result['asof']   = obs['date']
                    return result
            else:
                obs_list = _fred_fetch(fred_series, observations=2)
                if obs_list and len(obs_list) >= 1:
                    result['value']  = round(obs_list[0]['value'], 2)
                    result['source'] = 'FRED'
                    result['asof']   = obs_list[0]['date']
                    if len(obs_list) >= 2:
                        result['prev_value'] = round(obs_list[1]['value'], 2)
                        result['change']     = round(obs_list[0]['value'] - obs_list[1]['value'], 2)
                        if obs_list[1]['value'] != 0:
                            result['change_pct'] = round(
                                (obs_list[0]['value'] - obs_list[1]['value']) /
                                abs(obs_list[1]['value']) * 100, 2)
                    return result
        except Exception as e:
            print(f"[Economic Indicators US] FRED error for {indicator_id}: {str(e)[:120]}")

    # ── FALLBACK: Yahoo ──
    if yahoo_symbol:
        try:
            quote = _yahoo_fetch(yahoo_symbol)
            if quote and quote.get('price') is not None:
                result['value']  = round(quote['price'], 2)
                result['source'] = 'Yahoo Finance'
                result['asof']   = quote.get('date')
                if quote.get('prev_close') is not None:
                    result['prev_value'] = round(quote['prev_close'], 2)
                    result['change']     = round(quote['price'] - quote['prev_close'], 2)
                    if quote['prev_close'] != 0:
                        result['change_pct'] = round(
                            (quote['price'] - quote['prev_close']) /
                            abs(quote['prev_close']) * 100, 2)
                return result
        except Exception as e:
            print(f"[Economic Indicators US] Yahoo error for {indicator_id}: {str(e)[:120]}")

    # Both failed
    result['error'] = 'Both FRED and Yahoo failed or unavailable for this indicator'
    return result


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def fetch_economic_indicators(force_refresh=False):
    """Fetch all U.S. economic stability indicators.

    Returns:
        {
            'success':          bool,
            'indicators':       {indicator_id: {...}},
            'top_indicators':   [list of top-tier indicator IDs],
            'expanded_indicators': [list of expanded-tier IDs],
            'source_breakdown': {fred: int, yahoo: int, failed: int},
            'fetched_at':       ISO timestamp,
            'cached':           bool,
            'cache_age_hours':  float,
            'fred_configured':  bool,
            'version':          '1.0.0',
        }

    Cache: 12-hour Redis cache, with in-memory fallback.
    """
    # ── Cache check ──
    if not force_refresh:
        cached = _redis_get(CACHE_KEY)
        if cached and cached.get('fetched_at'):
            try:
                fetched = datetime.fromisoformat(cached['fetched_at'])
                age = (datetime.now(timezone.utc) - fetched).total_seconds()
                if age < CACHE_TTL_SECONDS:
                    cached['cached'] = True
                    cached['cache_age_hours'] = round(age / 3600, 2)
                    return cached
            except Exception:
                pass
        # Memory cache fallback for environments without Redis
        if (_memory_cache['data'] and
                time.time() - _memory_cache['cached_at'] < CACHE_TTL_SECONDS):
            d = dict(_memory_cache['data'])
            d['cached'] = True
            d['cache_age_hours'] = round(
                (time.time() - _memory_cache['cached_at']) / 3600, 2)
            return d

    print("[Economic Indicators US] Fetching fresh data from FRED + Yahoo...")
    fetch_start = time.time()

    indicators_out = {}
    source_counts = {'FRED': 0, 'FRED (YoY)': 0, 'Yahoo Finance': 0, 'failed': 0}

    for indicator_id in INDICATORS.keys():
        ind = _fetch_indicator(indicator_id)
        indicators_out[indicator_id] = ind
        if ind and ind.get('value') is not None:
            src = ind.get('source', 'unknown')
            source_counts[src] = source_counts.get(src, 0) + 1
        else:
            source_counts['failed'] += 1

    top_ids      = [k for k, v in INDICATORS.items() if v['tier'] == 'top']
    expanded_ids = [k for k, v in INDICATORS.items() if v['tier'] == 'expanded']

    elapsed = round(time.time() - fetch_start, 1)

    result = {
        'success':              True,
        'indicators':           indicators_out,
        'top_indicators':       top_ids,
        'expanded_indicators':  expanded_ids,
        'source_breakdown':     source_counts,
        'fetched_at':           datetime.now(timezone.utc).isoformat(),
        'fetch_time_seconds':   elapsed,
        'cached':               False,
        'cache_age_hours':      0,
        'fred_configured':      bool(FRED_API_KEY),
        'version':              '1.0.0',
    }

    # ── Write to caches ──
    _redis_set(CACHE_KEY, result)
    _memory_cache['data'] = result
    _memory_cache['cached_at'] = time.time()

    print(f"[Economic Indicators US] ✅ Fetched {len(indicators_out)} indicators "
          f"in {elapsed}s — FRED:{source_counts.get('FRED', 0) + source_counts.get('FRED (YoY)', 0)} "
          f"Yahoo:{source_counts.get('Yahoo Finance', 0)} "
          f"failed:{source_counts['failed']}")

    return result


# ============================================================
# FLASK ENDPOINT REGISTRATION
# ============================================================

def register_economic_indicators_endpoints(app):
    """Register the /api/economic-indicators-us Flask endpoints."""

    @app.route('/api/economic-indicators-us', methods=['GET', 'OPTIONS'])
    def api_economic_indicators_us():
        from flask import request as flask_request, jsonify
        if flask_request.method == 'OPTIONS':
            return '', 200
        try:
            force = flask_request.args.get('refresh', 'false').lower() == 'true'
            result = fetch_economic_indicators(force_refresh=force)
            return jsonify(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/economic-indicators-us/debug', methods=['GET'])
    def api_economic_indicators_us_debug():
        """Diagnostic endpoint — shows registry config + cache status."""
        from flask import jsonify
        cached = _redis_get(CACHE_KEY)
        return jsonify({
            'version':              '1.0.0',
            'fred_configured':      bool(FRED_API_KEY),
            'redis_configured':     bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'cache_ttl_hours':      CACHE_TTL_SECONDS / 3600,
            'indicator_count':      len(INDICATORS),
            'top_count':            len([k for k, v in INDICATORS.items() if v['tier'] == 'top']),
            'expanded_count':       len([k for k, v in INDICATORS.items() if v['tier'] == 'expanded']),
            'cached_data_present':  bool(cached),
            'cached_fetched_at':    (cached or {}).get('fetched_at'),
            'cached_source_breakdown': (cached or {}).get('source_breakdown'),
            'all_indicators':       [
                {'id': k, 'name': v['name'], 'unit': v['unit'], 'tier': v['tier'],
                 'fred_series': v['fred_series'], 'yahoo_symbol': v['yahoo_symbol']}
                for k, v in INDICATORS.items()
            ],
        })

    print("[Economic Indicators US] ✅ Endpoints registered: "
          "/api/economic-indicators-us, /api/economic-indicators-us/debug")


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == '__main__':
    """Self-test — fetches all indicators and prints structured output."""
    print("\n" + "=" * 60)
    print("ECONOMIC INDICATORS US — SELF-TEST")
    print("=" * 60)

    result = fetch_economic_indicators(force_refresh=True)

    print(f"\nFetched {len(result['indicators'])} indicators in "
          f"{result['fetch_time_seconds']}s")
    print(f"Sources: FRED={result['source_breakdown'].get('FRED', 0) + result['source_breakdown'].get('FRED (YoY)', 0)}, "
          f"Yahoo={result['source_breakdown'].get('Yahoo Finance', 0)}, "
          f"Failed={result['source_breakdown']['failed']}")
    print(f"FRED configured: {result['fred_configured']}")

    print("\n=== TOP-TIER INDICATORS (always visible) ===")
    for iid in result['top_indicators']:
        ind = result['indicators'].get(iid, {})
        v = ind.get('value')
        u = ind.get('unit', '')
        ch = ind.get('change')
        src = ind.get('source', '???')
        if v is None:
            print(f"  ❌ {ind.get('name'):40s} — UNAVAILABLE ({ind.get('error', 'no data')})")
        else:
            change_str = f"({ch:+.2f})" if ch is not None else ""
            print(f"  ✅ {ind.get('name'):40s} {v:>10} {u:8s} {change_str:12s} [{src}]")

    print("\n=== EXPANDED-TIER INDICATORS (on expand) ===")
    for iid in result['expanded_indicators']:
        ind = result['indicators'].get(iid, {})
        v = ind.get('value')
        u = ind.get('unit', '')
        ch = ind.get('change')
        src = ind.get('source', '???')
        if v is None:
            print(f"  ❌ {ind.get('name'):40s} — UNAVAILABLE")
        else:
            change_str = f"({ch:+.2f})" if ch is not None else ""
            print(f"  ✅ {ind.get('name'):40s} {v:>10} {u:8s} {change_str:12s} [{src}]")

    print("\n✅ SELF-TEST COMPLETE")
