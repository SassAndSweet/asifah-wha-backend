"""
wha_regional_bluf.py
Asifah Analytics -- Western Hemisphere Backend Module
v1.0.0 -- April 2026

Western Hemisphere Regional BLUF (Bottom Line Up Front) Engine.

Reads from WHA rhetoric tracker Redis caches and synthesizes a single
analyst-prose BLUF paragraph + top-5 structured top-line signals.

Architecture mirrors me_regional_bluf.py v2.0 + asia_regional_bluf.py v2.1
(proven canonical pattern).

Currently active trackers:
  - Cuba (rhetoric:cuba:latest) -- 9-actor model with 3-vector frame

Roadmap (slot in via TRACKER_KEYS as they come online):
  - Venezuela (post-Maduro transition watch)
  - Haiti (state failure / migration cascade)
  - Mexico (cartel military ops)
  - Panama (Panama Canal rhetoric)
  - Colombia (FARC / ELN / cartel pressures)
  - Brazil (regional balance)
  - United States (anchor page; sovereign-domestic dual axis)

v1.0.0 design choices:
- Compatibility shim _normalize_tracker_data() supports both legacy trackers
  (so_what / red_lines top-level) AND v2.0+ trackers self-emitting top_signals[]
- Output emits canonical fields (top_signals, max_level, theatre_summary,
  region: 'western_hemisphere') for direct GPI consumption
- Top 5 signals per region (matches ME, Asia)
- WHA-specific cross-tracker signal: migration_cascade (Cuba+Haiti+Mexico+Venezuela
  outflow indicators converging) -- prepared but currently latent until 2+ trackers live
- Canonical signal categories: red_line_breached, theatre_high, us_pressure_high,
  regime_fracture, adversary_access, migration_surge, off_ramp_active

Author: RCGG / Asifah Analytics
"""

import os
import json
import traceback
from datetime import datetime, timezone
import requests


# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '')

# Source caches (written by respective trackers)
TRACKER_KEYS = {
    'cuba':      'rhetoric:cuba:latest',
    'peru':      'rhetoric:peru:latest',
    # Future WHA trackers slot in here:
    # 'venezuela':  'rhetoric:venezuela:latest',
    # 'haiti':      'rhetoric:haiti:latest',
    # 'mexico':     'rhetoric:mexico:latest',
    # 'panama':     'rhetoric:panama:latest',
    # 'colombia':   'rhetoric:colombia:latest',
    # 'brazil':     'rhetoric:brazil:latest',
    # 'us':         'rhetoric:us:latest',
}

THEATRE_FLAGS = {
    'cuba':      '\U0001f1e8\U0001f1fa',  # 🇨🇺
    'peru':      '\U0001f1f5\U0001f1ea',  # 🇵🇪
    'venezuela': '\U0001f1fb\U0001f1ea',  # 🇻🇪
    'haiti':     '\U0001f1ed\U0001f1f9',  # 🇭🇹
    'mexico':    '\U0001f1f2\U0001f1fd',  # 🇲🇽
    'panama':    '\U0001f1f5\U0001f1e6',  # 🇵🇦
    'colombia':  '\U0001f1e8\U0001f1f4',  # 🇨🇴
    'brazil':    '\U0001f1e7\U0001f1f7',  # 🇧🇷
    'us':        '\U0001f1fa\U0001f1f8',  # 🇺🇸
}

THEATRE_DISPLAY = {
    'cuba':      'CUBA',
    'peru':      'PERU',
    'venezuela': 'VENEZUELA',
    'haiti':     'HAITI',
    'mexico':    'MEXICO',
    'panama':    'PANAMA',
    'colombia':  'COLOMBIA',
    'brazil':    'BRAZIL',
    'us':        'UNITED STATES',
}

# Top-N signals emitted to GPI (matches ME / Asia pattern)
TOP_SIGNALS_COUNT = 5

# Our synthesis cache
BLUF_CACHE_KEY    = 'rhetoric:wha:regional_bluf'
BLUF_CACHE_TTL    = 14 * 3600    # 14h -- outlasts any individual tracker TTL


# ============================================================
# ESCALATION + INFLUENCE LABELS (canonical across all regional BLUFs)
# ============================================================
ESCALATION_LABELS = {
    0: 'Monitoring',
    1: 'Rhetoric',
    2: 'Warning',
    3: 'Direct Threat',
    4: 'Incident',
    5: 'Active Conflict',
}

ESCALATION_COLORS = {
    0: '#6b7280',
    1: '#3b82f6',
    2: '#f59e0b',
    3: '#f97316',
    4: '#ef4444',
    5: '#dc2626',
}

# Forward-compat for future stability anchors (e.g., possible US dual-axis)
INFLUENCE_LABELS = {
    0: 'Standby',
    1: 'Engaged',
    2: 'Active',
    3: 'Mediation Engaged',
    4: 'High-Stakes Mediation',
    5: 'Crisis Mediation',
}

INFLUENCE_COLORS = {
    0: '#6b7280',
    1: '#a78bfa',
    2: '#8b5cf6',
    3: '#7c3aed',
    4: '#6d28d9',
    5: '#5b21b6',
}


# ============================================================
# REDIS HELPERS
# ============================================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5
        )
        result = resp.json().get('result')
        return json.loads(result) if result else None
    except Exception as e:
        print(f'[WHA BLUF] Redis GET error ({key}): {e}')
        return None


def _redis_set(key, value, ttl=BLUF_CACHE_TTL):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str)
        params = {'EX': ttl} if ttl else {}
        resp = requests.post(
            f'{UPSTASH_REDIS_URL}/set/{key}',
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json'
            },
            data=payload,
            params=params,
            timeout=5
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f'[WHA BLUF] Redis SET error ({key}): {e}')
        return False


# ============================================================
# SAFE-ACCESS HELPERS (defensive)
# ============================================================
def _safe_dict(val):
    return val if isinstance(val, dict) else {}

def _safe_list(val):
    return val if isinstance(val, list) else []

def _safe_int(val, default=0):
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def _safe_str(val, default=''):
    return str(val) if val is not None else default


# ============================================================
# COMPATIBILITY SHIM -- v1.0 (mirrors ME / Asia v2.0+ pattern)
# ============================================================
def _normalize_tracker_data(theatre, raw_data):
    """
    Convert raw tracker cache into canonical shape regardless of version.
    """
    if not raw_data:
        return None

    flag = THEATRE_FLAGS.get(theatre, '')
    so_what    = _safe_dict(raw_data.get('so_what'))
    red_lines  = _safe_list(raw_data.get('red_lines'))

    # ---- THREAT LEVEL (Cuba uses 'theatre_level'; future trackers may differ) ----
    threat = _safe_int(raw_data.get('theatre_level',
                       raw_data.get('overall_level',
                       raw_data.get('threat_level', 0))))

    # ---- SCORE ----
    # Most trackers emit theatre_score (0-100); level-based trackers (e.g. Cuba's
    # 3-vector model) only emit theatre_level (0-5). Derive a 0-100 proxy by
    # multiplying level × 20 so the regional dashboard always has a usable score.
    score = _safe_int(raw_data.get('theatre_score',
                      raw_data.get('rhetoric_score',
                      raw_data.get('overall_score', 0))))
    if score == 0 and threat:
        score = int(threat) * 20

    # ---- INFLUENCE LEVEL (forward-ready; no current WHA tracker uses this) ----
    influence = raw_data.get('influence_level')

    # ---- DOMINANT AXIS ----
    threat_int    = int(threat or 0)
    influence_int = int(influence or 0)
    dominant_level = max(threat_int, influence_int)
    dominant_axis  = 'influence' if influence_int > threat_int else 'threat'

    # ---- TOP SIGNALS (v2.0+ self-emitted if present; else synthesize) ----
    if 'top_signals' in raw_data and isinstance(raw_data['top_signals'], list):
        top_signals = list(raw_data['top_signals'])
    else:
        top_signals = _synthesize_top_signals_legacy(
            theatre, raw_data, threat_int, score, so_what, red_lines
        )

    # ALWAYS augment with BLUF-level diplomatic signals (v3.2.0 — mirrors ME pattern).
    # WHA expansion roadmap: Venezuela has active diplomatic vectors (Maduro-opposition
    # talks, Norway/Mexico mediation, US sanctions negotiations). Cuba may eventually
    # have US re-engagement signals. This helper is forward-compatible — no-op when
    # trackers don't emit diplomatic_track yet, but new tracker emissions automatically
    # surface to GPI's diplomatic axis.
    diplomatic_sigs = _extract_diplomatic_signals(theatre, raw_data, threat_int)
    existing_categories = {s.get('category') for s in top_signals}
    for ds in diplomatic_sigs:
        if ds.get('category') not in existing_categories:
            top_signals.append(ds)

    return {
        'theatre':      theatre,
        'flag':         flag,
        'levels': {
            'threat':         threat_int,
            'influence':      influence_int if influence is not None else None,
            'green':          None,
            'dominant_axis':  dominant_axis,
            'dominant_level': dominant_level,
        },
        'score':        score,
        'so_what':      so_what,
        'red_lines':    red_lines,
        'top_signals':  top_signals,
        'scanned_at':   _safe_str(raw_data.get('scanned_at') or raw_data.get('timestamp', '')),
        'raw':          raw_data,
    }


def _extract_diplomatic_signals(theatre, raw_data, threat_int):
    """
    BLUF-level diplomatic signal extractor (v3.2.0 — mirrors ME pattern).

    Reads diplomatic_track + green_lines from a tracker's interpretation block.
    Forward-compatible no-op when trackers don't emit diplomatic data.

    WHA-specific note: Venezuela trackers (when added) will emit Maduro-opposition
    talks, Norway/Mexico mediation status, US-Venezuela sanctions negotiations.
    Cuba may emit US re-engagement signals. This helper surfaces them automatically.

    Returns list of signal dicts (possibly empty).
    """
    flag    = THEATRE_FLAGS.get(theatre, '')
    display = THEATRE_DISPLAY.get(theatre, theatre.upper())
    interp  = (raw_data.get('interpretation') or {}) if isinstance(raw_data.get('interpretation'), dict) else {}
    signals = []

    # Green lines / diplomatic de-escalation (UNGATED + dual-schema).
    green_lines = interp.get('green_lines') if interp else None
    if green_lines and isinstance(green_lines, dict):
        if 'count' in green_lines:
            gl_count = green_lines.get('count', 0)
        else:
            gl_count = green_lines.get('active_count', 0) + green_lines.get('signaled_count', 0)
        if gl_count >= 1:
            gl_priority = 6 + min(threat_int, 4)
            signals.append({
                'priority':       gl_priority,
                'category':       'green_line_active',
                'theatre':        theatre,
                'level':          min(threat_int, 4),
                'icon':           '✅',
                'color':          '#10b981',
                'pressure_type':  'diplomatic',
                'short_text':     f'{flag} {display}: De-escalation signals ({gl_count})',
                'long_text':      f'{flag} {display}: {gl_count} green-line de-escalation '
                                  f'trigger{"s" if gl_count != 1 else ""} active.',
            })

    # Diplomatic track — Venezuela mediation, Cuba re-engagement, etc.
    diplomatic_track = interp.get('diplomatic_track') if interp else None
    if diplomatic_track and isinstance(diplomatic_track, dict):
        active_count   = diplomatic_track.get('active_count', 0)
        signaled_count = diplomatic_track.get('signaled_count', 0)
        scenario       = diplomatic_track.get('scenario', '')
        score          = diplomatic_track.get('score', 0)
        if active_count + signaled_count > 0:
            dt_priority = 7 + min(threat_int, 4)
            short_status = 'ACTIVE' if active_count > 0 else 'SIGNALED'
            signals.append({
                'priority':       dt_priority,
                'category':       'diplomatic_track_active',
                'theatre':        theatre,
                'level':          min(threat_int, 4),
                'icon':           '🕊️',
                'color':          '#0ea5e9',
                'pressure_type':  'diplomatic',
                'short_text':     f'{flag} {display}: Diplomatic track {short_status} ({scenario[:40]})',
                'long_text':      f'{flag} {display} diplomatic track: {active_count} active + '
                                  f'{signaled_count} signaled off-ramp triggers (score {score}/100). '
                                  f'Scenario: {scenario}.',
                'diplomatic_active_count':   active_count,
                'diplomatic_signaled_count': signaled_count,
                'diplomatic_score':          score,
                'diplomatic_scenario':       scenario,
            })

    return signals


def _synthesize_top_signals_legacy(theatre, raw_data, threat_int, score, so_what, red_lines):
    """
    For trackers not yet upgraded to v2.0+. Synthesize top_signals[] from raw fields.
    """
    flag    = THEATRE_FLAGS.get(theatre, '')
    display = THEATRE_DISPLAY.get(theatre, theatre.upper())
    signals = []

    # Red lines breached
    for rl in red_lines:
        rl = _safe_dict(rl)
        status = _safe_str(rl.get('status'))
        label  = _safe_str(rl.get('label'))
        if status == 'BREACHED':
            signals.append({
                'priority':   12,
                'category':   'red_line_breached',
                'theatre':    theatre,
                'level':      threat_int,
                'icon':       rl.get('icon', '🚨'),
                'color':      '#dc2626',
                'short_text': f'{flag} {display}: BREACH — {label[:55]}',
                'long_text':  f'{flag} {display} red line breached at L{threat_int}: {label}.',
            })
        elif status == 'APPROACHING':
            signals.append({
                'priority':   8,
                'category':   'red_line_approaching',
                'theatre':    theatre,
                'level':      threat_int,
                'icon':       '🟠',
                'color':      '#f97316',
                'short_text': f'{flag} {display}: Approaching — {label[:50]}',
                'long_text':  f'{flag} {display} approaching red line: {label}.',
            })

    # Theatre at high level
    if threat_int >= 4:
        signals.append({
            'priority':   9 + threat_int,
            'category':   'theatre_high',
            'theatre':    theatre,
            'level':      threat_int,
            'icon':       '🔴',
            'color':      ESCALATION_COLORS.get(threat_int, '#6b7280'),
            'short_text': f'{flag} {display} L{threat_int} — {ESCALATION_LABELS.get(threat_int, "")}',
            'long_text':  f'{flag} {display} at L{threat_int} {ESCALATION_LABELS.get(threat_int, "")} (score {score}/100)',
        })

    # CUBA-SPECIFIC vector signals (legacy fallback)
    if theatre == 'cuba':
        us_pressure      = _safe_int(so_what.get('us_pressure'))
        regime_fracture  = _safe_int(so_what.get('regime_fracture'))
        adversary_access = _safe_int(so_what.get('adversary_access'))

        if us_pressure >= 3:
            signals.append({
                'priority':   7 + us_pressure,
                'category':   'us_pressure_high',
                'theatre':    'cuba',
                'level':      us_pressure,
                'icon':       '🦅',
                'color':      '#f97316' if us_pressure < 4 else '#dc2626',
                'short_text': f'{flag} CUBA: U.S. pressure L{us_pressure}',
                'long_text':  f'CUBA U.S. pressure vector L{us_pressure} — sanctions/coercion language elevated.',
            })
        if regime_fracture >= 3:
            signals.append({
                'priority':   7 + regime_fracture,
                'category':   'regime_fracture',
                'theatre':    'cuba',
                'level':      regime_fracture,
                'icon':       '✊',
                'color':      '#f97316' if regime_fracture < 4 else '#dc2626',
                'short_text': f'{flag} CUBA: Regime fracture L{regime_fracture}',
                'long_text':  f'CUBA regime fracture L{regime_fracture} — dissident activity vs. baseline elevated.',
            })
        if adversary_access >= 3:
            signals.append({
                'priority':   8 + adversary_access,
                'category':   'adversary_access',
                'theatre':    'cuba',
                'level':      adversary_access,
                'icon':       '🤝',
                'color':      '#7c3aed' if adversary_access < 4 else '#dc2626',
                'short_text': f'{flag} CUBA: Adversary access L{adversary_access}',
                'long_text':  f'CUBA adversary access L{adversary_access} — RU/CN/IR axis activity detected.',
            })

    # PERU-SPECIFIC vector signals (4-vector frame)
    # Peru emits vector_levels {domestic_stability, resource_sector, us_alignment, china_alignment}
    # Map level strings to integers for BLUF priority math, then surface escalatory vectors.
    if theatre == 'peru':
        VECTOR_LVL_INT = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
        vector_levels  = _safe_dict(raw_data.get('vector_levels'))

        domestic_lvl = VECTOR_LVL_INT.get(vector_levels.get('domestic_stability'), 0)
        resource_lvl = VECTOR_LVL_INT.get(vector_levels.get('resource_sector'),   0)
        us_lvl       = VECTOR_LVL_INT.get(vector_levels.get('us_alignment'),      0)
        china_lvl    = VECTOR_LVL_INT.get(vector_levels.get('china_alignment'),   0)

        if domestic_lvl >= 2:   # elevated+
            signals.append({
                'priority':   7 + domestic_lvl,
                'category':   'peru_domestic_stability',
                'theatre':    'peru',
                'level':      domestic_lvl,
                'icon':       '🏛️',
                'color':      '#f59e0b' if domestic_lvl < 3 else '#dc2626',
                'short_text': f'{flag} PERU: Domestic stability L{domestic_lvl}',
                'long_text':  f'PERU domestic-stability vector L{domestic_lvl} — presidency / FFAA / VRAEM / Las Bambas channels signaling above baseline.',
            })

        if resource_lvl >= 2:
            signals.append({
                'priority':   8 + resource_lvl,   # resource ranks slightly higher (commodity coupling)
                'category':   'peru_resource_sector',
                'theatre':    'peru',
                'level':      resource_lvl,
                'icon':       '⛏️',
                'color':      '#f59e0b' if resource_lvl < 3 else '#dc2626',
                'short_text': f'{flag} PERU: Resource sector L{resource_lvl}',
                'long_text':  f'PERU resource-sector vector L{resource_lvl} — mining-sector + Las Bambas rhetoric coupled to global copper / silver supply.',
            })

        if us_lvl >= 2:
            signals.append({
                'priority':   6 + us_lvl,
                'category':   'peru_us_alignment',
                'theatre':    'peru',
                'level':      us_lvl,
                'icon':       '🦅',
                'color':      '#3b82f6' if us_lvl < 3 else '#dc2626',
                'short_text': f'{flag} PERU: U.S. alignment L{us_lvl}',
                'long_text':  f'PERU U.S.-alignment vector L{us_lvl} — Embassy Lima / INL / SOUTHCOM / FTA channel activity above baseline.',
            })

        if china_lvl >= 2:
            signals.append({
                'priority':   7 + china_lvl,
                'category':   'peru_china_alignment',
                'theatre':    'peru',
                'level':      china_lvl,
                'icon':       '🚢',
                'color':      '#dc2626' if china_lvl >= 3 else '#f59e0b',
                'short_text': f'{flag} PERU: China alignment L{china_lvl}',
                'long_text':  f'PERU China-alignment vector L{china_lvl} — Chancay megaport / BRI / Chinese mining-investment activity above baseline.',
            })

    signals.sort(key=lambda s: s['priority'], reverse=True)
    return signals


# ============================================================
# TRACKER READERS
# ============================================================
def _read_all_trackers():
    """
    Read all WHA tracker caches and normalize via shim.
    Returns dict of theatre -> NORMALIZED data.
    Missing caches are silently skipped.
    """
    trackers = {}
    for theatre, redis_key in TRACKER_KEYS.items():
        raw = _redis_get(redis_key)
        if raw:
            normalized = _normalize_tracker_data(theatre, raw)
            if normalized:
                trackers[theatre] = normalized
                lvls = normalized['levels']
                axis_str = (f"T{lvls['threat']}" +
                            (f"/I{lvls['influence']}" if lvls['influence'] is not None else ''))
                print(f'[WHA BLUF] {theatre}: loaded ({axis_str}, score={normalized["score"]})')
        else:
            print(f'[WHA BLUF] {theatre}: no cache available')
    return trackers


# ============================================================
# REGIONAL POSTURE
# ============================================================
def _determine_regional_posture(trackers):
    """
    Roll up posture across all WHA trackers.
    """
    if not trackers:
        return {
            'label':            'BASELINE',
            'color':            '#6b7280',
            'peak_level':       0,
            'breached_count':   0,
            'theatres_at_l3plus': 0,
        }

    levels = [t['levels']['threat'] for t in trackers.values()]
    max_level = max(levels) if levels else 0

    # Count breached red lines across all trackers
    total_breached = 0
    for data in trackers.values():
        for rl in data.get('red_lines', []) or []:
            if isinstance(rl, dict) and rl.get('status') == 'BREACHED':
                total_breached += 1

    theatres_at_l3plus = sum(1 for l in levels if l >= 3)

    # Posture ladder
    if total_breached >= 2 or max_level >= 5:
        label, color = 'CRITICAL -- MULTI-BREACH OR ACTIVE CONFLICT', '#dc2626'
    elif total_breached >= 1 or max_level >= 4:
        label, color = 'ELEVATED -- RED LINE OR INCIDENT', '#ef4444'
    elif theatres_at_l3plus >= 2:
        label, color = 'ELEVATED -- MULTI-COUNTRY WARNING', '#f97316'
    elif max_level >= 3:
        label, color = 'WARNING -- DIRECT THREAT', '#f59e0b'
    elif max_level >= 2:
        label, color = 'MONITORING -- WARNING', '#fbbf24'
    elif max_level >= 1:
        label, color = 'MONITORING -- RHETORIC', '#3b82f6'
    else:
        label, color = 'BASELINE', '#6b7280'

    return {
        'label':              label,
        'color':              color,
        'peak_level':         max_level,
        'breached_count':     total_breached,
        'theatres_at_l3plus': theatres_at_l3plus,
    }


# ============================================================
# BLUF PROSE
# ============================================================
def _build_bluf_prose(posture, trackers):
    """Generate regional prose paragraph. 2-4 sentences."""
    date_str = datetime.now(timezone.utc).strftime('%b %d, %Y')
    parts = [f"Western Hemisphere Rhetoric Monitor ({date_str}):"]

    n_live = len(trackers)
    parts.append(
        f"Regional posture at {posture['label']} -- peak escalation L{posture['peak_level']} "
        f"across {n_live} live tracker{'s' if n_live != 1 else ''}."
    )

    # Per-tracker callouts (only for elevated theaters)
    for theatre, data in trackers.items():
        threat   = data['levels']['threat']
        so_what  = data.get('so_what', {})
        display  = THEATRE_DISPLAY.get(theatre, theatre.upper())

        if theatre == 'cuba' and threat >= 2:
            us_pressure      = _safe_int(so_what.get('us_pressure'))
            regime_fracture  = _safe_int(so_what.get('regime_fracture'))
            adversary_access = _safe_int(so_what.get('adversary_access'))
            scenario         = _safe_str(so_what.get('scenario'))
            cuba_desc = f"{display} composite L{threat}"
            vector_phrases = []
            if us_pressure >= 3:
                vector_phrases.append(f"U.S. pressure L{us_pressure}")
            if regime_fracture >= 3:
                vector_phrases.append(f"regime fracture L{regime_fracture}")
            if adversary_access >= 3:
                vector_phrases.append(f"adversary axis L{adversary_access}")
            if vector_phrases:
                cuba_desc += " — " + ", ".join(vector_phrases) + "."
            elif scenario:
                cuba_desc += f" — {scenario}."
            else:
                cuba_desc += " — composite pressure elevated."
            parts.append(cuba_desc)
        elif theatre == 'peru' and threat >= 2:
            # Peru uses 4-vector frame: domestic_stability, resource_sector, us_alignment, china_alignment
            VECTOR_LVL_INT = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
            raw           = data.get('raw', {}) or {}
            vector_levels = raw.get('vector_levels', {}) or {}
            domestic_lvl = VECTOR_LVL_INT.get(vector_levels.get('domestic_stability'), 0)
            resource_lvl = VECTOR_LVL_INT.get(vector_levels.get('resource_sector'),   0)
            us_lvl       = VECTOR_LVL_INT.get(vector_levels.get('us_alignment'),      0)
            china_lvl    = VECTOR_LVL_INT.get(vector_levels.get('china_alignment'),   0)

            peru_desc = f"{display} composite L{threat}"
            vector_phrases = []
            if domestic_lvl >= 2:
                vector_phrases.append(f"domestic stability L{domestic_lvl}")
            if resource_lvl >= 2:
                vector_phrases.append(f"resource sector L{resource_lvl}")
            if us_lvl >= 2:
                vector_phrases.append(f"U.S. alignment L{us_lvl}")
            if china_lvl >= 2:
                vector_phrases.append(f"China alignment L{china_lvl}")
            if vector_phrases:
                peru_desc += " — " + ", ".join(vector_phrases) + "."
            else:
                peru_desc += " — composite pressure elevated."
            parts.append(peru_desc)
        elif threat >= 3:
            # Generic treatment for other future trackers
            parts.append(f"{display} L{threat} — {ESCALATION_LABELS.get(threat, 'elevated')}.")

    # Cascade flag
    if posture['theatres_at_l3plus'] >= 2:
        parts.append(
            f"⚠️ {posture['theatres_at_l3plus']} theaters at L3+ simultaneously -- "
            f"WHA cascade risk: migration, sanctions, and adversary access vectors converging."
        )
    elif posture['breached_count'] >= 1:
        parts.append(
            f"{posture['breached_count']} red line(s) breached across WHA trackers -- "
            f"adjacent categories warrant elevated monitoring."
        )

    return ' '.join(parts)


# ============================================================
# TOP SIGNALS COLLECTOR
# ============================================================
def _build_signals(posture, trackers):
    """
    Collect all top_signals[] from normalized trackers, dedupe, return top N.
    Adds WHA-specific cross-tracker signals.
    """
    all_signals = []
    for theatre, data in trackers.items():
        for sig in data.get('top_signals', []):
            sig.setdefault('priority', 5)
            sig.setdefault('category', 'unknown')
            sig.setdefault('theatre', theatre)
            sig.setdefault('icon', '•')
            sig.setdefault('color', '#6b7280')
            sig.setdefault('short_text', '')
            sig.setdefault('long_text', sig.get('short_text', ''))
            all_signals.append(sig)

    # WHA cross-tracker signal: simultaneous multi-country elevation (>=2 at L3+)
    if posture.get('theatres_at_l3plus', 0) >= 2:
        elevated_theatres = [
            t for t, d in trackers.items()
            if d['levels']['threat'] >= 3
        ]
        all_signals.append({
            'priority':   13,
            'category':   'wha_cascade',
            'theatre':    'regional',
            'level':      posture.get('peak_level', 0),
            'icon':       '🌀',
            'color':      '#dc2626',
            'short_text': f'WHA CASCADE: {len(elevated_theatres)} theaters L3+',
            'long_text':  f'WHA cross-country elevation — {", ".join(t.upper() for t in elevated_theatres)} '
                          f'simultaneously at L3+; migration, sanctions, and adversary-access vectors converging.',
        })

    # Global sort
    all_signals.sort(key=lambda x: x.get('priority', 0), reverse=True)

    # Dedupe by (theatre, category)
    seen = set()
    deduped = []
    for s in all_signals:
        key = f'{s.get("theatre", "")}:{s.get("category", "")}'
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    if not deduped:
        deduped.append({
            'priority':   1,
            'category':   'baseline',
            'theatre':    'regional',
            'level':      0,
            'icon':       '🌎',
            'color':      '#6b7280',
            'short_text': 'WHA at baseline',
            'long_text':  'All Western Hemisphere theaters at baseline — monitoring for cascade triggers.',
        })

    return deduped     # v2.3.0: full deduped pool (caller caps for display)


# ============================================================
# MAIN BUILD FUNCTION
# ============================================================
def build_regional_bluf(force=False):
    """
    Build the WHA regional BLUF. Reads all WHA caches, synthesizes,
    caches result in Redis. Returns dict.
    Cache check is inside this function (matches ME / Asia pattern).
    """
    if not force:
        cached = _redis_get(BLUF_CACHE_KEY)
        if cached and cached.get('generated_at'):
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(cached['generated_at'])).total_seconds()
                if age < BLUF_CACHE_TTL:
                    cached['from_cache'] = True
                    return cached
            except Exception:
                pass

    print('[WHA BLUF v1.0] Building regional BLUF from all WHA tracker caches...')

    try:
        trackers = _read_all_trackers()

        if not trackers:
            return {
                'success': False,
                'error':   'No tracker data available',
                'bluf':    'BLUF unavailable -- no WHA tracker caches loaded.',
                'signals': [],
                'top_signals': [],
                'posture_label': 'UNAVAILABLE',
                'posture_color': '#6b7280',
            }

        posture     = _determine_regional_posture(trackers)
        bluf        = _build_bluf_prose(posture, trackers)
        all_signals = _build_signals(posture, trackers)            # v2.3.0: full pool — for GPI axis aggregation
        top_signals = all_signals[:TOP_SIGNALS_COUNT]                # v2.3.0: capped for display

        trackers_live = len(trackers)

        # Per-theatre summary (canonical)
        theatre_summary = {}
        for t, data in trackers.items():
            lvls       = data.get('levels', {})
            threat_lvl = lvls.get('threat', 0)
            infl_lvl   = lvls.get('influence')
            theatre_summary[t] = {
                'level':            threat_lvl,
                'label':            ESCALATION_LABELS.get(threat_lvl, 'Unknown'),
                'color':            ESCALATION_COLORS.get(threat_lvl, '#6b7280'),
                'score':            data.get('score', 0),
                'flag':             data.get('flag', THEATRE_FLAGS.get(t, '')),
                'timestamp':        data.get('scanned_at', ''),
                'threat_level':     threat_lvl,
                'influence_level':  infl_lvl,
                'green_level':      lvls.get('green'),
                'dominant_axis':    lvls.get('dominant_axis', 'threat'),
                'dominant_level':   lvls.get('dominant_level', threat_lvl),
                'is_dual_axis':     infl_lvl is not None,
                'influence_label':  INFLUENCE_LABELS.get(infl_lvl, '') if infl_lvl is not None else None,
                'influence_color':  INFLUENCE_COLORS.get(infl_lvl, '#6b7280') if infl_lvl is not None else None,
            }

        scores = [t.get('score', 0) for t in theatre_summary.values()]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        result = {
            'success':            True,
            'from_cache':         False,
            'bluf':               bluf,
            'signals':            all_signals,                # v2.3.0: FULL signal pool — for GPI axis aggregation
            'top_signals':        top_signals,                # v2.3.0: capped — for display + prose synthesis
            'posture_label':      posture['label'],
            'posture_color':      posture['color'],
            'peak_level':         posture['peak_level'],      # legacy alias
            'max_level':          posture['peak_level'],      # canonical
            'avg_score':          avg_score,
            'red_lines_breached': posture['breached_count'],
            'trackers_live':      trackers_live,
            'theatres_live':      trackers_live,              # canonical alias
            'theatres_at_l3plus': posture['theatres_at_l3plus'],
            'trackers_total':     len(TRACKER_KEYS),
            'theatre_summary':    theatre_summary,
            'generated_at':       datetime.now(timezone.utc).isoformat(),
            'version':            '1.0.0',
            'region':             'western_hemisphere',
            'top_signals_count':  len(top_signals),
        }

        _redis_set(BLUF_CACHE_KEY, result)
        print(f"[WHA BLUF v1.0] Built: posture={posture['label']}, "
              f"max_level=L{posture['peak_level']}, "
              f"breached={posture['breached_count']}, "
              f"signals={len(top_signals)}, "
              f"theaters_live={trackers_live}")
        return result

    except Exception as e:
        print(f"[WHA BLUF] SYNTHESIS EXCEPTION: {e}")
        print(f"[WHA BLUF] Traceback follows:")
        print(traceback.format_exc())
        return {
            'success': False,
            'error':   f'{type(e).__name__}: {str(e)[:300]}',
            'bluf':    'BLUF synthesis failed -- check backend logs for traceback.',
            'signals': [],
            'top_signals': [],
            'posture_label': 'ERROR',
            'posture_color': '#6b7280',
        }


# ============================================================
# ROUTE REGISTRATION
# ============================================================
def register_wha_bluf_routes(app):
    """Register WHA BLUF endpoints on the given Flask app."""
    from flask import jsonify, request as flask_request

    @app.route('/api/rhetoric/wha/bluf', methods=['GET'])
    def get_wha_bluf():
        force = flask_request.args.get('force', 'false').lower() == 'true'
        result = build_regional_bluf(force=force)
        return jsonify(result)

    @app.route('/api/rhetoric/wha/bluf/debug', methods=['GET'])
    def get_wha_bluf_debug():
        """Direct Redis cache inspection -- for triage."""
        cached = _redis_get(BLUF_CACHE_KEY)
        return jsonify({
            'cache_present':  cached is not None,
            'cache_data':     cached,
        })

    print('[WHA BLUF] Routes registered: /api/rhetoric/wha/bluf, /bluf/debug')


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    print("WHA Regional BLUF Engine -- standalone test")
    print("(Requires Redis env vars to actually read tracker caches)")
    print()
    result = build_regional_bluf(force=True)
    print('BLUF:')
    print(result.get('bluf', '(no BLUF)'))
    print()
    print('TOP SIGNALS:')
    for s in result.get('top_signals', []):
        print(f'  {s.get("icon", "•")} {s.get("short_text", "")}')
    print()
    print(f'POSTURE: {result.get("posture_label", "")}')
    print(f'MAX LEVEL: L{result.get("max_level", 0)}')
    print(f'TRACKERS LIVE: {result.get("trackers_live", 0)}/{result.get("trackers_total", 0)}')
