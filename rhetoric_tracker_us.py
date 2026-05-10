"""
========================================
U.S. RHETORIC TRACKER (v1.0.0)
========================================
Multi-actor rhetoric monitoring for the United States — the only tracker
in the Asifah corpus where every other tracker reads from us, and we read
from every other tracker.

CALIBRATION PHILOSOPHY (per Rachel + Peter, May 2026):
  Score reflects RHETORIC VOLATILITY and CROSS-SPECTRUM FRACTURE, not
  aggression. The US is generally on the upper edge of stable. View from
  Foggy Bottom feels more volatile than view from Iowa, and the score
  reflects the median American experience, not DC pundit experience.

  0-25:  STABLE      Coherent posture, low partisan divergence, allies aligned
  26-50: ACTIVE      Assertive posture, normal disagreement, manageable
  51-75: VOLATILE    Sharp divergence, allies distancing, branches contradicting
  76-100: CRISIS     Branches openly fighting, allies breaking publicly,
                     multiple foreign actors targeting US directly

ACTORS (9):

  EXECUTIVE LAYER (3)
  ─────────────────────────
  us_executive          Trump + WH press + cabinet (weight 1.2 — primary)
  us_state_dept         Diplomatic posture (weight 1.0)
  us_defense            Pentagon / CENTCOM / SOCOM / NORTHCOM (weight 1.0)

  LEGISLATIVE LAYER (2)
  ─────────────────────────
  us_congress_majority    House R + Senate leadership (weight 0.95)
  us_congress_opposition  Dem leadership + opposition voices (weight 0.95)

  INSTITUTIONAL LAYER (4)
  ─────────────────────────
  us_judicial           SCOTUS + DOJ + courts (weight 1.05)
  us_dhs_ice            DHS + ICE + immigration enforcement (weight 1.1) ⭐
  us_federal_reserve    Powell + FOMC statements (weight 0.85)
  us_states             Governors pushing back on federal posture (weight 0.85)

CROSS-THEATER ARCHITECTURE:
  - READS fingerprints from: ALL trackers (ME 6, Asia 4, Europe 4, WHA 6+)
  - WRITES fingerprint: us_active, us_outbound_targets[], us_executive_volatility,
                        us_dhs_enforcement_active, us_branch_divergence_score,
                        us_domestic_fracture_score, us_taco_index_v0 (placeholder)

REDIS KEYS WRITTEN:
  rhetoric:us:latest         (current scan results, no TTL)
  rhetoric:us:summary        (compact summary for dashboards)
  rhetoric:us:history        (last 12 weeks, snapshot index pattern)
  fingerprint:us:current     (cross-theater fingerprint contract)

ENDPOINTS REGISTERED:
  GET /api/rhetoric/us
  GET /api/rhetoric/us/debug
"""

import os
import json
import time
import threading
import requests
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta


# ════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════

print("[US Rhetoric] Module loading...")

SCAN_INTERVAL_HOURS    = 12
INITIAL_BOOT_DELAY_SEC = 90
GDELT_TIMEOUT_SEC      = 8
RSS_TIMEOUT_SEC        = 12
NEWSAPI_TIMEOUT_SEC    = 10
DEFAULT_MAX_ARTICLES   = 25

# Defensive: support both env var naming conventions used across Asifah trackers.
# Peru/Chile use UPSTASH_REDIS_URL; some docs reference UPSTASH_REDIS_REST_URL.
# Try both so the tracker works regardless of which one is configured on Render.
UPSTASH_URL   = os.environ.get('UPSTASH_REDIS_URL', '') or os.environ.get('UPSTASH_REDIS_REST_URL', '')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '') or os.environ.get('UPSTASH_REDIS_REST_TOKEN', '')
NEWSAPI_KEY   = os.environ.get('NEWSAPI_KEY', '')
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY', '')

REDIS_AVAILABLE  = bool(UPSTASH_URL and UPSTASH_TOKEN)
NEWSAPI_AVAILABLE = bool(NEWSAPI_KEY)
BRAVE_AVAILABLE  = bool(BRAVE_API_KEY)

# Diagnostic logging — show which env vars resolved at module load
print(f"[US Rhetoric] Redis available: {REDIS_AVAILABLE} (URL len={len(UPSTASH_URL)}, TOKEN len={len(UPSTASH_TOKEN)})")
print(f"[US Rhetoric] NewsAPI available: {NEWSAPI_AVAILABLE} (key len={len(NEWSAPI_KEY)})")
print(f"[US Rhetoric] Brave available: {BRAVE_AVAILABLE} (key len={len(BRAVE_API_KEY)})")

# Show first 30 chars of URL so we can verify we got the right one (without
# leaking the token). This helps catch env var typos.
if UPSTASH_URL:
    print(f"[US Rhetoric] Redis URL prefix: {UPSTASH_URL[:30]}...")
if NEWSAPI_KEY:
    print(f"[US Rhetoric] NewsAPI key prefix: {NEWSAPI_KEY[:8]}... (suffix: ...{NEWSAPI_KEY[-4:]})")

# ── Social signal modules (graceful degradation) ──
try:
    from bluesky_signals_wha import fetch_bluesky_for_target
    BLUESKY_AVAILABLE = True
    print("[US Rhetoric] ✅ Bluesky module loaded")
except ImportError as e:
    BLUESKY_AVAILABLE = False
    print(f"[US Rhetoric] ⚠️ Bluesky unavailable ({e})")

try:
    from telegram_signals_wha import fetch_telegram_signals_us
    TELEGRAM_AVAILABLE = True
    print("[US Rhetoric] ✅ Telegram module loaded")
except ImportError as e:
    TELEGRAM_AVAILABLE = False
    print(f"[US Rhetoric] ⚠️ Telegram unavailable ({e})")

try:
    from reddit_signals_us import fetch_reddit_signals_us
    REDDIT_AVAILABLE = True
    print("[US Rhetoric] ✅ Reddit module loaded")
except ImportError as e:
    REDDIT_AVAILABLE = False
    print(f"[US Rhetoric] ⚠️ Reddit unavailable ({e})")

try:
    from us_signal_interpreter import (
        compute_top_signals,
        compute_so_what_factor,
        compute_branch_divergence_score,
        compute_domestic_fracture_score,
    )
    INTERPRETER_AVAILABLE = True
    print("[US Rhetoric] ✅ Signal interpreter loaded")
except ImportError as e:
    INTERPRETER_AVAILABLE = False
    print(f"[US Rhetoric] ⚠️ Signal interpreter unavailable ({e})")


# ════════════════════════════════════════════════════════════════════
# THE 9-ACTOR MATRIX
# ════════════════════════════════════════════════════════════════════
# Each actor entry contains:
#   name, flag, icon, color, role, description (display)
#   keywords (case-insensitive substring matches in title+description)
#   baseline_statements_per_week (calibration baseline)
#   tripwires (high-severity signal phrases that auto-elevate the actor's tier)
#   weight (signal contribution multiplier)
#   layer (executive | legislative | institutional)
# ════════════════════════════════════════════════════════════════════

ACTORS = {

    # ════════════════════════════════════════════════════════════════
    # EXECUTIVE LAYER (3 actors)
    # ════════════════════════════════════════════════════════════════

    'us_executive': {
        'name':  'U.S. Executive Branch',
        'flag':  '🇺🇸',
        'icon':  '🏛️',
        'color': '#dc2626',
        'role':  'White House / Trump / Cabinet -- Primary Political Rhetoric',
        'layer': 'executive',
        'weight': 1.2,
        'description': (
            'Presidential and White House rhetoric. Highest weight because executive '
            'rhetoric drives headline cycles, market moves, and cross-theater rhetoric. '
            'Watch for: Truth Social posts, WH press briefings, cabinet statements, '
            'EO announcements, Rose Garden speeches.'
        ),
        'keywords': [
            'trump statement', 'trump announces', 'trump declares', 'trump warns',
            'trump truth social', 'trump truth post', 'truth social post',
            'white house statement', 'white house announces', 'wh press secretary',
            'press briefing', 'oval office', 'cabinet meeting', 'cabinet statement',
            'president signs', 'president announces', 'executive order signed',
            'rose garden', 'air force one', 'wh briefing room',
            'trump rally', 'trump speech', 'trump remarks',
            # Cabinet
            'rubio statement', 'secretary rubio', 'hegseth statement',
            'noem statement', 'secretary noem', 'kennedy hhs statement',
            'lutnick commerce', 'bessent treasury',
            # Spanish (for ES tab)
            'declaración trump', 'casa blanca declara', 'comunicado casa blanca',
        ],
        'tripwires': [
            'trump invokes insurrection act', 'trump declares national emergency',
            'trump threatens military', 'trump fires cabinet',
            'wh threatens', 'trump withdraws', 'trump terminates',
            'trump declares war', 'trump activates national guard',
        ],
        'baseline_statements_per_week': 50,
    },

    'us_state_dept': {
        'name':  'U.S. State Department',
        'flag':  '🇺🇸',
        'icon':  '🌐',
        'color': '#2563eb',
        'role':  'Diplomatic Posture / Foggy Bottom',
        'layer': 'executive',
        'weight': 1.0,
        'description': (
            'State Department official statements, briefings, ambassador postings, '
            'and treaty/agreement language. Indicator of allied alignment vs friction. '
            'Watch for: Spokesperson briefings, public statements on foreign policy, '
            'ambassador recall language, treaty withdrawal signals.'
        ),
        'keywords': [
            'state department briefing', 'state department spokesperson',
            'state department announces', 'state department condemns',
            'state department statement', 'foggy bottom',
            'us ambassador', 'us embassy', 'us chief of mission',
            'us recalls ambassador', 'us expels diplomat',
            'state dept human rights', 'state dept democracy',
            'us treaty', 'us withdraws from treaty', 'us suspends agreement',
            'us sanctions waiver', 'us travel advisory',
            'briefing at state department', 'matt miller', 'tammy bruce',
            # Spanish
            'departamento de estado', 'secretario de estado',
        ],
        'tripwires': [
            'us recalls ambassador', 'us closes embassy', 'us expels diplomat',
            'us breaks diplomatic relations', 'us terminates treaty',
            'state dept resignation', 'mass resignation state dept',
        ],
        'baseline_statements_per_week': 30,
    },

    'us_defense': {
        'name':  'U.S. Department of Defense',
        'flag':  '🇺🇸',
        'icon':  '🪖',
        'color': '#475569',
        'role':  'Pentagon / Combatant Commands / Military Posture Rhetoric',
        'layer': 'executive',
        'weight': 1.0,
        'description': (
            'Pentagon, CENTCOM, NORTHCOM, SOCOM, INDOPACOM rhetoric and posture '
            'announcements. Distinct from Asifah Military Tracker (which counts ships) — '
            'this captures the LANGUAGE of force projection. Watch for: deployment '
            'announcements, posture changes, exercises, NDAA disputes, Joint Chiefs '
            'public statements.'
        ),
        'keywords': [
            'pentagon statement', 'pentagon announces', 'pentagon press briefing',
            'sec def hegseth', 'secretary hegseth', 'defense secretary',
            'centcom announces', 'northcom announces', 'socom statement',
            'indopacom', 'eucom', 'africom',
            'joint chiefs', 'chairman joint chiefs',
            'us military deployment', 'us troops deploy', 'us forces deploy',
            'carrier strike group', 'aircraft carrier deploys',
            'us military exercise', 'us forces exercise',
            'pentagon press secretary', 'singh pentagon',
            'us troop posture', 'us force posture review',
            'ndaa', 'defense authorization',
        ],
        'tripwires': [
            'us troops to', 'carrier deploys', 'pentagon escalates',
            'centcom escalates', 'us forces engage',
            'pentagon issues warning', 'us military strike',
            'us forces respond',
        ],
        'baseline_statements_per_week': 25,
    },

    # ════════════════════════════════════════════════════════════════
    # LEGISLATIVE LAYER (2 actors)
    # ════════════════════════════════════════════════════════════════

    'us_congress_majority': {
        'name':  'Congress — Majority',
        'flag':  '🇺🇸',
        'icon':  '🏛️',
        'color': '#b91c1c',
        'role':  'House R Majority + Senate Leadership Rhetoric',
        'layer': 'legislative',
        'weight': 0.95,
        'description': (
            'House Republican majority + Senate leadership rhetoric. Captures legislative '
            'agenda statements, leadership press conferences, committee chair statements, '
            'and majority-coordinated messaging.'
        ),
        'keywords': [
            'speaker johnson', 'speaker mike johnson', 'house speaker',
            'house republican', 'house gop', 'gop leadership',
            'senate majority leader', 'senate leadership',
            'senator thune', 'leader thune', 'senate gop',
            'house majority leader', 'majority whip',
            'committee chair', 'house chair', 'senate chair',
            'gop press conference', 'republican leadership',
            'house republicans pass', 'gop bill',
            'congressional republicans', 'gop senators',
            # Specific committee chairs
            'jim jordan', 'mark green homeland', 'mike rogers armed services',
        ],
        'tripwires': [
            'house gop blocks', 'house impeaches', 'gop impeachment',
            'gop senators break', 'gop revolt',
            'speaker resigns', 'speaker ousted',
            'gop leadership crisis',
        ],
        'baseline_statements_per_week': 35,
    },

    'us_congress_opposition': {
        'name':  'Congress — Opposition',
        'flag':  '🇺🇸',
        'icon':  '🏛️',
        'color': '#1d4ed8',
        'role':  'House Dem Minority + Senate Dem + Opposition Rhetoric',
        'layer': 'legislative',
        'weight': 0.95,
        'description': (
            'House Democratic minority + Senate Democrats + opposition voices. Critical '
            'for measuring cross-spectrum rhetoric divergence. Captures opposition press '
            'conferences, ranking member statements, dissent on EOs, oversight rhetoric.'
        ),
        'keywords': [
            'minority leader jeffries', 'hakeem jeffries', 'rep jeffries',
            'house democrat', 'house dems', 'house minority',
            'senate minority leader', 'senate democrats',
            'schumer statement', 'senator schumer',
            'congressional democrats', 'dem leadership',
            'house dems oppose', 'dems block', 'dems push back',
            'ranking member', 'oversight democrats',
            'progressive caucus', 'house progressives',
            'rep aoc', 'aoc statement', 'rep ocasio-cortez',
            'sen warren', 'sen sanders', 'sen warnock',
            'sen booker', 'sen padilla', 'sen ossoff',
            # Opposition-aligned
            'lincoln project', 'never trump',
        ],
        'tripwires': [
            'dems file impeachment', 'dems walk out',
            'mass dem resignation', 'opposition demands resignation',
            'dems file articles', 'house dems sue',
            'dems block confirmation',
        ],
        'baseline_statements_per_week': 35,
    },

    # ════════════════════════════════════════════════════════════════
    # INSTITUTIONAL LAYER (4 actors)
    # ════════════════════════════════════════════════════════════════

    'us_judicial': {
        'name':  'U.S. Judicial Branch',
        'flag':  '🇺🇸',
        'icon':  '⚖️',
        'color': '#7c2d12',
        'role':  'SCOTUS / Federal Courts / DOJ Rhetoric',
        'layer': 'institutional',
        'weight': 1.05,
        'description': (
            'SCOTUS opinions, federal court rulings on EOs, DOJ statements, and judicial '
            'rhetoric. Critical for institutional pushback signal. Watch for: SCOTUS '
            'rulings, lower court injunctions on EOs, DOJ press conferences, recusal/'
            'resignation language, contempt findings.'
        ),
        'keywords': [
            'supreme court ruling', 'scotus ruling', 'scotus decision',
            'supreme court strikes down', 'supreme court upholds',
            'chief justice roberts', 'justice sotomayor', 'justice kagan',
            'justice jackson', 'justice barrett', 'justice kavanaugh',
            'justice thomas', 'justice alito', 'justice gorsuch',
            'federal judge rules', 'federal court rules',
            'district court rules', 'circuit court rules',
            'dc circuit ruling', 'fifth circuit ruling', 'ninth circuit ruling',
            'court blocks executive order', 'court strikes down eo',
            'court issues injunction', 'court denies stay',
            'doj statement', 'attorney general statement',
            'department of justice', 'us attorney',
            'doj indicts', 'doj investigation', 'doj prosecution',
            'fbi director', 'fbi statement',
            'judge issues contempt', 'court orders compliance',
        ],
        'tripwires': [
            'scotus blocks executive order', 'court orders president',
            'court holds in contempt', 'court issues nationwide injunction',
            'doj resignation', 'mass doj resignation',
            'court orders troops withdrawn', 'judicial defiance',
            'scotus rules against', 'supreme court overturns',
        ],
        'baseline_statements_per_week': 25,
    },

    # ⭐ NEW: DHS / ICE — highest-volatility domestic vector
    'us_dhs_ice': {
        'name':  'DHS / ICE / Immigration Enforcement',
        'flag':  '🇺🇸',
        'icon':  '🚨',
        'color': '#c2410c',
        'role':  'Immigration Enforcement Rhetoric & Civil Unrest Driver',
        'layer': 'institutional',
        'weight': 1.1,
        'description': (
            'DHS Secretary, ICE Director, CBP, and immigration enforcement rhetoric. '
            'Currently the highest-volatility domestic signal vector and a leading '
            'indicator for protests + civil unrest + midterm voter mobilization. '
            'Note: operational tempo currently low due to partial shutdown / DHS budget '
            'constraints, but rhetoric remains active. Watch for: ICE raids announcements, '
            'mass deportation language, sanctuary city rhetoric, CBP enforcement actions, '
            'DHS funding clips.'
        ),
        'keywords': [
            'ice raid', 'ice raids', 'ice enforcement', 'ice operation',
            'ice arrests', 'ice detention', 'ice deportation',
            'mass deportation', 'mass roundup',
            'dhs announces', 'dhs secretary noem', 'dhs statement',
            'cbp announces', 'border patrol', 'border enforcement',
            'sanctuary city', 'sanctuary jurisdiction',
            'immigration enforcement', 'immigration raid',
            'workplace raid', 'workplace enforcement',
            'tom homan', 'border czar homan', 'homan statement',
            'ice acting director', 'ice director',
            'family separation', 'detention center',
            'asylum seekers', 'border crossing',
            'immigration crackdown', 'immigrant communities',
            'protest ice', 'ice protest', 'anti-ice protest',
            'sanctuary protest', 'immigrant rights protest',
            'dhs funding', 'dhs shutdown', 'ice budget',
            # Spanish
            'ice redada', 'redadas migratorias', 'deportación masiva',
            'agentes de migración', 'migra',
        ],
        'tripwires': [
            'mass ice raids', 'ice raids reported',
            'ice deploys troops', 'national guard ice',
            'ice kills', 'ice shoots', 'ice fatal',
            'ice raid sparks protests', 'ice riots',
            'mass deportation begins', 'deportation flights',
            'sanctuary city defies', 'governor blocks ice',
            'troops deployed enforce immigration',
        ],
        'baseline_statements_per_week': 40,
    },

    'us_federal_reserve': {
        'name':  'Federal Reserve',
        'flag':  '🇺🇸',
        'icon':  '💵',
        'color': '#059669',
        'role':  'Powell + FOMC -- Markets-Stability Rhetoric',
        'layer': 'institutional',
        'weight': 0.85,
        'description': (
            'Fed Chair Powell, FOMC statements, and Federal Reserve regional bank '
            'commentary. Distinct economic-stability signal because Fed independence '
            'rhetoric (vs executive pressure to cut rates) is a key institutional '
            'integrity indicator. Watch for: FOMC press conferences, dissent in FOMC '
            'votes, Powell-Trump rhetoric, regional Fed statements.'
        ),
        'keywords': [
            'fed chair powell', 'powell statement', 'jerome powell',
            'fomc statement', 'fomc decision', 'fomc minutes',
            'federal reserve announces', 'fed rate decision',
            'fed press conference', 'fed governors',
            'st louis fed', 'new york fed', 'kansas city fed',
            'fed independence', 'fed pressure',
            'trump powell', 'trump fed', 'wh pressures fed',
            'powell defends fed', 'fed dissent vote',
            'fed minutes show', 'fomc minutes',
            'rate cut', 'rate hike', 'rate hold',
            'beige book', 'fed beige book',
        ],
        'tripwires': [
            'powell resigns', 'fed chair fired', 'trump fires powell',
            'fed independence threatened', 'fomc mass dissent',
            'fed governor resigns', 'emergency fomc meeting',
            'fed cuts emergency rate',
        ],
        'baseline_statements_per_week': 8,
    },

    'us_states': {
        'name':  'State Governors',
        'flag':  '🇺🇸',
        'icon':  '🗺️',
        'color': '#7c3aed',
        'role':  'State Pushback / Federalism Rhetoric',
        'layer': 'institutional',
        'weight': 0.85,
        'description': (
            'Major state governors (CA, TX, FL, NY, IL, WA, etc.) when they push back '
            'on federal posture or align with federal policy. Federalism-tension '
            'indicator. Watch for: governor lawsuits against federal actions, sanctuary '
            'state declarations, state national guard deployment disputes, governor-vs-'
            'WH rhetoric.'
        ),
        'keywords': [
            'governor newsom', 'governor abbott', 'governor desantis',
            'governor hochul', 'governor pritzker', 'governor inslee',
            'governor whitmer', 'governor youngkin', 'governor shapiro',
            'governor lee tennessee', 'governor murphy', 'governor walz',
            'state attorney general', 'state ag sues',
            'state files lawsuit', 'state sues federal',
            'state national guard', 'governor federalize',
            'sanctuary state', 'sanctuary declaration',
            'state vs federal', 'governor pushes back',
            'red state blue state', 'governor defies',
            'state of the state',
            'governors association', 'national governors',
        ],
        'tripwires': [
            'governor refuses federal', 'governor defies federal',
            'state national guard refuses',
            'state secedes', 'state nullifies',
            'governor invokes states rights',
            'state files supreme court',
        ],
        'baseline_statements_per_week': 20,
    },
}


# Layer ordering for frontend display
LAYER_ORDER = ['executive', 'legislative', 'institutional']

# Convenience: list of actor keys in display order (executive first, then legislative, then institutional)
ACTOR_DISPLAY_ORDER = [
    'us_executive', 'us_state_dept', 'us_defense',
    'us_congress_majority', 'us_congress_opposition',
    'us_judicial', 'us_dhs_ice', 'us_federal_reserve', 'us_states',
]


# ════════════════════════════════════════════════════════════════════
# RSS FEEDS — per-actor + general US politics
# ════════════════════════════════════════════════════════════════════
# Browser UA already used in _fetch_rss to bypass bot blocks
# ════════════════════════════════════════════════════════════════════

US_RHETORIC_RSS = [
    # ── General politics / news ──
    ('NYT Politics',     'https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml',   'eng', 1.0),
    ('NYT US',           'https://rss.nytimes.com/services/xml/rss/nyt/US.xml',         'eng', 1.0),
    ('NPR National',     'https://feeds.npr.org/1003/rss.xml',                          'eng', 1.0),
    ('The Hill',         'https://thehill.com/news/feed/',                              'eng', 0.95),
    ('Politico (via Google News)', 'https://news.google.com/rss/search?q=site%3Apolitico.com&hl=en-US&gl=US&ceid=US:en', 'eng', 0.9),
    ('Axios',            'https://api.axios.com/feed/',                                  'eng', 0.95),
    ('CNN Politics',     'http://rss.cnn.com/rss/cnn_allpolitics.rss',                  'eng', 0.9),
    ('PBS NewsHour',     'https://www.pbs.org/newshour/feeds/rss/headlines',            'eng', 0.95),
    ('ProPublica',       'https://www.propublica.org/feeds/propublica/main',            'eng', 0.95),
    ('WaPo Politics',    'https://feeds.washingtonpost.com/rss/politics',               'eng', 1.0),
    ('Atlantic Politics','https://www.theatlantic.com/feed/channel/politics/',          'eng', 0.9),
    ('AP US (via Google News)', 'https://news.google.com/rss/search?q=site%3Aapnews.com+politics&hl=en-US&gl=US&ceid=US:en', 'eng', 1.0),

    # ── Cross-spectrum balance ──
    ('Washington Examiner', 'https://www.washingtonexaminer.com/news/feed',             'eng', 0.85),
    ('National Review',  'https://www.nationalreview.com/feed/',                        'eng', 0.85),
    ('Reason',           'https://reason.com/feed/',                                    'eng', 0.8),

    # ── Legal / institutional ──
    ('Just Security (via Google News)', 'https://news.google.com/rss/search?q=site%3Ajustsecurity.org&hl=en-US&gl=US&ceid=US:en', 'eng', 0.95),
    ('Lawfare (via Google News)', 'https://news.google.com/rss/search?q=site%3Alawfaremedia.org&hl=en-US&gl=US&ceid=US:en', 'eng', 0.95),
    ('SCOTUSblog',       'https://www.scotusblog.com/feed/',                             'eng', 1.0),

    # ── DHS / immigration enforcement specialist ──
    ('DHS/ICE (via Google News)', 'https://news.google.com/rss/search?q=ICE+raid+OR+deportation+OR+%22immigration+enforcement%22&hl=en-US&gl=US&ceid=US:en', 'eng', 1.05),

    # ── Cyber / infrastructure (cross-cutting) ──
    ('CISA Alerts',      'https://www.cisa.gov/news.xml',                                'eng', 0.95),

    # ── Allied foreign view (US-focused) ──
    ('BBC US & Canada',  'https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml',   'eng', 0.95),
    ('Guardian US',      'https://www.theguardian.com/us-news/rss',                     'eng', 0.95),

    # ── Spanish-language US-focused ──
    ('Spanish-language US Politics (via Google News)', 'https://news.google.com/rss/search?q=Estados+Unidos+pol%C3%ADtica+OR+Trump+OR+Casa+Blanca&hl=es-419&gl=US&ceid=US:es-419', 'spa', 0.85),
]


# ════════════════════════════════════════════════════════════════════
# GDELT QUERIES (per-actor + general)
# ════════════════════════════════════════════════════════════════════

GDELT_QUERIES = [
    # General executive rhetoric
    ('"trump statement" OR "trump announces" OR "white house statement"',     'eng', 1.0),
    ('"trump truth social" OR "truth social post"',                            'eng', 1.0),
    # Cabinet
    ('"secretary rubio" OR "state department" OR "rubio statement"',           'eng', 0.95),
    ('"secretary hegseth" OR "pentagon" OR "defense secretary"',               'eng', 0.95),
    ('"secretary noem" OR "dhs secretary" OR "homeland security"',             'eng', 1.0),
    # Legislative
    ('"speaker johnson" OR "house republicans" OR "senate gop"',               'eng', 0.9),
    ('"hakeem jeffries" OR "senate democrats" OR "house democrats"',           'eng', 0.9),
    # Judicial
    ('"supreme court" ruling OR decision OR strikes',                          'eng', 0.95),
    ('"federal judge" rules OR injunction OR blocks',                          'eng', 0.9),
    # ICE / immigration
    ('"ice raids" OR "ice arrests" OR "mass deportation"',                     'eng', 1.05),
    ('"sanctuary city" OR "sanctuary state" OR "immigration enforcement"',     'eng', 1.0),
    # Federal Reserve
    ('"jerome powell" OR "federal reserve" OR "fomc"',                         'eng', 0.85),
    # State pushback
    ('"governor" sues OR defies OR "state attorney general"',                  'eng', 0.85),
    # Spanish
    ('"trump declara" OR "casa blanca"',                                       'spa', 0.85),
    ('"redadas migratorias" OR "deportación masiva"',                          'spa', 0.95),
]


# ════════════════════════════════════════════════════════════════════
# TIER THRESHOLDS (calibration per Rachel May 2026)
# ════════════════════════════════════════════════════════════════════
# Score is volatility/coherence-based (per D4):
#   STABLE    0-25   coherent posture, low partisan divergence
#   ACTIVE    26-50  assertive posture, normal disagreement (current state)
#   VOLATILE  51-75  sharp divergence, branches contradicting
#   CRISIS    76-100 branches openly fighting, allies breaking publicly

TIER_THRESHOLDS = [
    (0,  'L0', 'Stable',     'STABLE',   '🟢', 'Coherent posture, low partisan divergence, allies aligned'),
    (26, 'L1', 'Active',     'ACTIVE',   '🟢', 'Assertive posture, normal disagreement, manageable'),
    (38, 'L2', 'Active+',    'ACTIVE',   '🟡', 'Assertive posture trending volatile'),
    (51, 'L3', 'Volatile',   'VOLATILE', '🟠', 'Sharp partisan divergence, allies distancing'),
    (66, 'L4', 'Volatile+',  'VOLATILE', '🔴', 'Branches contradicting, allies publicly skeptical'),
    (76, 'L5', 'Crisis',     'CRISIS',   '🔴', 'Branches openly fighting, multiple foreign actors targeting US'),
]


def _get_tier(score):
    """Return (tier_level, tier_name, tier_band, icon, description) for a score."""
    selected = TIER_THRESHOLDS[0]
    for entry in TIER_THRESHOLDS:
        if score >= entry[0]:
            selected = entry
    return selected[1], selected[2], selected[3], selected[4], selected[5]


# ════════════════════════════════════════════════════════════════════
# REDIS HELPERS (Upstash REST)
# ════════════════════════════════════════════════════════════════════

def _redis_get(key):
    """Fetch a key from Upstash Redis. Returns parsed JSON or None.

    Now LOUD on infrastructure failure (May 2026): we don't log
    every key-not-found (too noisy) but DO log auth/network errors.
    """
    if not REDIS_AVAILABLE:
        return None
    try:
        url = f"{UPSTASH_URL}/get/{urllib.parse.quote(key, safe='')}"
        resp = requests.get(url, headers={'Authorization': f'Bearer {UPSTASH_TOKEN}'}, timeout=8)
        if resp.status_code != 200:
            print(f"[US Rhetoric] ⚠️ Redis GET HTTP {resp.status_code} for {key}: {resp.text[:200]}")
            return None
        result = resp.json().get('result')
        if result is None:
            return None
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result
    except Exception as e:
        print(f"[US Rhetoric] ❌ Redis GET exception for {key}: {type(e).__name__}: {str(e)[:200]}")
        return None


def _redis_set(key, value, ttl=None):
    """Set a key in Upstash Redis. Returns True on success.

    Now LOUD on failure (May 2026): logs every failure type so we can
    distinguish env var issues, network issues, auth issues, etc.
    """
    if not REDIS_AVAILABLE:
        print(f"[US Rhetoric] ❌ Redis SET SKIPPED for {key} -- REDIS_AVAILABLE is False (URL len={len(UPSTASH_URL)}, TOKEN len={len(UPSTASH_TOKEN)})")
        return False
    try:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        url = f"{UPSTASH_URL}/set/{urllib.parse.quote(key, safe='')}"
        params = {'EX': ttl} if ttl else {}
        resp = requests.post(
            url,
            data=value,
            headers={'Authorization': f'Bearer {UPSTASH_TOKEN}', 'Content-Type': 'text/plain'},
            params=params,
            timeout=8,
        )
        if resp.status_code == 200:
            print(f"[US Rhetoric] ✅ Redis SET ok for {key} ({len(str(value))} bytes)")
            return True
        else:
            print(f"[US Rhetoric] ❌ Redis SET failed for {key} -- HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"[US Rhetoric] ❌ Redis SET exception for {key}: {type(e).__name__}: {str(e)[:200]}")
        return False


def _redis_lpush_trim(key, value, max_len=336):
    """Push a value onto a Redis list and trim to max_len. (12 weeks * 28 = 336 by default)"""
    if not REDIS_AVAILABLE:
        return False
    try:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        url_push = f"{UPSTASH_URL}/lpush/{urllib.parse.quote(key, safe='')}/{urllib.parse.quote(value, safe='')}"
        resp = requests.post(url_push, headers={'Authorization': f'Bearer {UPSTASH_TOKEN}'}, timeout=8)
        if resp.status_code != 200:
            return False
        url_trim = f"{UPSTASH_URL}/ltrim/{urllib.parse.quote(key, safe='')}/0/{max_len-1}"
        requests.post(url_trim, headers={'Authorization': f'Bearer {UPSTASH_TOKEN}'}, timeout=8)
        return True
    except Exception as e:
        print(f"[US Rhetoric] Redis LPUSH error for {key}: {str(e)[:120]}")
        return False


# ════════════════════════════════════════════════════════════════════
# ARTICLE FETCHING (RSS / GDELT / NewsAPI / Brave / Social)
# ════════════════════════════════════════════════════════════════════

def _parse_pub_date(pub_str):
    """Parse a publish date from various formats. Returns datetime or None."""
    if not pub_str:
        return None
    formats = [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S %Z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S',
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(pub_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
    except Exception:
        return None


def _fetch_rss(url, source_name, weight=0.85, lang='eng', max_items=20):
    """Fetch RSS feed and return list of article dicts."""
    try:
        resp = requests.get(url, timeout=RSS_TIMEOUT_SEC, headers={
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'X-Asifah-Source': 'asifahanalytics.com OSINT stability monitor',
        })
        if resp.status_code != 200:
            print(f"[US Rhetoric RSS] {source_name}: HTTP {resp.status_code}")
            return []

        root = ET.fromstring(resp.content)
        items = []
        for item in (root.iter('item') or []):
            title = (item.find('title').text if item.find('title') is not None else '') or ''
            link  = (item.find('link').text  if item.find('link')  is not None else '') or ''
            desc  = (item.find('description').text if item.find('description') is not None else '') or ''
            pub   = (item.find('pubDate').text if item.find('pubDate') is not None else '') or ''
            items.append({
                'title':       title.strip(),
                'description': desc.strip(),
                'link':        link.strip(),
                'published':   pub.strip(),
                'source':      f'rss/{source_name}',
                'source_type': 'rss',
                'language':    lang,
                'weight':      weight,
            })
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        print(f"[US Rhetoric RSS] {source_name}: error {str(e)[:120]}")
        return []


def _fetch_gdelt(query, language='eng', days=3, max_records=25, weight=0.95):
    """Fetch from GDELT 2.0 DOC API. Returns list of articles."""
    try:
        params = {
            'query':      query,
            'mode':       'artlist',
            'maxrecords': str(max_records),
            'format':     'json',
            'sort':       'datedesc',
            'sourcelang': language,
            'timespan':   f'{days*24}h',
        }
        url = 'https://api.gdeltproject.org/api/v2/doc/doc?' + urllib.parse.urlencode(params)
        resp = requests.get(url, timeout=GDELT_TIMEOUT_SEC)
        if resp.status_code == 429:
            print(f"[US Rhetoric GDELT] 429 rate limit -- skipping: {language}")
            return []
        if resp.status_code != 200:
            print(f"[US Rhetoric GDELT] HTTP {resp.status_code}")
            return []
        try:
            data = resp.json()
        except Exception:
            print(f"[US Rhetoric GDELT] {language}: non-JSON response (soft block)")
            return []

        articles = []
        for art in (data.get('articles') or []):
            articles.append({
                'title':       art.get('title', ''),
                'description': '',
                'link':        art.get('url', ''),
                'published':   art.get('seendate', ''),
                'source':      f'gdelt/{art.get("domain","unknown")}',
                'source_type': 'gdelt',
                'language':    language,
                'weight':      weight,
            })
        return articles
    except requests.exceptions.Timeout:
        print(f"[US Rhetoric GDELT] timeout (>8s) -- breaking circuit")
        return []
    except Exception as e:
        print(f"[US Rhetoric GDELT] error: {str(e)[:120]}")
        return []


def _fetch_newsapi(query, max_records=15, weight=0.9):
    """Fetch from NewsAPI as fallback when GDELT struggles."""
    if not NEWSAPI_AVAILABLE:
        return []
    try:
        url = 'https://newsapi.org/v2/everything'
        params = {
            'q':        query,
            'pageSize': max_records,
            'sortBy':   'publishedAt',
            'language': 'en',
            'apiKey':   NEWSAPI_KEY,
        }
        resp = requests.get(url, params=params, timeout=NEWSAPI_TIMEOUT_SEC)
        if resp.status_code == 429:
            print(f"[US Rhetoric NewsAPI] 429 rate limit -- skipping")
            return []
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for art in (data.get('articles') or []):
            articles.append({
                'title':       art.get('title', '') or '',
                'description': art.get('description', '') or '',
                'link':        art.get('url', '') or '',
                'published':   art.get('publishedAt', '') or '',
                'source':      f"newsapi/{(art.get('source') or {}).get('name', 'unknown')}",
                'source_type': 'newsapi',
                'language':    'eng',
                'weight':      weight,
            })
        return articles
    except Exception as e:
        print(f"[US Rhetoric NewsAPI] error: {str(e)[:120]}")
        return []


def _fetch_brave(query, max_records=15, weight=0.85):
    """Brave Search fallback (free tier, 2000 queries/month)."""
    if not BRAVE_AVAILABLE:
        return []
    try:
        url = 'https://api.search.brave.com/res/v1/news/search'
        params = {'q': query, 'count': max_records}
        resp = requests.get(url, params=params, timeout=8, headers={
            'Accept': 'application/json',
            'X-Subscription-Token': BRAVE_API_KEY,
        })
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for art in (data.get('results') or []):
            articles.append({
                'title':       art.get('title', '') or '',
                'description': art.get('description', '') or '',
                'link':        art.get('url', '') or '',
                'published':   art.get('age', '') or '',
                'source':      f"brave/{art.get('meta_url',{}).get('hostname','unknown')}",
                'source_type': 'brave',
                'language':    'eng',
                'weight':      weight,
            })
        return articles
    except Exception as e:
        print(f"[US Rhetoric Brave] error: {str(e)[:120]}")
        return []


def _fetch_all_articles():
    """Aggregate articles from all sources (RSS + GDELT + NewsAPI + Brave + social)."""
    all_articles = []

    # ── RSS ──
    rss_count = 0
    for url, name, lang, weight in [(t[1], t[0], t[2], t[3]) for t in US_RHETORIC_RSS]:
        rss = _fetch_rss(url, name, weight=weight, lang=lang)
        all_articles.extend(rss)
        rss_count += len(rss)
        time.sleep(0.3)  # gentle pacing
    print(f"[US Rhetoric] RSS: {rss_count} articles")

    # ── GDELT ──
    gdelt_count = 0
    gdelt_failed = 0
    for query, lang, weight in GDELT_QUERIES:
        if gdelt_failed >= 3:
            print(f"[US Rhetoric GDELT] Circuit broken after 3 failures -- skipping rest")
            break
        articles = _fetch_gdelt(query, language=lang, days=3, weight=weight)
        if not articles:
            gdelt_failed += 1
        else:
            gdelt_failed = 0
        all_articles.extend(articles)
        gdelt_count += len(articles)
        time.sleep(0.5)
    print(f"[US Rhetoric] GDELT: {gdelt_count} articles")

    # ── NewsAPI fallback (if GDELT thin) ──
    newsapi_count = 0
    if gdelt_count < 30 and NEWSAPI_AVAILABLE:
        print(f"[US Rhetoric] GDELT thin ({gdelt_count}) -- triggering NewsAPI fallback")
        pre_newsapi = len(all_articles)
        for q in [
            '"trump statement" OR "white house"',
            '"ice raids" OR "mass deportation"',
            '"supreme court ruling" united states',
            '"congress" democrats republicans',
        ]:
            articles = _fetch_newsapi(q, max_records=10)
            all_articles.extend(articles)
        newsapi_count = len(all_articles) - pre_newsapi
        print(f"[US Rhetoric] NewsAPI fallback: {newsapi_count} articles")

    # ── Brave fallback (NEW LOGIC May 2026): fires when GDELT + NewsAPI combined
    # is thin, independent of RSS/social health. Different source types serve
    # different analytical purposes — keyword-driven news-index discovery should
    # be backstopped even if curated RSS + social are healthy. Brave free tier
    # is 2000/month so we can spend the requests freely.
    news_index_total = gdelt_count + newsapi_count
    if news_index_total < 60 and BRAVE_AVAILABLE:
        print(f"[US Rhetoric] News-index thin (GDELT={gdelt_count} + NewsAPI={newsapi_count} = {news_index_total}) -- triggering Brave fallback")
        pre_brave = len(all_articles)
        for q in [
            'trump white house statement',
            'ice raids deportation',
            'supreme court ruling united states',
            'congress democrats republicans',
            'federal reserve powell',
            'state governor lawsuit federal',
        ]:
            articles = _fetch_brave(q, max_records=10)
            all_articles.extend(articles)
        brave_count = len(all_articles) - pre_brave
        print(f"[US Rhetoric] Brave fallback: {brave_count} articles")

    # ── Bluesky ──
    if BLUESKY_AVAILABLE:
        try:
            bluesky_raw = fetch_bluesky_for_target('us', days=7, max_posts_per_account=20)
            transformed = []
            for p in bluesky_raw:
                # Defensive: source may be a dict — coerce to string
                raw_src = p.get('source')
                if isinstance(raw_src, dict):
                    src_str = raw_src.get('name', '') or f"Bluesky/{p.get('handle','unknown')}"
                else:
                    src_str = raw_src or f"Bluesky/{p.get('handle','unknown')}"
                transformed.append({
                    'title':       p.get('title') or p.get('text') or '',
                    'description': p.get('text') or p.get('description') or '',
                    'link':        p.get('url') or p.get('link') or '',
                    'published':   p.get('publishedAt') or p.get('published') or '',
                    'source':      str(src_str),
                    'source_type': 'bluesky',
                    'language':    'eng',
                    'weight':      1.0,
                })
            all_articles.extend(transformed)
            print(f"[US Rhetoric] Bluesky: +{len(transformed)} posts")
        except Exception as e:
            print(f"[US Rhetoric] Bluesky error: {str(e)[:120]}")

    # ── Telegram ──
    if TELEGRAM_AVAILABLE:
        try:
            tg_raw = fetch_telegram_signals_us(hours_back=7 * 24)
            transformed = []
            for p in tg_raw:
                # Defensive: source may be a dict — coerce to string
                raw_src = p.get('source')
                if isinstance(raw_src, dict):
                    src_str = raw_src.get('name', '') or f"Telegram/{p.get('channel','unknown')}"
                else:
                    src_str = raw_src or f"Telegram/{p.get('channel','unknown')}"
                transformed.append({
                    'title':       p.get('title') or p.get('text') or '',
                    'description': p.get('text') or p.get('description') or '',
                    'link':        p.get('url') or p.get('link') or '',
                    'published':   p.get('publishedAt') or p.get('published') or p.get('date') or '',
                    'source':      str(src_str),
                    'source_type': 'telegram',
                    'language':    'eng',
                    'weight':      0.95,
                })
            all_articles.extend(transformed)
            print(f"[US Rhetoric] Telegram: +{len(transformed)} posts")
        except Exception as e:
            print(f"[US Rhetoric] Telegram error: {str(e)[:120]}")

    # ── Reddit ──
    if REDDIT_AVAILABLE:
        try:
            reddit_articles = fetch_reddit_signals_us(days=7, max_per_sub=25)
            for r in reddit_articles:
                r.setdefault('language', 'eng')
                r.setdefault('weight', 0.9)
            all_articles.extend(reddit_articles)
            print(f"[US Rhetoric] Reddit: +{len(reddit_articles)} posts")
        except Exception as e:
            print(f"[US Rhetoric] Reddit error: {str(e)[:120]}")

    return all_articles


# ════════════════════════════════════════════════════════════════════
# CLASSIFICATION + SCORING
# ════════════════════════════════════════════════════════════════════

def _score_article_for_actor(article, actor_key, actor_def):
    """Score how well an article matches a specific actor. Returns (score, tripwire_hit)."""
    title = (article.get('title') or '').lower()
    desc  = (article.get('description') or '').lower()
    text = title + ' ' + desc

    score = 0
    matched_keywords = 0
    for kw in actor_def['keywords']:
        if kw.lower() in text:
            matched_keywords += 1
            score += 1
    if matched_keywords == 0:
        return 0, False

    tripwire_hit = False
    for tw in actor_def.get('tripwires', []):
        if tw.lower() in text:
            score += 5
            tripwire_hit = True

    base_weight = article.get('weight', 1.0)
    return score * base_weight, tripwire_hit


def _classify_articles(articles):
    """Classify articles by actor. Returns dict {actor_key: {articles, statement_count, tripwires}}."""
    seen_links = set()
    deduped = []
    for art in articles:
        link = art.get('link', '')
        if link and link in seen_links:
            continue
        if link:
            seen_links.add(link)
        deduped.append(art)
    print(f"[US Rhetoric] Dedup: {len(articles)} -> {len(deduped)} articles")

    actor_results = {k: {'articles': [], 'statement_count': 0, 'tripwires': 0,
                          'total_score': 0.0, 'sample_articles': []}
                     for k in ACTORS.keys()}

    for art in deduped:
        for actor_key, actor_def in ACTORS.items():
            score, tripwire = _score_article_for_actor(art, actor_key, actor_def)
            if score > 0:
                actor_results[actor_key]['articles'].append(art)
                actor_results[actor_key]['statement_count'] += 1
                actor_results[actor_key]['total_score'] += score
                if tripwire:
                    actor_results[actor_key]['tripwires'] += 1
                if len(actor_results[actor_key]['sample_articles']) < 12:
                    actor_results[actor_key]['sample_articles'].append({
                        'title':     art.get('title', '')[:200],
                        'link':      art.get('link', ''),
                        'source':    art.get('source', ''),
                        'published': art.get('published', ''),
                        'language':  art.get('language', 'eng'),
                    })

    for actor_key, result in actor_results.items():
        actor_def = ACTORS[actor_key]
        baseline_3d = actor_def['baseline_statements_per_week'] * (3/7)
        ratio = result['statement_count'] / max(1.0, baseline_3d)
        # Volatility score: ratio above baseline indicates elevated activity
        # Cap at 100, scale so 1x baseline = 25, 2x = 50, 3x+ = 75-100
        if ratio <= 1.0:
            actor_score = 15 + ratio * 10  # 15-25 for normal
        elif ratio <= 2.0:
            actor_score = 25 + (ratio - 1) * 25  # 25-50
        elif ratio <= 3.0:
            actor_score = 50 + (ratio - 2) * 25  # 50-75
        else:
            actor_score = min(100, 75 + (ratio - 3) * 12.5)
        actor_score += result['tripwires'] * 8
        result['actor_score'] = min(100, round(actor_score, 1))
        result['baseline_ratio'] = round(ratio, 2)
        tier_lvl, tier_name, tier_band, tier_icon, tier_desc = _get_tier(result['actor_score'])
        result['tier'] = tier_lvl
        result['tier_name'] = tier_name
        result['tier_band'] = tier_band
        result['tier_icon'] = tier_icon
        result['tier_description'] = tier_desc

    return actor_results


# ════════════════════════════════════════════════════════════════════
# AGGREGATE COMPOSITE SCORE
# ════════════════════════════════════════════════════════════════════

def _compute_composite_score(actor_results):
    """Weighted average of actor scores -> composite US rhetoric score (0-100)."""
    total_weight = 0.0
    weighted_sum = 0.0
    for actor_key, result in actor_results.items():
        weight = ACTORS[actor_key]['weight']
        weighted_sum += result['actor_score'] * weight
        total_weight += weight
    composite = weighted_sum / total_weight if total_weight > 0 else 0
    return round(composite, 1)


# ════════════════════════════════════════════════════════════════════
# CROSS-THEATER FINGERPRINT (READ all + WRITE us_*)
# ════════════════════════════════════════════════════════════════════

# Full list of trackers to read fingerprints from
CROSS_THEATER_SOURCES = [
    # Middle East
    'iran', 'israel', 'lebanon', 'yemen', 'iraq', 'syria', 'oman',
    # Asia
    'china', 'taiwan', 'japan',  # 'dprk', 'india_pakistan' coming-soon
    # Europe
    'russia', 'belarus', 'ukraine', 'greenland',
    # Western Hemisphere
    'cuba', 'venezuela', 'mexico', 'panama', 'haiti', 'colombia', 'brazil',
    'peru', 'chile',
]


def _read_crosstheater_fingerprints():
    """Read fingerprints from all other trackers. Returns dict by source theater."""
    fingerprints = {}
    for theater in CROSS_THEATER_SOURCES:
        # Try multiple key conventions used across trackers
        for key_pattern in [f'fingerprint:{theater}:current',
                            f'rhetoric:{theater}:fingerprint',
                            f'crosstheater:{theater}']:
            fp = _redis_get(key_pattern)
            if fp:
                fingerprints[theater] = fp
                break
    return fingerprints


def _detect_outbound_targets(actor_results, fingerprints):
    """Identify which countries the US is currently rhetoric-targeting."""
    targets = []
    target_keywords = {
        'iran':       ['iran', 'tehran', 'iranian', 'irgc'],
        'china':      ['china', 'beijing', 'chinese', 'xi jinping', 'taiwan strait'],
        'russia':     ['russia', 'putin', 'kremlin', 'russian'],
        'mexico':     ['mexico', 'sheinbaum', 'mexican', 'cartel'],
        'cuba':       ['cuba', 'cuban', 'havana', 'diaz-canel'],
        'venezuela':  ['venezuela', 'maduro', 'caracas', 'venezuelan'],
        'panama':     ['panama', 'panama canal'],
        'greenland':  ['greenland'],
        'north_korea':['north korea', 'kim jong un', 'dprk', 'pyongyang'],
        'israel':     ['israel', 'netanyahu', 'idf'],
        'lebanon':    ['lebanon', 'hezbollah'],
        'yemen':      ['yemen', 'houthi', 'houthis'],
        'ukraine':    ['ukraine', 'zelensky', 'kyiv'],
    }
    exec_articles = actor_results.get('us_executive', {}).get('articles', [])
    state_articles = actor_results.get('us_state_dept', {}).get('articles', [])
    defense_articles = actor_results.get('us_defense', {}).get('articles', [])
    all_outbound = exec_articles + state_articles + defense_articles

    for target, kws in target_keywords.items():
        count = 0
        for art in all_outbound:
            text = ((art.get('title') or '') + ' ' + (art.get('description') or '')).lower()
            for kw in kws:
                if kw in text:
                    count += 1
                    break
        if count >= 2:
            targets.append({'country': target, 'mention_count': count})
    targets.sort(key=lambda t: t['mention_count'], reverse=True)
    return targets[:10]


def _write_us_fingerprint(actor_results, composite, branch_div, fracture, outbound_targets):
    """Write the US cross-theater fingerprint that all other trackers will read."""
    fingerprint = {
        'us_active':                    composite >= 26,
        'us_composite_score':           composite,
        'us_tier':                      _get_tier(composite)[0],
        'us_tier_band':                 _get_tier(composite)[2],
        'us_executive_score':           actor_results['us_executive']['actor_score'],
        'us_executive_volatility':      actor_results['us_executive']['baseline_ratio'],
        'us_dhs_enforcement_score':     actor_results['us_dhs_ice']['actor_score'],
        'us_dhs_enforcement_active':    actor_results['us_dhs_ice']['actor_score'] >= 38,
        'us_judicial_pushback_score':   actor_results['us_judicial']['actor_score'],
        'us_branch_divergence_score':   branch_div,
        'us_domestic_fracture_score':   fracture,
        'us_outbound_targets':          outbound_targets,
        'us_taco_index_v0':             0,  # placeholder for v1.1
        'updated_at':                   datetime.now(timezone.utc).isoformat(),
    }
    _redis_set('fingerprint:us:current', fingerprint)
    return fingerprint


# ════════════════════════════════════════════════════════════════════
# MAIN SCAN
# ════════════════════════════════════════════════════════════════════

_scan_lock    = threading.Lock()
_scan_running = False


def run_us_rhetoric_scan(force=False):
    """Run a full US rhetoric scan. Returns the result dict."""
    global _scan_running
    with _scan_lock:
        if _scan_running and not force:
            print("[US Rhetoric] Scan already running, skipping")
            return None
        _scan_running = True

    start_time = time.time()
    print(f"[US Rhetoric] === Starting scan at {datetime.now(timezone.utc).isoformat()} ===")

    try:
        # Phase 1: fetch articles
        print("[US Rhetoric] Phase 1: fetching articles...")
        articles = _fetch_all_articles()
        print(f"[US Rhetoric] Total articles fetched: {len(articles)}")

        # Phase 2: classify by actor
        print("[US Rhetoric] Phase 2: classifying by actor...")
        actor_results = _classify_articles(articles)

        # Phase 3: composite score
        composite = _compute_composite_score(actor_results)
        tier_lvl, tier_name, tier_band, tier_icon, tier_desc = _get_tier(composite)
        print(f"[US Rhetoric] Composite score: {composite} ({tier_lvl} {tier_name} -- {tier_band})")

        # Phase 4: cross-theater reads
        print("[US Rhetoric] Phase 4: reading cross-theater fingerprints...")
        cross_theater_fps = _read_crosstheater_fingerprints()
        print(f"[US Rhetoric] Read fingerprints from {len(cross_theater_fps)} theaters")

        outbound_targets = _detect_outbound_targets(actor_results, cross_theater_fps)
        print(f"[US Rhetoric] Outbound targets detected: {[t['country'] for t in outbound_targets[:5]]}")

        # Phase 5: branch divergence + domestic fracture (interpreter)
        if INTERPRETER_AVAILABLE:
            branch_div = compute_branch_divergence_score(actor_results)
            fracture   = compute_domestic_fracture_score(actor_results, articles)
            top_signals = compute_top_signals(actor_results, articles, cross_theater_fps)
            so_what    = compute_so_what_factor(actor_results, composite, outbound_targets)
        else:
            branch_div = 0
            fracture   = 0
            top_signals = []
            so_what    = {'factor': 'unknown', 'description': 'Signal interpreter not loaded'}

        # Phase 6: write fingerprint
        fingerprint = _write_us_fingerprint(actor_results, composite, branch_div, fracture, outbound_targets)

        # Phase 7: build full result
        elapsed = round(time.time() - start_time, 1)
        result = {
            'composite_score':         composite,
            'tier':                    tier_lvl,
            'tier_name':               tier_name,
            'tier_band':               tier_band,
            'tier_icon':               tier_icon,
            'tier_description':        tier_desc,
            'actors':                  {k: {kk: v[kk] for kk in v if kk != 'articles'}
                                        for k, v in actor_results.items()},
            'cross_theater_fps':       cross_theater_fps,
            'outbound_targets':        outbound_targets,
            'branch_divergence_score': branch_div,
            'domestic_fracture_score': fracture,
            'top_signals':             top_signals,
            'so_what':                 so_what,
            'fingerprint':             fingerprint,
            'article_count':           len(articles),
            'scan_seconds':            elapsed,
            'scan_completed_at':       datetime.now(timezone.utc).isoformat(),
            'source_counts':           _compute_source_counts(articles),
            'actor_display_order':     ACTOR_DISPLAY_ORDER,
            'layer_order':             LAYER_ORDER,
        }

        # Phase 8: cache write
        _redis_set('rhetoric:us:latest', result)
        compact = {k: result[k] for k in ('composite_score', 'tier', 'tier_name', 'tier_band',
                                          'tier_icon', 'top_signals', 'so_what',
                                          'outbound_targets', 'scan_completed_at')}
        _redis_set('rhetoric:us:summary', compact)

        # Phase 9: history snapshot
        snapshot = {
            'date':            datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'composite_score': composite,
            'tier':            tier_lvl,
            'tier_band':       tier_band,
            'actor_scores':    {k: v['actor_score'] for k, v in actor_results.items()},
            'fracture':        fracture,
            'branch_div':      branch_div,
        }
        _redis_lpush_trim('rhetoric:us:history', snapshot, max_len=336)

        print(f"[US Rhetoric] ✅ Scan complete in {elapsed}s -- composite={composite} ({tier_lvl})")
        return result

    except Exception as e:
        print(f"[US Rhetoric] ❌ Scan error: {str(e)[:300]}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        with _scan_lock:
            _scan_running = False


def _compute_source_counts(articles):
    """Aggregate article counts by source_type for diagnostics."""
    counts = {}
    for art in articles:
        st = art.get('source_type', 'unknown')
        counts[st] = counts.get(st, 0) + 1
    return counts


# ════════════════════════════════════════════════════════════════════
# CACHE / BACKGROUND
# ════════════════════════════════════════════════════════════════════

def get_us_rhetoric_cache():
    """Return cached scan result or None."""
    return _redis_get('rhetoric:us:latest')


def _background_refresh():
    """Periodic refresh thread."""
    time.sleep(INITIAL_BOOT_DELAY_SEC)
    while True:
        try:
            print("[US Rhetoric] Background refresh starting...")
            run_us_rhetoric_scan()
        except Exception as e:
            print(f"[US Rhetoric] Background refresh error: {str(e)[:200]}")
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


def start_background_refresh():
    """Start the background refresh thread."""
    t = threading.Thread(target=_background_refresh, daemon=True, name='us_rhetoric_bg')
    t.start()
    print("[US Rhetoric] Background refresh thread started (initial delay 90s)")


# ════════════════════════════════════════════════════════════════════
# FLASK ENDPOINT REGISTRATION
# ════════════════════════════════════════════════════════════════════

def register_us_rhetoric_endpoints(app):
    """Register Flask endpoints for the US rhetoric tracker."""
    from flask import jsonify, request

    @app.route('/api/rhetoric/us', methods=['GET', 'OPTIONS'])
    def api_rhetoric_us():
        if request.method == 'OPTIONS':
            return '', 200
        try:
            force = request.args.get('refresh', 'false').lower() == 'true'
            if force:
                # Trigger background scan, return cached for now
                threading.Thread(target=run_us_rhetoric_scan, daemon=True).start()
            cache = get_us_rhetoric_cache()
            if not cache:
                return jsonify({'success': False,
                                'error': 'No cached data — first scan in progress.'}), 503
            return jsonify(cache)
        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/rhetoric/us/debug', methods=['GET'])
    def api_rhetoric_us_debug():
        try:
            cache = get_us_rhetoric_cache() or {}
            cross_fps = _read_crosstheater_fingerprints()
            return jsonify({
                'cache_present':       bool(cache),
                'composite_score':     cache.get('composite_score'),
                'tier':                cache.get('tier'),
                'scan_completed_at':   cache.get('scan_completed_at'),
                'article_count':       cache.get('article_count'),
                'source_counts':       cache.get('source_counts', {}),
                'cross_theater_fps_loaded': list(cross_fps.keys()),
                'actors':              list(ACTORS.keys()),
                'redis_available':     REDIS_AVAILABLE,
                'newsapi_available':   NEWSAPI_AVAILABLE,
                'brave_available':     BRAVE_AVAILABLE,
                'bluesky_available':   BLUESKY_AVAILABLE,
                'telegram_available':  TELEGRAM_AVAILABLE,
                'reddit_available':    REDDIT_AVAILABLE,
                'interpreter_available': INTERPRETER_AVAILABLE,
                'scan_interval_hours': SCAN_INTERVAL_HOURS,
            })
        except Exception as e:
            return jsonify({'error': str(e)[:200]}), 500

    print("[US Rhetoric] ✅ Endpoints registered: /api/rhetoric/us, /api/rhetoric/us/debug")


print("[US Rhetoric] Module loaded.")
