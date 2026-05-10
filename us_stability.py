"""
Asifah Analytics — U.S. Stability Index v1.0.0
May 11, 2026

THE SCORING ENGINE for the U.S. Stability page. This is sister-module to
china_stability.py, russia_stability.py, lebanon_stability.py, but with
U.S.-specific dimensions reflecting the structural distinctness of
American government.

ANALYTICAL FRAME — APOLITICAL BY DESIGN:
The same scoring rubric applies regardless of which administration is in
power. Specific events that score the same severity:

  • 1973 Saturday Night Massacre (Nixon firing Cox/Richardson) →
    Democratic Institutions stress
  • 2021 January 6 → Civil/Social + Political Cohesion stress
  • 2024 Trump indictments (Biden-era DOJ) → Democratic Institutions stress
  • 2025 cabinet turnover (Trump 2nd term) → Political Cohesion stress
  • Hypothetical Dem unilateral debt cancellation against court order →
    Democratic Institutions stress

Keyword sets are STRUCTURAL-PATTERN based, not party-coded. Same code
runs in 2026 (unified GOP) or hypothetical 2027 (divided govt).

SIX SCORING DIMENSIONS:

  1. Economic Stability         (20%) — economic_indicators_us module
  2. Political Cohesion         (15%) — cabinet/agency churn, deadlock
  3. Civil / Social             (15%) — mass casualty, protest activity
  4. Democratic Institutions    (20%) — court orders, IGs, electoral
  5. Military Posture           (15%) — military:us:posture fingerprint
  6. Cyber / Infrastructure     (15%) — cyber events, infra failures

COMPOSITE STABILITY INDEX (0-100, higher = more stress):
  0-29   🟢  RESILIENT             — strong functional state
  30-49  🟡  STRESSED               — multiple signals elevated
  50-69  🟠  FRACTURED              — convergent stress
  70-89  🔴  CRISIS MODE            — major institutional pressure
  90-100 🔴  CONSTITUTIONAL CRISIS  — load-bearing institutions failing

Apolitical, structural — not rhetoric-delta-based (unlike older trackers).
This means scores are directly comparable across time periods and
administrations.

ELECTION-CYCLE AWARENESS:
The composite score is multiplied by election_cycle.stability_modifier
(1.0 to 1.6) to reflect that certain phases (lame duck, election week,
late campaign) amplify political stress signals' relevance.

CROSS-TRACKER WRITES (for Global Pressure Index consumption):
  - stability:us:fingerprint   (12h TTL, full payload)
  - stability:us:summary       (12h TTL, compressed for GPI)

REDIS KEYS:
  Cache:           us:stability:latest
  History:         us:stability:history    (30 days, daily snapshots)
  Fingerprint:     stability:us:fingerprint
  Cross-theater:   military:us:posture     (READ — from mil tracker)

DATA SOURCES (v1.1.0):
  RSS feeds  · GDELT · NewsAPI · Brave Search (fallback)
  Bluesky    · Telegram · Reddit  (NEW — social signal expansion)
  FRED       · Yahoo Finance · Congress.gov · Military Tracker fingerprint

ENDPOINTS:
  GET /api/us-stability                 — full payload
  GET /api/us-stability/debug           — diagnostics
  GET /api/us-stability/dimension/<id>  — single dimension detail
  GET /api/us-stability/history         — 30-day trendline data

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import time
import threading
import requests
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta


# ════════════════════════════════════════════════════════════
# SOCIAL SIGNAL COLLECTORS (v1.1.0 — May 2026)
# ════════════════════════════════════════════════════════════
# Three external modules feed social-media signal into the article pool
# alongside RSS / GDELT / NewsAPI. Each module is wrapped in try/except so
# the scan keeps working if any single module is missing or broken.
#
#   Bluesky:  101 accounts (US gov + journalists + foreign view) — no auth
#   Telegram: 33 channels  (Israeli, UK, AJ, breaking news) — requires API keys
#   Reddit:   74 sub/mode pairs (cross-spectrum) — no auth
# ════════════════════════════════════════════════════════════
try:
    from bluesky_signals_wha import fetch_bluesky_for_target
    BLUESKY_US_AVAILABLE = True
    print("[US Stability] Bluesky US signals module loaded")
except ImportError as e:
    BLUESKY_US_AVAILABLE = False
    print(f"[US Stability] WARNING: Bluesky unavailable ({e})")

try:
    from telegram_signals_wha import fetch_telegram_signals_us
    TELEGRAM_US_AVAILABLE = True
    print("[US Stability] Telegram US signals module loaded")
except ImportError as e:
    TELEGRAM_US_AVAILABLE = False
    print(f"[US Stability] WARNING: Telegram unavailable ({e})")

try:
    from reddit_signals_us import fetch_reddit_signals_us
    REDDIT_US_AVAILABLE = True
    print("[US Stability] Reddit US signals module loaded")
except ImportError as e:
    REDDIT_US_AVAILABLE = False
    print(f"[US Stability] WARNING: Reddit unavailable ({e})")


# ============================================================
# CONFIGURATION
# ============================================================

print("[US Stability] Module loading...")

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL') or
                     os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN') or
                       os.environ.get('UPSTASH_REDIS_REST_TOKEN'))
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY')

# Cache keys
CACHE_KEY        = 'us:stability:latest'
HISTORY_KEY      = 'us:stability:history'
FINGERPRINT_KEY  = 'stability:us:fingerprint'
SUMMARY_KEY      = 'stability:us:summary'

CACHE_TTL_SECONDS  = 12 * 3600    # 12h
HISTORY_DAYS       = 30            # 30 daily snapshots
SCAN_INTERVAL_HOURS = 12

# Background scan management
_scan_lock = threading.Lock()
_scan_running = False

DEFAULT_TIMEOUT = 12

print("[US Stability] Configuration loaded.")


# ============================================================
# IMPORT DEPENDENCIES (graceful degradation if missing)
# ============================================================

try:
    from economic_indicators_us import fetch_economic_indicators
    ECON_AVAILABLE = True
    print("[US Stability] ✅ economic_indicators_us imported")
except ImportError:
    ECON_AVAILABLE = False
    print("[US Stability] ⚠️  economic_indicators_us not available — Dimension 1 will fail")

try:
    from us_government_composition import get_government_composition
    GOVT_AVAILABLE = True
    print("[US Stability] ✅ us_government_composition imported")
except ImportError:
    GOVT_AVAILABLE = False
    print("[US Stability] ⚠️  us_government_composition not available — using default baselines")


# ============================================================
# STABILITY BANDS (canonical 5-band system)
# ============================================================

STABILITY_BANDS = [
    {'min':  0, 'max': 29,  'band': 'resilient',           'label': 'Resilient',
     'icon': '🟢', 'color': '#10b981',
     'description': 'Strong functional state across all dimensions.'},
    {'min': 30, 'max': 49,  'band': 'stressed',            'label': 'Stressed',
     'icon': '🟡', 'color': '#f59e0b',
     'description': 'Multiple signals elevated; institutional capacity intact.'},
    {'min': 50, 'max': 69,  'band': 'fractured',           'label': 'Fractured',
     'icon': '🟠', 'color': '#f97316',
     'description': 'Convergent stress across dimensions; some institutional friction.'},
    {'min': 70, 'max': 89,  'band': 'crisis_mode',         'label': 'Crisis Mode',
     'icon': '🔴', 'color': '#ef4444',
     'description': 'Major institutional pressure; multiple load-bearing systems strained.'},
    {'min': 90, 'max': 100, 'band': 'constitutional_crisis', 'label': 'Constitutional Crisis',
     'icon': '🔴', 'color': '#991b1b',
     'description': 'Load-bearing institutions failing or in active conflict.'},
]


def score_to_band(score):
    """Given a 0-100 score, return matching band dict."""
    for b in STABILITY_BANDS:
        if b['min'] <= score <= b['max']:
            return b
    # Fallback (e.g., negative or >100)
    if score < 0:
        return STABILITY_BANDS[0]
    return STABILITY_BANDS[-1]


# ============================================================
# DIMENSION WEIGHTS (must sum to 1.0)
# ============================================================

DIMENSION_WEIGHTS = {
    'economic':                0.20,
    'political_cohesion':      0.15,
    'civil_social':            0.15,
    'democratic_institutions': 0.20,
    'military_posture':        0.15,
    'cyber_infrastructure':    0.15,
}

# Sanity check
assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 0.001, \
    "Dimension weights must sum to 1.0"


# ============================================================
# DIMENSION 1 — ECONOMIC STABILITY THRESHOLDS
# ============================================================
# Threshold tables: maps indicator value to 0-100 stress score
# (Higher value on indicator → higher stress score, EXCEPT for "good_direction"
# indicators where higher = better)
# ============================================================

ECON_THRESHOLDS = {
    'cpi_yoy': {
        'unit':  '%',
        'good_direction': 'down',
        'thresholds': [
            (0,    2.5,   10),   # below 2.5% YoY: very mild
            (2.5,  4.0,   30),   # 2.5-4%: stressed
            (4.0,  6.0,   55),   # 4-6%: fractured
            (6.0,  9.0,   75),   # 6-9%: crisis
            (9.0,  100,   95),   # >9%: constitutional-economic crisis
        ],
    },
    'unemployment': {
        'unit':  '%',
        'good_direction': 'down',
        'thresholds': [
            (0,    4.0,   10),
            (4.0,  5.5,   30),
            (5.5,  7.0,   55),
            (7.0,  9.0,   75),
            (9.0,  100,   95),
        ],
    },
    'mortgage_30yr': {
        'unit':  '%',
        'good_direction': 'down',
        'thresholds': [
            (0,    5.5,   15),
            (5.5,  7.0,   35),
            (7.0,  8.5,   55),
            (8.5,  10.0,  75),
            (10.0, 100,   90),
        ],
    },
    'gas_price': {
        'unit':  '$/gal',
        'good_direction': 'down',
        'thresholds': [
            (0,    3.25,  15),
            (3.25, 4.00,  35),
            (4.00, 5.00,  55),
            (5.00, 6.00,  75),
            (6.00, 100,   90),
        ],
    },
    'treasury_10y': {
        'unit':  '%',
        'good_direction': 'down',
        'thresholds': [
            (0,    4.0,   15),
            (4.0,  5.0,   35),
            (5.0,  6.0,   55),
            (6.0,  7.0,   75),
            (7.0,  100,   90),
        ],
    },
    'jobless_claims': {
        'unit':  'count',
        'good_direction': 'down',
        'thresholds': [
            (0,      230000,   15),
            (230000, 275000,   35),
            (275000, 350000,   55),
            (350000, 450000,   75),
            (450000, 1000000,  90),
        ],
    },
    'fed_funds': {
        'unit':  '%',
        'good_direction': None,    # context-dependent
        'thresholds': [
            (0,    1.0,   25),    # near-zero rates can signal crisis-response
            (1.0,  3.0,   15),    # normal range
            (3.0,  5.0,   25),
            (5.0,  7.0,   45),
            (7.0,  100,   70),
        ],
    },
    'deficit_gdp': {
        'unit':  '%',
        'good_direction': 'up',    # closer to 0 (or surplus) is better
        'thresholds': [
            (-3,   100,   15),    # surplus or deficit < 3%
            (-5,   -3,    30),    # 3-5% deficit
            (-7,   -5,    50),    # 5-7% deficit
            (-10,  -7,    70),    # 7-10% deficit
            (-100, -10,   90),    # >10% deficit
        ],
    },
    # Equity indices and BTC don't have stability thresholds in same way —
    # we skip them in the scoring (they're informational, not stress-mapped)
}


def score_economic_indicator(indicator_id, value):
    """Map an indicator value to a 0-100 stress score using threshold table."""
    if value is None or indicator_id not in ECON_THRESHOLDS:
        return None
    cfg = ECON_THRESHOLDS[indicator_id]
    for low, high, score in cfg['thresholds']:
        if low <= value < high:
            return score
    # Off-table — return highest band score
    return cfg['thresholds'][-1][2]


# ============================================================
# DIMENSION 2-4, 6 — KEYWORD SIGNAL DETECTION SETS
# ============================================================
# APOLITICAL keyword sets — detect structural stress patterns
# regardless of which party is involved.
# ============================================================

POLITICAL_COHESION_KEYWORDS = {
    # Cabinet/Agency Churn (modified by cabinet_turnover_weight from baseline)
    'cabinet_churn': {
        'patterns': [
            'cabinet shakeup', 'cabinet reshuffle', 'cabinet resign',
            'secretary resigns', 'secretary fired', 'secretary stepped down',
            'fired the head of', 'fired the director of', 'removed the director',
            'forced out as', 'ousted as', 'pushed out of',
            'acting secretary', 'interim director', 'interim secretary',
            'leadership vacancy', 'agency leadership vacant',
            'nominee withdrawn', 'withdraws from consideration',
            'rejected by senate', 'failed to confirm',
        ],
        'base_weight': 8,
        'baseline_modifier_key': 'cabinet_turnover_weight',
    },
    # Legislative Deadlock
    'legislative_deadlock': {
        'patterns': [
            'shutdown looms', 'government shutdown', 'continuing resolution',
            'fiscal cliff', 'debt ceiling crisis', 'debt limit fight',
            'filibuster', 'stalemate in', 'no path forward',
            'fiscal impasse', 'budget impasse',
            'failed to pass', 'rejected the bill',
            'cloture vote failed',
        ],
        'base_weight': 6,
        'baseline_modifier_key': 'partisan_deadlock_weight',
    },
    # Inter-branch Friction
    'inter_branch_friction': {
        'patterns': [
            'veto override', 'congressional subpoena', 'subpoena defied',
            'stonewall congress', 'refused to comply with subpoena',
            'speaker challenge', 'motion to vacate',
            'lawmaker indicted', 'congressman indicted', 'senator indicted',
            'ethics violation', 'censure resolution',
            'expelled from congress',
        ],
        'base_weight': 7,
        'baseline_modifier_key': None,
    },
}

CIVIL_SOCIAL_KEYWORDS = {
    # Mass Casualty Events (heaviest weight)
    'mass_casualty': {
        'patterns': [
            'mass shooting', 'active shooter', 'active shooter incident',
            'school shooting', 'workplace shooting', 'church shooting',
            'shooting at', 'gunman opened fire',
            'casualties reported', 'multiple casualties',
            'mass casualty incident',
        ],
        'base_weight': 12,
        'baseline_modifier_key': None,
    },
    # Protest Activity (apolitical — tracked by name+size+frequency)
    'protest_activity': {
        'patterns': [
            'thousands gathered', 'thousands protest', 'tens of thousands',
            'protests in', 'rally drew', 'march on', 'demonstration in',
            'no kings movement', 'no kings rally', 'no kings protest',
            'black lives matter', 'blm rally', 'blm protest',
            'tea party rally', 'tea party movement',
            'march for life', 'pride rally', 'pride march',
            'climate march', 'climate strike',
            'standing protest', 'occupation of',
        ],
        'base_weight': 4,
        'baseline_modifier_key': None,
    },
    # Civil Unrest
    'civil_unrest': {
        'patterns': [
            'riots in', 'riots erupted', 'looting reported',
            'curfew imposed', 'curfew declared',
            'national guard deployed', 'national guard activated',
            'state of emergency declared',
            'martial law',
            'tear gas deployed', 'rubber bullets fired',
        ],
        'base_weight': 10,
        'baseline_modifier_key': None,
    },
    # Severe Weather (climate stability proxy)
    'severe_weather': {
        'patterns': [
            'hurricane warning', 'hurricane landfall', 'category 4 hurricane', 'category 5 hurricane',
            'wildfire evacuation', 'wildfire grew to', 'wildfires destroy',
            'extreme heat', 'heat dome', 'heat advisory',
            'polar vortex', 'arctic blast',
            'flooding emergency', 'flash flood emergency',
            'drought emergency', 'tornado outbreak',
        ],
        'base_weight': 5,
        'baseline_modifier_key': None,
    },
}

DEMOCRATIC_INSTITUTIONS_KEYWORDS = {
    # Court Order Compliance (modified by court_orders_defied_weight)
    'court_order_compliance': {
        'patterns': [
            'court order defied', 'ignored court ruling', 'in contempt of court',
            'judge held in contempt', 'contempt of court',
            'stay denied', 'court issued', 'judge ruled', 'ruling against',
            'temporary restraining order', 'preliminary injunction',
            'supreme court ruled', 'scotus ruled', 'court enjoined',
            'judicial review',
        ],
        'base_weight': 9,
        'baseline_modifier_key': 'court_orders_defied_weight',
    },
    # Inspector General / Oversight Integrity
    'oversight_integrity': {
        'patterns': [
            'inspector general fired', 'removed ig', 'ig dismissed',
            'inspector general dismissed', 'watchdog removed', 'oversight removed',
            'career official replaced', 'career civil service',
            'whistleblower', 'whistleblower retaliation',
            'gao report', 'congressional watchdog',
        ],
        'base_weight': 8,
        'baseline_modifier_key': 'inspector_general_dismissal',
    },
    # Civil Service Erosion
    'civil_service_erosion': {
        'patterns': [
            'schedule f', 'schedule f executive order',
            'civil service reform', 'merit system', 'career civil service fired',
            'agency career staff', 'loyalty test', 'political appointee',
            'mass firings', 'mass termination',
            'reduction in force',
        ],
        'base_weight': 8,
        'baseline_modifier_key': 'civil_service_purge_weight',
    },
    # Electoral Integrity Signals
    'electoral_integrity': {
        'patterns': [
            'election certification', 'certification disputed', 'certification challenged',
            'secretary of state challenged', 'state election official',
            'electoral college dispute', 'faithless elector',
            'ballot challenges', 'ballot rejected', 'voter suppression',
            'voting machines compromised', 'election fraud allegation',
            'election integrity', 'election denialism',
            'gerrymandering ruling', 'redistricting ruling',
        ],
        'base_weight': 9,
        'baseline_modifier_key': None,
    },
    # DOJ Independence Signals (works in both directions)
    'doj_independence': {
        'patterns': [
            'doj politicized', 'political prosecution', 'selective prosecution',
            'attorney general ordered', 'ag ordered to', 'ag fired',
            'white house pressured doj', 'white house pressured prosecutors',
            'special counsel removed', 'special counsel fired',
            'doj reorganization', 'us attorney fired', 'us attorneys removed',
            'pardon controversy', 'preemptive pardon',
        ],
        'base_weight': 9,
        'baseline_modifier_key': None,
    },
}

CYBER_INFRA_KEYWORDS = {
    # Cyber Events
    'cyber_events': {
        'patterns': [
            'ransomware attack', 'ransomware on',
            'data breach', 'data breach exposed',
            'cyberattack on', 'cyber attack on',
            'critical infrastructure attack', 'pipeline hack',
            'election system breach', 'voter data breach',
            'state-sponsored hack', 'apt group',
            'cisa warning', 'cisa alert',
        ],
        'base_weight': 8,
        'baseline_modifier_key': None,
    },
    # Infrastructure Failures
    'infrastructure_failures': {
        'patterns': [
            'power grid failure', 'power outage', 'rolling blackouts',
            'mass power outage', 'electricity grid failure',
            'bridge collapse', 'road collapse',
            'infrastructure failure',
            'water system contamination', 'water crisis',
            'water main break', 'sewer system failure',
            'natural gas explosion', 'pipeline rupture',
        ],
        'base_weight': 7,
        'baseline_modifier_key': None,
    },
    # Tech / Network Stability
    'tech_failures': {
        'patterns': [
            'air traffic outage', 'faa system failure', 'faa ground stop',
            '911 system down', 'emergency services outage',
            'banking system outage', 'payment system failure',
            'major outage at',
        ],
        'base_weight': 6,
        'baseline_modifier_key': None,
    },
}


# ============================================================
# RSS / GDELT / NEWSAPI SIGNAL FETCHERS
# ============================================================

# RSS feeds — focused on US domestic stability
US_STABILITY_RSS = [
    ('Reuters US',       'https://feeds.reuters.com/reuters/domesticNews'),
    ('NPR National',     'https://feeds.npr.org/1003/rss.xml'),
    ('AP US',            'https://apnews.com/index.rss'),
    ('CNN Politics',     'http://rss.cnn.com/rss/cnn_allpolitics.rss'),
    ('NYT US',           'https://rss.nytimes.com/services/xml/rss/nyt/US.xml'),
    ('Politico',         'https://www.politico.com/rss/politicopicks.xml'),
    ('The Hill',         'https://thehill.com/news/feed/'),
    ('Axios',            'https://api.axios.com/feed/'),
    ('Just Security',    'https://www.justsecurity.org/feed/'),
    ('Lawfare',          'https://www.lawfaremedia.org/feed.xml'),
    ('CISA Alerts',      'https://www.cisa.gov/news.xml'),
    ('FEMA News',        'https://www.fema.gov/about/news-multimedia/rss'),
    # Spanish-language US-focused (for ES tab)
    ('Univision',        'https://www.univision.com/feed/rss/news.xml'),
    ('Telemundo',        'https://www.telemundo.com/feed/news'),
]

# 50 US states — for state-level signal aggregation
US_STATES = {
    'AL': 'Alabama',         'AK': 'Alaska',          'AZ': 'Arizona',
    'AR': 'Arkansas',        'CA': 'California',      'CO': 'Colorado',
    'CT': 'Connecticut',     'DE': 'Delaware',        'FL': 'Florida',
    'GA': 'Georgia',         'HI': 'Hawaii',          'ID': 'Idaho',
    'IL': 'Illinois',        'IN': 'Indiana',         'IA': 'Iowa',
    'KS': 'Kansas',          'KY': 'Kentucky',        'LA': 'Louisiana',
    'ME': 'Maine',           'MD': 'Maryland',        'MA': 'Massachusetts',
    'MI': 'Michigan',        'MN': 'Minnesota',       'MS': 'Mississippi',
    'MO': 'Missouri',        'MT': 'Montana',         'NE': 'Nebraska',
    'NV': 'Nevada',          'NH': 'New Hampshire',   'NJ': 'New Jersey',
    'NM': 'New Mexico',      'NY': 'New York',        'NC': 'North Carolina',
    'ND': 'North Dakota',    'OH': 'Ohio',            'OK': 'Oklahoma',
    'OR': 'Oregon',          'PA': 'Pennsylvania',    'RI': 'Rhode Island',
    'SC': 'South Carolina',  'SD': 'South Dakota',    'TN': 'Tennessee',
    'TX': 'Texas',           'UT': 'Utah',            'VT': 'Vermont',
    'VA': 'Virginia',        'WA': 'Washington',      'WV': 'West Virginia',
    'WI': 'Wisconsin',       'WY': 'Wyoming',         'DC': 'District of Columbia',
}


def _fetch_rss(name, url, max_items=15):
    """Fetch RSS feed and return list of {title, link, published, source}."""
    try:
        resp = requests.get(url, timeout=DEFAULT_TIMEOUT,
                            headers={'User-Agent': 'AsifahAnalytics/1.0'})
        if resp.status_code != 200:
            print(f"[US Stability RSS] {name}: HTTP {resp.status_code}")
            return []
        root = ET.fromstring(resp.text)
        items = []
        # Handle both RSS and Atom
        for item in (root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')):
            title_el = item.find('title') or item.find('{http://www.w3.org/2005/Atom}title')
            link_el = item.find('link') or item.find('{http://www.w3.org/2005/Atom}link')
            pub_el = (item.find('pubDate') or
                      item.find('{http://www.w3.org/2005/Atom}published') or
                      item.find('{http://www.w3.org/2005/Atom}updated'))
            desc_el = (item.find('description') or
                       item.find('{http://www.w3.org/2005/Atom}summary'))
            if title_el is None or title_el.text is None:
                continue
            link_text = ''
            if link_el is not None:
                link_text = (link_el.text or link_el.get('href') or '').strip()
            items.append({
                'title':       title_el.text.strip(),
                'description': (desc_el.text or '').strip() if desc_el is not None else '',
                'link':        link_text,
                'published':   pub_el.text.strip() if (pub_el is not None and pub_el.text) else '',
                'source':      name,
                'source_type': 'rss',
            })
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        print(f"[US Stability RSS] {name}: error {str(e)[:100]}")
        return []


def _fetch_gdelt(query, max_records=30):
    """Fetch GDELT articles for a query. Returns list of articles."""
    try:
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        params = {
            'query':       f'{query} sourcecountry:US',
            'mode':        'artlist',
            'maxrecords':  max_records,
            'format':      'json',
            'timespan':    '7d',
        }
        resp = requests.get(url, params=params,
                            timeout=(5, 10),    # connect, read
                            headers={'User-Agent': 'AsifahAnalytics/1.0'})
        if resp.status_code == 429:
            print(f"[US Stability GDELT] rate-limited")
            return []
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = data.get('articles', [])
        return [{
            'title':       a.get('title', ''),
            'description': '',
            'link':        a.get('url', ''),
            'published':   a.get('seendate', ''),
            'source':      f"GDELT/{a.get('domain', 'unknown')}",
            'source_type': 'gdelt',
        } for a in articles]
    except Exception as e:
        print(f"[US Stability GDELT] error {str(e)[:100]}")
        return []


def _fetch_newsapi(query, max_records=30):
    """Fetch NewsAPI articles for a query. Returns list of articles."""
    if not NEWSAPI_KEY:
        return []
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            'q':         query,
            'language':  'en',
            'sortBy':    'publishedAt',
            'pageSize':  max_records,
            'apiKey':    NEWSAPI_KEY,
        }
        # Constrain to last 7 days
        from_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%d')
        params['from'] = from_date
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = data.get('articles', [])
        return [{
            'title':       a.get('title', '') or '',
            'description': a.get('description', '') or '',
            'link':        a.get('url', ''),
            'published':   a.get('publishedAt', ''),
            'source':      f"NewsAPI/{(a.get('source') or {}).get('name', 'unknown')}",
            'source_type': 'newsapi',
        } for a in articles if a.get('title')]
    except Exception as e:
        print(f"[US Stability NewsAPI] error {str(e)[:100]}")
        return []


# ============================================================
# REDIS HELPERS
# ============================================================

def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5)
        body = resp.json()
        if body.get('result'):
            return json.loads(body['result'])
    except Exception as e:
        print(f"[US Stability] Redis get error: {str(e)[:100]}")
    return None


def _redis_set(key, value, ttl_seconds=CACHE_TTL_SECONDS):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl_seconds)}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(value, default=str),
            timeout=8)
        return resp.status_code == 200
    except Exception:
        return False


# ============================================================
# SIGNAL DETECTION
# ============================================================

def _detect_signals(articles, keyword_dimension):
    """Scan articles for keyword matches in a dimension's keyword set.

    Returns list of {category, pattern, weight, article} matches.
    Same article can match multiple categories.
    """
    matches = []
    for art in articles:
        haystack = (art.get('title', '') + ' ' + art.get('description', '')).lower()
        if not haystack.strip():
            continue
        for category, cfg in keyword_dimension.items():
            for pattern in cfg['patterns']:
                if pattern.lower() in haystack:
                    matches.append({
                        'category':                category,
                        'pattern':                 pattern,
                        'base_weight':             cfg['base_weight'],
                        'baseline_modifier_key':   cfg.get('baseline_modifier_key'),
                        'article':                 art,
                    })
                    break    # only one pattern per article per category
    return matches


def _extract_states(text):
    """Find U.S. state name mentions in text. Returns list of state codes."""
    text_lower = (text or '').lower()
    mentioned = []
    for code, name in US_STATES.items():
        if name.lower() in text_lower:
            mentioned.append(code)
    return mentioned


# ============================================================
# DIMENSION SCORING FUNCTIONS
# ============================================================

def score_economic_dimension():
    """Score Dimension 1 — Economic Stability.

    Returns: {score, band, indicators, top_signals, source: 'economic_indicators_us'}
    """
    if not ECON_AVAILABLE:
        return {
            'score':       50,
            'band':        score_to_band(50),
            'error':       'economic_indicators_us module not available',
            'indicators':  {},
            'top_signals': [],
        }

    try:
        econ_data = fetch_economic_indicators()
    except Exception as e:
        return {
            'score':       50,
            'band':        score_to_band(50),
            'error':       f'economic fetch failed: {str(e)[:100]}',
            'indicators':  {},
            'top_signals': [],
        }

    indicators = econ_data.get('indicators', {})
    scored = {}
    weighted_sum = 0.0
    weight_total = 0.0
    top_signals = []

    for indicator_id, ind in indicators.items():
        value = ind.get('value')
        if value is None:
            continue
        if indicator_id not in ECON_THRESHOLDS:
            continue
        stress = score_economic_indicator(indicator_id, value)
        if stress is None:
            continue
        # Tier weighting: top-tier 2x, expanded 1x
        tier_w = 2.0 if ind.get('tier') == 'top' else 1.0
        weighted_sum += stress * tier_w
        weight_total += tier_w
        scored[indicator_id] = {
            'name':   ind.get('name'),
            'value':  value,
            'unit':   ind.get('unit'),
            'stress_score': stress,
            'tier':   ind.get('tier'),
            'frame':  ind.get('frame'),
            'source': ind.get('source'),
        }
        # Surface high-stress indicators as top signals
        if stress >= 50:
            top_signals.append({
                'short_text':  f"{ind.get('name')}: {value} {ind.get('unit', '')}",
                'long_text':   ind.get('frame', '') + f" Current: {value} {ind.get('unit', '')}.",
                'level':       3 if stress >= 70 else 2 if stress >= 50 else 1,
                'level_name':  'crisis' if stress >= 70 else 'elevated' if stress >= 50 else 'monitor',
                'category':    'econ_indicator',
                'icon':        '📉',
                'priority':    int(stress / 10),
            })

    final_score = round(weighted_sum / weight_total) if weight_total > 0 else 50

    # Sort top signals by priority
    top_signals.sort(key=lambda s: -s['priority'])

    return {
        'dimension':   'economic',
        'score':       final_score,
        'band':        score_to_band(final_score),
        'indicators':  scored,
        'top_signals': top_signals[:5],
        'source':      f"FRED + Yahoo ({len(scored)} indicators scored)",
        'fetched_at':  econ_data.get('fetched_at'),
        'fred_configured': econ_data.get('fred_configured'),
    }


def _score_keyword_dimension(dimension_id, keyword_set, articles, baseline_modifiers):
    """Generic scorer for keyword-based dimensions (Political, Civil, Democratic, Cyber).

    Returns: {score, band, top_signals, signals_detected, articles_scanned}
    """
    matches = _detect_signals(articles, keyword_set)

    # Aggregate by category
    category_data = {}
    for m in matches:
        cat = m['category']
        if cat not in category_data:
            category_data[cat] = {
                'count':       0,
                'weight':      m['base_weight'],
                'modifier':    1.0,
                'modifier_key': m['baseline_modifier_key'],
                'sample_articles': [],
                'states':      set(),
            }
        category_data[cat]['count'] += 1
        # Apply baseline modifier
        if m['baseline_modifier_key'] and baseline_modifiers:
            category_data[cat]['modifier'] = baseline_modifiers.get(
                m['baseline_modifier_key'], 1.0)
        # Sample article (up to 3 per category)
        if len(category_data[cat]['sample_articles']) < 3:
            category_data[cat]['sample_articles'].append({
                'title':     m['article'].get('title', ''),
                'link':      m['article'].get('link', ''),
                'source':    m['article'].get('source', ''),
                'pattern':   m['pattern'],
            })
        # Aggregate state mentions
        states_in_article = _extract_states(
            m['article'].get('title', '') + ' ' + m['article'].get('description', ''))
        category_data[cat]['states'].update(states_in_article)

    # Compute dimension score
    # Each category contributes: count * base_weight * modifier
    # Capped at 100; aggregated cumulatively but with diminishing returns
    raw_score = 0.0
    for cat, data in category_data.items():
        category_contribution = data['count'] * data['weight'] * data['modifier']
        # Diminishing returns: cap individual category at 35 points
        raw_score += min(35, category_contribution)
    # Cap total at 100
    final_score = min(100, round(raw_score))

    # Build top signals from highest-impact categories
    top_signals = []
    sorted_cats = sorted(category_data.items(),
                         key=lambda x: -x[1]['count'] * x[1]['weight'] * x[1]['modifier'])
    for cat, data in sorted_cats[:5]:
        impact = data['count'] * data['weight'] * data['modifier']
        if impact < 5:
            continue
        level = 3 if impact >= 30 else 2 if impact >= 15 else 1
        level_name = 'crisis' if level == 3 else 'elevated' if level == 2 else 'monitor'
        top_signals.append({
            'short_text':  f"{cat.replace('_', ' ').title()}: {data['count']} signal(s)",
            'long_text':   (f"{data['count']} signal(s) detected in {cat.replace('_', ' ')} "
                            f"category. Weight {data['weight']} × modifier {data['modifier']:.2f}. "
                            f"States mentioned: {', '.join(sorted(data['states'])) or 'national'}."),
            'level':       level,
            'level_name':  level_name,
            'category':    f'{dimension_id}_{cat}',
            'icon':        '⚡' if level == 3 else '🔶' if level == 2 else '🔸',
            'priority':    int(impact),
            'sample_articles': data['sample_articles'],
        })

    # Convert sets to sorted lists for JSON serialization
    cat_data_serializable = {}
    for cat, data in category_data.items():
        cat_data_serializable[cat] = {
            **{k: v for k, v in data.items() if k != 'states'},
            'states': sorted(data['states']),
        }

    return {
        'dimension':       dimension_id,
        'score':           final_score,
        'band':            score_to_band(final_score),
        'top_signals':     top_signals,
        'category_data':   cat_data_serializable,
        'signals_detected': len(matches),
        'articles_scanned': len(articles),
    }


def score_political_cohesion(articles, baseline_modifiers):
    """Score Dimension 2 — Political Cohesion."""
    return _score_keyword_dimension(
        'political_cohesion', POLITICAL_COHESION_KEYWORDS, articles, baseline_modifiers)


def score_civil_social(articles, baseline_modifiers):
    """Score Dimension 3 — Civil/Social Stability."""
    return _score_keyword_dimension(
        'civil_social', CIVIL_SOCIAL_KEYWORDS, articles, baseline_modifiers)


def score_democratic_institutions(articles, baseline_modifiers):
    """Score Dimension 4 — Democratic Institutions."""
    return _score_keyword_dimension(
        'democratic_institutions', DEMOCRATIC_INSTITUTIONS_KEYWORDS, articles, baseline_modifiers)


def score_cyber_infrastructure(articles, baseline_modifiers):
    """Score Dimension 6 — Cyber/Infrastructure."""
    return _score_keyword_dimension(
        'cyber_infrastructure', CYBER_INFRA_KEYWORDS, articles, baseline_modifiers)


def score_military_posture():
    """Score Dimension 5 — Military Posture.

    Reads from military:us:posture Redis fingerprint (the contract built
    earlier today in military_tracker.py v3.x).
    """
    us_posture = _redis_get('military:us:posture')
    cross_refs = {}
    for label in ['nato_us_active', 'us_venezuela_active', 'us_cuba_active',
                  'us_panama_active', 'us_greenland_active']:
        cr = _redis_get(f'military:cross:{label}')
        if cr:
            cross_refs[label] = cr

    if not us_posture:
        # Cold start — no military fingerprint available
        return {
            'dimension':   'military_posture',
            'score':       40,
            'band':        score_to_band(40),
            'top_signals': [],
            'mil_fingerprint': None,
            'cross_references': cross_refs,
            'note':        'Military posture fingerprint not yet available (cold start or mil tracker not deployed).',
        }

    # Extract score from posture (mil tracker peaks ~200; map to 0-100)
    raw_score = us_posture.get('score', 0)
    stability_score = min(100, round(raw_score / 2))

    # Surface top mil signals
    top_signals = []
    mil_top = us_posture.get('top_signals', [])
    for sig in mil_top[:3]:
        top_signals.append({
            'short_text':  f"🪖 {sig.get('asset_label', 'Mil signal')}: {sig.get('actor_name', '')}",
            'long_text':   f"{sig.get('article_title', '')[:200]} (weight {sig.get('weight', 0)}, "
                            f"location: {sig.get('hotspot_location', 'unspecified')})",
            'level':       3 if sig.get('weight', 0) >= 8 else 2 if sig.get('weight', 0) >= 5 else 1,
            'level_name':  'crisis' if sig.get('weight', 0) >= 8 else 'elevated' if sig.get('weight', 0) >= 5 else 'monitor',
            'category':    'mil_us_posture',
            'icon':        '🪖',
            'priority':    int(sig.get('weight', 0)),
        })

    # Add cross-reference signals
    for label, cr_data in cross_refs.items():
        if cr_data and cr_data.get('active'):
            top_signals.append({
                'short_text':  f"🔗 Cross-reference: {label.replace('_', ' ')}",
                'long_text':   f"Military cross-reference signal active: {label}. "
                                f"{cr_data.get('rationale', '')}",
                'level':       2,
                'level_name':  'elevated',
                'category':    'mil_cross_ref',
                'icon':        '🔗',
                'priority':    5,
            })

    return {
        'dimension':         'military_posture',
        'score':             stability_score,
        'band':              score_to_band(stability_score),
        'top_signals':       top_signals,
        'mil_fingerprint':   us_posture,
        'cross_references':  cross_refs,
        'mil_alert_level':   us_posture.get('alert_level'),
        'evac_active':       us_posture.get('evac_active', False),
    }


# ============================================================
# COMPOSITE SCORING
# ============================================================

def compute_composite_score(dimension_scores, election_cycle):
    """Compute weighted composite score from 6 dimensions.

    Applies election-cycle stability_modifier as final multiplier.
    Capped at 100.
    """
    composite_raw = 0.0
    for dim_id, weight in DIMENSION_WEIGHTS.items():
        dim = dimension_scores.get(dim_id, {})
        score = dim.get('score', 50)
        composite_raw += score * weight

    cycle_modifier = (election_cycle or {}).get('stability_modifier', 1.0)
    composite_final = min(100, round(composite_raw * cycle_modifier))

    return {
        'score':            composite_final,
        'raw_score':        round(composite_raw, 1),
        'cycle_modifier':   cycle_modifier,
        'band':             score_to_band(composite_final),
        'weights_applied':  DIMENSION_WEIGHTS,
    }


# ============================================================
# 30-DAY HISTORY MANAGEMENT
# ============================================================

def update_history(composite_score):
    """Append today's composite score to 30-day history.

    History stored as list of {date, score, band} dicts. One entry per day;
    if today already has an entry, it's overwritten with latest.
    """
    history = _redis_get(HISTORY_KEY) or {'snapshots': []}
    snapshots = history.get('snapshots', [])
    today_str = datetime.now(timezone.utc).date().isoformat()

    # Remove any existing entry for today
    snapshots = [s for s in snapshots if s.get('date') != today_str]

    # Add today's entry
    snapshots.append({
        'date':  today_str,
        'score': composite_score['score'],
        'band':  composite_score['band']['band'],
    })

    # Sort by date and keep only last 30 days
    snapshots.sort(key=lambda s: s['date'])
    snapshots = snapshots[-HISTORY_DAYS:]

    history['snapshots'] = snapshots
    history['updated_at'] = datetime.now(timezone.utc).isoformat()
    _redis_set(HISTORY_KEY, history, ttl_seconds=90 * 24 * 3600)    # 90-day TTL safety
    return history


# ============================================================
# CROSS-TRACKER FINGERPRINT WRITES
# ============================================================

def write_stability_fingerprint(scan_result):
    """Write a compressed stability fingerprint for GPI consumption.

    Schema:
      stability:us:fingerprint = {
        'composite_score':  int 0-100,
        'composite_band':   'resilient' | 'stressed' | 'fractured' | 'crisis_mode' | 'constitutional_crisis',
        'dimension_scores': {economic: int, political_cohesion: int, ...},
        'election_phase':   string,
        'unified_government': bool,
        'top_signals_count': int,
        'updated_at':       ISO timestamp,
      }
    """
    composite = scan_result.get('composite', {})
    dimensions = scan_result.get('dimensions', {})

    fingerprint = {
        'composite_score':    composite.get('score', 50),
        'composite_band':     composite.get('band', {}).get('band', 'stressed'),
        'composite_label':    composite.get('band', {}).get('label', 'Stressed'),
        'dimension_scores':   {dim_id: dim.get('score', 50)
                                for dim_id, dim in dimensions.items()},
        'election_phase':     scan_result.get('election_cycle', {}).get('phase'),
        'unified_government': scan_result.get('structural_baseline', {}).get('unified_government'),
        'top_signals_count':  len(scan_result.get('top_signals', [])),
        'updated_at':         datetime.now(timezone.utc).isoformat(),
    }
    _redis_set(FINGERPRINT_KEY, fingerprint, ttl_seconds=CACHE_TTL_SECONDS)
    _redis_set(SUMMARY_KEY, {
        'score':  fingerprint['composite_score'],
        'band':   fingerprint['composite_band'],
        'updated_at': fingerprint['updated_at'],
    }, ttl_seconds=CACHE_TTL_SECONDS)
    return fingerprint


# ============================================================
# MAIN SCAN
# ============================================================

def run_stability_scan():
    """Run a full US stability scan. Returns the complete scan_result dict."""
    print("[US Stability] === Starting full scan ===")
    scan_start = time.time()

    # ── Fetch government composition + structural baseline ──
    if GOVT_AVAILABLE:
        govt = get_government_composition()
    else:
        govt = {
            'congress':            {},
            'executive':           {},
            'election_cycle':      {'phase': 'regular', 'stability_modifier': 1.0},
            'structural_baseline': {
                'unified_government':  False,
                'baseline_modifiers':  {},
            },
        }
    structural_baseline = govt.get('structural_baseline', {})
    baseline_modifiers = structural_baseline.get('baseline_modifiers', {})
    election_cycle = govt.get('election_cycle', {})

    # ── Aggregate articles from all sources ──
    print("[US Stability] Phase 1: fetching articles...")
    all_articles = []

    # RSS feeds
    for name, url in US_STABILITY_RSS:
        articles = _fetch_rss(name, url)
        all_articles.extend(articles)
        time.sleep(0.2)    # gentle pacing

    print(f"[US Stability] RSS: {len(all_articles)} articles")

    # GDELT queries (one per dimension to avoid hammering)
    gdelt_queries = [
        '("court order" OR "inspector general" OR "civil service")',
        '("mass shooting" OR "active shooter" OR "protest")',
        '("cabinet" OR "secretary resigns" OR "shutdown")',
        '("ransomware" OR "cyberattack" OR "infrastructure")',
    ]
    for q in gdelt_queries:
        gdelt_articles = _fetch_gdelt(q, max_records=15)
        all_articles.extend(gdelt_articles)
        time.sleep(0.5)

    # NewsAPI fallback
    if NEWSAPI_KEY:
        for q in ['"court order" defied United States',
                  '"mass shooting" United States',
                  '"cabinet" OR "secretary fired" United States',
                  '"ransomware" United States']:
            na = _fetch_newsapi(q, max_records=10)
            all_articles.extend(na)

    pre_social_count = len(all_articles)
    print(f"[US Stability] Pre-social article pool: {pre_social_count}")

    # ── Social media signals (Bluesky / Telegram / Reddit) ──
    # Each call is independently try/except-wrapped so one source failing
    # never breaks the scan. All three return the standard article shape.

    # Bluesky (US gov, journalists, foreign view) — fetch_bluesky_for_target
    # returns posts in WHA-backend schema; transform `url` → `link` + tag
    # source_type='bluesky' so the frontend Bluesky&Telegram tab catches them.
    if BLUESKY_US_AVAILABLE:
        try:
            bluesky_raw = fetch_bluesky_for_target('us', days=7, max_posts_per_account=20)
            bluesky_articles = []
            for p in bluesky_raw:
                bluesky_articles.append({
                    'title':       p.get('title') or p.get('text') or '',
                    'description': p.get('text') or p.get('description') or '',
                    'link':        p.get('url') or p.get('link') or '',
                    'published':   p.get('publishedAt') or p.get('published') or '',
                    'source':      p.get('source') or f"Bluesky/{p.get('handle','unknown')}",
                    'source_type': 'bluesky',
                })
            all_articles.extend(bluesky_articles)
            print(f"[US Stability] Bluesky: +{len(bluesky_articles)} posts")
        except Exception as e:
            print(f"[US Stability] Bluesky fetch error: {str(e)[:200]}")

    # Telegram (Israeli/UK/AJ press, US incident trackers)
    if TELEGRAM_US_AVAILABLE:
        try:
            telegram_raw = fetch_telegram_signals_us(hours_back=7 * 24)
            telegram_articles = []
            for p in telegram_raw:
                telegram_articles.append({
                    'title':       p.get('title') or p.get('text') or '',
                    'description': p.get('text') or p.get('description') or '',
                    'link':        p.get('url') or p.get('link') or '',
                    'published':   p.get('publishedAt') or p.get('published') or p.get('date') or '',
                    'source':      p.get('source') or f"Telegram/{p.get('channel','unknown')}",
                    'source_type': 'telegram',
                })
            all_articles.extend(telegram_articles)
            print(f"[US Stability] Telegram: +{len(telegram_articles)} posts")
        except Exception as e:
            print(f"[US Stability] Telegram fetch error: {str(e)[:200]}")

    # Reddit (cross-spectrum political + civil/social + military + economic + cyber)
    # Already returns articles in the standard shape; no transform needed.
    if REDDIT_US_AVAILABLE:
        try:
            reddit_articles = fetch_reddit_signals_us(days=7, max_per_sub=25)
            all_articles.extend(reddit_articles)
            print(f"[US Stability] Reddit: +{len(reddit_articles)} posts")
        except Exception as e:
            print(f"[US Stability] Reddit fetch error: {str(e)[:200]}")

    social_added = len(all_articles) - pre_social_count
    print(f"[US Stability] Social signal total: +{social_added} posts "
          f"(article pool now {len(all_articles)})")

    # Deduplicate by link
    seen_links = set()
    unique_articles = []
    for a in all_articles:
        link = a.get('link', '')
        if link and link not in seen_links:
            seen_links.add(link)
            unique_articles.append(a)
    all_articles = unique_articles

    print(f"[US Stability] Total deduplicated: {len(all_articles)} articles")

    # ── Score each dimension ──
    print("[US Stability] Phase 2: scoring dimensions...")
    dimensions = {
        'economic':                score_economic_dimension(),
        'political_cohesion':      score_political_cohesion(all_articles, baseline_modifiers),
        'civil_social':            score_civil_social(all_articles, baseline_modifiers),
        'democratic_institutions': score_democratic_institutions(all_articles, baseline_modifiers),
        'military_posture':        score_military_posture(),
        'cyber_infrastructure':    score_cyber_infrastructure(all_articles, baseline_modifiers),
    }

    # ── Composite score ──
    composite = compute_composite_score(dimensions, election_cycle)

    # ── Top signals across all dimensions (canonical schema for GPI) ──
    all_top_signals = []
    for dim_id, dim in dimensions.items():
        for sig in dim.get('top_signals', []):
            sig_copy = dict(sig)
            sig_copy['dimension'] = dim_id
            all_top_signals.append(sig_copy)
    all_top_signals.sort(key=lambda s: -s.get('priority', 0))
    top_signals = all_top_signals[:10]

    # ── State-level signal aggregation ──
    state_signals = {}
    for dim_id in ['political_cohesion', 'civil_social',
                    'democratic_institutions', 'cyber_infrastructure']:
        cat_data = (dimensions.get(dim_id, {}) or {}).get('category_data', {})
        for cat, data in cat_data.items():
            for state in data.get('states', []):
                state_signals[state] = state_signals.get(state, 0) + data['count']

    # ── Build scan result ──
    elapsed = round(time.time() - scan_start, 1)
    scan_result = {
        'success':              True,
        'composite':            composite,
        'dimensions':           dimensions,
        'top_signals':          top_signals,
        'state_signals':        state_signals,
        'election_cycle':       election_cycle,
        'structural_baseline':  structural_baseline,
        'government_data_freshness': govt.get('data_freshness'),
        'staleness_warning':    govt.get('staleness_warning'),
        'articles_scanned':     len(all_articles),
        'scan_time_seconds':    elapsed,
        'last_updated':         datetime.now(timezone.utc).isoformat(),
        'version':              '1.0.0',
    }

    # ── Update 30-day history ──
    update_history(composite)

    # ── Write cross-tracker fingerprint ──
    write_stability_fingerprint(scan_result)

    # ── Cache ──
    _redis_set(CACHE_KEY, scan_result)

    print(f"[US Stability] ✅ Scan complete in {elapsed}s — composite "
          f"{composite['score']} {composite['band']['label']} "
          f"({len(top_signals)} top signals across {len(state_signals)} states)")

    return scan_result


def get_stability_data(force_refresh=False):
    """Get current US stability data (cache-aware)."""
    if not force_refresh:
        cached = _redis_get(CACHE_KEY)
        if cached:
            return cached
    return run_stability_scan()


# ============================================================
# BACKGROUND SCAN MANAGEMENT
# ============================================================

def _trigger_background_scan():
    """Trigger an async background scan (non-blocking)."""
    global _scan_running
    with _scan_lock:
        if _scan_running:
            print("[US Stability] Background scan already running, skipping")
            return
        _scan_running = True

    def _bg():
        global _scan_running
        try:
            run_stability_scan()
        except Exception as e:
            print(f"[US Stability] Background scan error: {str(e)[:200]}")
            import traceback
            traceback.print_exc()
        finally:
            with _scan_lock:
                _scan_running = False

    threading.Thread(target=_bg, daemon=True).start()


def _periodic_scanner():
    """Background thread that runs scans every SCAN_INTERVAL_HOURS."""
    # Initial 90-second delay to let the app fully boot
    time.sleep(90)
    while True:
        try:
            print("[US Stability] Periodic scan starting...")
            run_stability_scan()
        except Exception as e:
            print(f"[US Stability] Periodic scan error: {str(e)[:200]}")
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


def start_periodic_scanner():
    """Start the background periodic scanner thread."""
    t = threading.Thread(target=_periodic_scanner, daemon=True, name='us-stability-scanner')
    t.start()
    print(f"[US Stability] ✅ Periodic scanner started "
          f"(interval: {SCAN_INTERVAL_HOURS}h)")


# ============================================================
# FLASK ENDPOINT REGISTRATION
# ============================================================

def register_us_stability_endpoints(app):
    """Register all /api/us-stability endpoints."""
    from flask import jsonify, request

    @app.route('/api/us-stability', methods=['GET', 'OPTIONS'])
    def api_us_stability():
        if request.method == 'OPTIONS':
            return '', 200
        try:
            force = request.args.get('refresh', 'false').lower() == 'true'
            if force:
                _trigger_background_scan()
            data = get_stability_data(force_refresh=False)
            if not data:
                return jsonify({'success': False,
                                'error': 'No data — first scan in progress.'}), 503
            return jsonify(data)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/us-stability/dimension/<dim_id>', methods=['GET'])
    def api_us_stability_dimension(dim_id):
        try:
            data = get_stability_data(force_refresh=False)
            if not data or dim_id not in data.get('dimensions', {}):
                return jsonify({'success': False,
                                'error': f'Dimension {dim_id} not found'}), 404
            return jsonify(data['dimensions'][dim_id])
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/us-stability/history', methods=['GET'])
    def api_us_stability_history():
        try:
            history = _redis_get(HISTORY_KEY) or {'snapshots': []}
            return jsonify(history)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/us-stability/debug', methods=['GET'])
    def api_us_stability_debug():
        cached = _redis_get(CACHE_KEY)
        history = _redis_get(HISTORY_KEY)
        fingerprint = _redis_get(FINGERPRINT_KEY)
        return jsonify({
            'version':                '1.0.0',
            'redis_configured':       bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured':     bool(NEWSAPI_KEY),
            'brave_configured':       bool(BRAVE_API_KEY),
            'econ_module_available':  ECON_AVAILABLE,
            'govt_module_available':  GOVT_AVAILABLE,
            'cache_present':          bool(cached),
            'cache_last_updated':     (cached or {}).get('last_updated'),
            'cache_composite_score':  (cached or {}).get('composite', {}).get('score'),
            'cache_articles_scanned': (cached or {}).get('articles_scanned'),
            'history_snapshots':      len((history or {}).get('snapshots', [])),
            'fingerprint_present':    bool(fingerprint),
            'fingerprint_data':       fingerprint,
            'dimension_weights':      DIMENSION_WEIGHTS,
            'rss_feed_count':         len(US_STABILITY_RSS),
            'scan_interval_hours':    SCAN_INTERVAL_HOURS,
        })

    print("[US Stability] ✅ Endpoints registered: /api/us-stability, "
          "/dimension/<id>, /history, /debug")


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == '__main__':
    """Self-test — runs synthetic test against fake articles."""
    print("\n" + "=" * 60)
    print("US STABILITY — SELF-TEST")
    print("=" * 60)

    # Test 1: Score-to-band mapping
    print("\n=== Test 1: Score-to-band mapping ===")
    for score in [10, 35, 55, 75, 95]:
        band = score_to_band(score)
        print(f"  Score {score:3} → {band['icon']} {band['label']} ({band['band']})")

    # Test 2: Economic indicator scoring
    print("\n=== Test 2: Economic indicator scoring ===")
    test_cases = [
        ('cpi_yoy',       2.0, 'Below Fed target'),
        ('cpi_yoy',       3.5, 'Stressed inflation'),
        ('cpi_yoy',       7.0, 'Crisis-level inflation'),
        ('unemployment',  3.5, 'Below 4%'),
        ('unemployment',  6.0, 'Fractured'),
        ('mortgage_30yr', 6.5, 'Mid-stressed'),
        ('mortgage_30yr', 9.0, 'Crisis-level'),
        ('gas_price',     3.50, 'Stressed'),
        ('gas_price',     5.50, 'Crisis'),
    ]
    for ind, val, label in test_cases:
        score = score_economic_indicator(ind, val)
        band = score_to_band(score) if score else None
        print(f"  {ind:18s} = {val:6} ({label:25s}) → score {score:3} {band['label'] if band else '?'}")

    # Test 3: Synthetic keyword detection
    print("\n=== Test 3: Synthetic keyword detection ===")
    test_articles = [
        {'title': 'Mass shooting at high school in Texas leaves multiple casualties',
         'description': 'Active shooter incident at Houston-area school',
         'source': 'AP', 'link': 'https://example.com/1'},
        {'title': 'Cabinet shakeup as Secretary of State resigns abruptly',
         'description': 'Acting secretary will fill role until nominee confirmed',
         'source': 'NPR', 'link': 'https://example.com/2'},
        {'title': 'Federal judge held in contempt as administration defied court order',
         'description': 'Judge ruled administration ignored ruling on immigration',
         'source': 'NYT', 'link': 'https://example.com/3'},
        {'title': 'Major ransomware attack on US healthcare system reported',
         'description': 'CISA issued emergency alert; hospitals across multiple states affected',
         'source': 'Reuters', 'link': 'https://example.com/4'},
        {'title': 'Thousands gathered for No Kings Movement protest in Washington',
         'description': 'Demonstration drew estimated 50,000 in DC and major cities',
         'source': 'WaPo', 'link': 'https://example.com/5'},
        {'title': 'Inspector General fired by White House — third in two months',
         'description': 'Whistleblower retaliation alleged by oversight groups',
         'source': 'Politico', 'link': 'https://example.com/6'},
    ]

    # Use unified-R baseline modifiers (current state)
    test_baseline_modifiers = {
        'cabinet_turnover_weight':         1.3,
        'agency_leadership_churn_weight':  1.3,
        'court_orders_defied_weight':      1.4,
        'partisan_deadlock_weight':        1.5,
        'inspector_general_dismissal':     1.4,
        'civil_service_purge_weight':      1.3,
    }

    pol = score_political_cohesion(test_articles, test_baseline_modifiers)
    civ = score_civil_social(test_articles, test_baseline_modifiers)
    dem = score_democratic_institutions(test_articles, test_baseline_modifiers)
    cyb = score_cyber_infrastructure(test_articles, test_baseline_modifiers)

    print(f"  Political Cohesion:        score {pol['score']:3} ({pol['band']['label']}) — "
          f"{pol['signals_detected']} signals detected")
    print(f"  Civil/Social:              score {civ['score']:3} ({civ['band']['label']}) — "
          f"{civ['signals_detected']} signals detected")
    print(f"  Democratic Institutions:   score {dem['score']:3} ({dem['band']['label']}) — "
          f"{dem['signals_detected']} signals detected")
    print(f"  Cyber/Infrastructure:      score {cyb['score']:3} ({cyb['band']['label']}) — "
          f"{cyb['signals_detected']} signals detected")

    print("\n  Top signals from Civil/Social:")
    for s in civ['top_signals'][:3]:
        print(f"    {s['icon']} [{s['level_name']}] {s['short_text']}")

    # Test 4: Composite scoring
    print("\n=== Test 4: Composite scoring ===")
    fake_dimensions = {
        'economic':                {'score': 55},
        'political_cohesion':      {'score': pol['score']},
        'civil_social':            {'score': civ['score']},
        'democratic_institutions': {'score': dem['score']},
        'military_posture':        {'score': 65},
        'cyber_infrastructure':    {'score': cyb['score']},
    }
    fake_cycle = {'stability_modifier': 1.15, 'phase': 'primary_season'}
    comp = compute_composite_score(fake_dimensions, fake_cycle)
    print(f"  Composite score:    {comp['score']} ({comp['band']['label']})")
    print(f"  Raw score:          {comp['raw_score']}")
    print(f"  Cycle modifier:     {comp['cycle_modifier']}x (primary_season)")
    print(f"  Band description:   {comp['band']['description']}")

    print("\n✅ SELF-TEST COMPLETE")
