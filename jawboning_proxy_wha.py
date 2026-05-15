"""
Asifah Analytics — JAWBONING PROXY (Asia backend)
v1.0.0 — May 15, 2026

PLACEMENT: WHA backend (asifah-wha-backend.onrender.com).
Mirrors the absorption_proxy_asia.py + commodity_proxy_asia.py pattern.

PURPOSE:
========
Forwards jawboning-detection requests from WHA-side trackers (currently
just rhetoric_tracker_us.py, but future Cuba/Mexico/Venezuela trackers
can use the same proxy) to the ME backend, which owns:
  • jawboning_signatures.py    — the catalog of 13 signatures
  • jawboning_detector.py      — the detection logic + fingerprint writes
  • Redis fingerprints         — jawboning:{direction}:{country}:{target}

ARCHITECTURE:
=============

  Asia backend                              ME backend
  ──────────────                            ──────────────
  rhetoric_tracker_us.py
        │  (calls detect_jawboning_via_proxy)
        ▼
  jawboning_proxy_asia.py
        │   HTTPS POST
        ▼
                                  /api/jawboning/detect
                                  (jawboning_detector.py)
                                        │
                                        ▼
                                  Apply catalog logic per signature
                                        │
                                        ▼
                                  Redis fingerprint writes
                                  (24h TTL, envelope payload)

WHY HTTP PROXY (not local import):
==================================
Same reason as absorption + commodity: ONE detector implementation, ONE
catalog source-of-truth, ONE place to add new signatures (Xi, MBS, Erdogan)
without multi-backend redeploys. Cross-theater consumers (Iran, China,
Cuba, Russia trackers) read fingerprints from Redis directly — they never
call the detector.

PUBLIC API:
===========

  detect_jawboning_via_proxy(leader_id, country_id, actor_results, ...)
      → dict {signature_id: bool, ...}    on success
      → {}                                on failure / unreachable ME

  Callers should treat empty dict as "no signatures fired this scan"
  rather than failing the whole scan. The detector is INFORMATIONAL — its
  output drives display + cross-theater amplification, but a tracker scan
  should complete successfully even if jawboning detection times out.

PHASE 5b NOTE (Phase 5 — May 15, 2026):
=========================================
Phase 5b is GREENFIELD for Trump signatures — unlike Phase 3 (India dual-track),
there's no pre-existing inline implementation of trump_on_china / trump_on_iran /
etc. in rhetoric_tracker_us.py to compare against. So this proxy fires Trump
signatures directly: write_fingerprints=True from day one, no comparison loop,
no `[Jawboning Compare]` lines. The catalog IS the implementation.

ENDPOINTS REGISTERED ON WHA BACKEND:
====================================
  POST /api/wha/jawboning/detect       — direct passthrough for testing
  GET  /api/wha/jawboning/debug        — ME reachability diagnostic

CALL FROM app.py:
=================
    from jawboning_proxy_wha import register_jawboning_proxy
    register_jawboning_proxy(app)

CALL FROM A TRACKER (e.g., rhetoric_tracker_us.py):
======================================================
    from jawboning_proxy_wha import detect_jawboning_via_proxy

    primitive_results = detect_jawboning_via_proxy(
        leader_id='trump',
        country_id='us',
        actor_results=<the 9-actor dict from US scan>,
        scan_id=<some scan identifier for log correlation>,
    )
    # primitive_results = {'trump_on_china': True, 'trump_on_iran': False, ...}
    # or {} on ME unreachable

CHANGELOG:
==========
  v1.0.0 (2026-05-15): Initial build. Mirrors absorption_proxy_asia.py
                       pattern. POST-only; ME endpoint accepts POST and GET
                       but proxies always POST (write-path discipline).

COPYRIGHT 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import requests
from datetime import datetime, timezone


# ────────────────────────────────────────────────────────────
# CONFIG
# ────────────────────────────────────────────────────────────

# ME backend hosts the detector + catalog + Redis writes.
# Override with env var if needed for staging.
ME_BACKEND_URL = os.environ.get(
    'ME_BACKEND_URL',
    'https://asifah-backend.onrender.com'
)

# HTTP timeout for the detection round-trip. Render cold starts can be slow.
DETECT_TIMEOUT_SECONDS = 20


# ────────────────────────────────────────────────────────────
# PUBLIC API — called directly by WHA trackers
# ────────────────────────────────────────────────────────────

def detect_jawboning_via_proxy(leader_id,
                               country_id,
                               actor_results,
                               articles=None,
                               write_fingerprints=True,
                               scan_id=None):
    """
    Send a jawboning-detection request to the ME backend.

    On success: returns the {signature_id: bool} dict the detector produced.
    On any failure: returns {} (empty dict). Callers should treat empty
    as "no signatures fired" rather than failing the scan.

    Args:
        leader_id: str — 'modi', 'trump', 'xi', etc.
        country_id: str — 'india', 'us', 'china', etc.
        actor_results: dict — per-actor scan output. Each cluster value should
                       contain 'level', 'matched_triggers', and 'top_articles'.
        articles: list — optional, currently unused by detector v1, reserved.
        write_fingerprints: bool — if True (default), ME writes Redis fingerprints
                            on positive detection. Set to False for dry-run
                            comparison logging (Phase 3 strangler-fig mode).
        scan_id: str — optional diagnostic identifier (correlates Asia scan
                 cycle with ME fingerprint writes in cross-backend logs).

    Returns:
        dict {signature_id: bool, ...} — possibly empty.
    """
    if not leader_id or not country_id:
        print("[Jawboning Proxy WHA] detect call missing leader_id or country_id")
        return {}

    body = {
        'leader_id':          leader_id,
        'country_id':         country_id,
        'actor_results':      actor_results or {},
        'articles':           articles or [],
        'write_fingerprints': bool(write_fingerprints),
    }
    if scan_id:
        body['scan_id'] = scan_id

    url = f"{ME_BACKEND_URL}/api/jawboning/detect"

    try:
        resp = requests.post(
            url,
            json=body,
            timeout=DETECT_TIMEOUT_SECONDS,
            headers={'Content-Type': 'application/json'},
        )
    except requests.exceptions.Timeout:
        print(f"[Jawboning Proxy WHA] Timeout calling ME detector for "
              f"{leader_id}/{country_id}")
        return {}
    except Exception as e:
        print(f"[Jawboning Proxy WHA] ME detector POST error for "
              f"{leader_id}/{country_id}: {e}")
        return {}

    if resp.status_code != 200:
        print(f"[Jawboning Proxy WHA] ME detector HTTP {resp.status_code} "
              f"for {leader_id}/{country_id}: {resp.text[:200]}")
        return {}

    try:
        data = resp.json()
    except Exception as e:
        print(f"[Jawboning Proxy WHA] ME detector returned non-JSON: {e}")
        return {}

    if not data.get('success'):
        print(f"[Jawboning Proxy WHA] ME detector error for "
              f"{leader_id}/{country_id}: {data.get('error', 'unknown')}")
        return {}

    results = data.get('results') or {}
    fired_count = data.get('fired_count', sum(1 for v in results.values() if v))
    if fired_count > 0:
        print(f"[Jawboning Proxy WHA] ✅ {fired_count} signature(s) fired "
              f"for {leader_id}/{country_id}"
              f"{' (wrote fingerprints)' if write_fingerprints else ' (dry-run)'}")
    return results


# ────────────────────────────────────────────────────────────
# FLASK ENDPOINTS — WHA-side passthrough + debug
# ────────────────────────────────────────────────────────────

def register_jawboning_proxy(app):
    """
    Register jawboning proxy endpoints on the Asia Flask app.
    Call from app.py:
        from jawboning_proxy_asia import register_jawboning_proxy
        register_jawboning_proxy(app)
    """
    from flask import jsonify, request as flask_request

    @app.route('/api/wha/jawboning/detect', methods=['POST', 'OPTIONS'])
    def api_wha_jawboning_detect():
        """
        WHA-side passthrough to ME's /api/jawboning/detect.
        Accepts the same JSON body shape. Useful for testing + for WHA-side
        callers other than the in-process trackers.
        """
        if flask_request.method == 'OPTIONS':
            return '', 200

        body = flask_request.get_json(silent=True) or {}
        leader_id  = body.get('leader_id')
        country_id = body.get('country_id')

        if not leader_id or not country_id:
            return jsonify({
                'success': False,
                'error':   "Missing required fields: leader_id, country_id",
                'results': {},
            }), 400

        results = detect_jawboning_via_proxy(
            leader_id=leader_id,
            country_id=country_id,
            actor_results=body.get('actor_results'),
            articles=body.get('articles'),
            write_fingerprints=bool(body.get('write_fingerprints', False)),
            scan_id=body.get('scan_id'),
        )

        return jsonify({
            'success':      True,
            'leader_id':    leader_id,
            'country_id':   country_id,
            'results':      results,
            'fired_count':  sum(1 for v in results.values() if v),
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'proxy_layer':  'wha',
        })

    @app.route('/api/wha/jawboning/debug', methods=['GET'])
    def api_wha_jawboning_debug():
        """Diagnostic — confirms ME reachability + jawboning catalog count."""
        from flask import jsonify
        debug = {
            'me_backend_url':  ME_BACKEND_URL,
            'timeout_seconds': DETECT_TIMEOUT_SECONDS,
            'me_reachable':    False,
            'me_endpoints':    None,
        }
        try:
            r = requests.get(
                f"{ME_BACKEND_URL}/api/jawboning/signatures/count",
                timeout=5,
            )
            debug['me_reachable'] = (r.status_code == 200)
            if r.status_code == 200:
                payload = r.json()
                debug['me_endpoints'] = {
                    'catalog_count': payload.get('count'),
                    'success':       payload.get('success'),
                }
        except Exception as e:
            debug['me_error'] = str(e)[:200]
        return jsonify(debug)

    print("[Jawboning Proxy WHA] ✅ Endpoints registered:")
    print("  POST /api/wha/jawboning/detect")
    print("  GET  /api/wha/jawboning/debug")
