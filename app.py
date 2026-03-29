"""
Asifah Analytics -- Western Hemisphere Backend v1.0.0
March 2026

Flask backend for the Western Hemisphere (SOUTHCOM) regional dashboard.
Covers: Venezuela, Cuba, Haiti, Panama, Colombia, Mexico, Brazil, United States

ARCHITECTURE:
  - Upstash Redis (REST via requests) -- persistent cache across Render cold starts
  - /tmp file fallback when Redis unavailable
  - Background refresh every 12 hours (daemon thread)
  - force=true query param bypasses cache for manual OSINT scans
  - Military tracker module integrated (same as ME backend)

ENDPOINTS:
  /health                              -- service health check
  /api/wha/threat/<country>            -- conflict probability + OSINT scan
  /api/wha/threat/<country>?force=true -- force rescan (OSINT button)
  /api/wha/stability/<country>         -- stability summary card data
  /api/military-posture                -- military tracker (all theatres)
  /api/military-posture/<target>       -- military posture for specific target

COUNTRIES:
  venezuela, cuba, haiti, panama, colombia, mexico, brazil, us

CONFLICT % BASE SCORES (higher = worse):
  haiti      85  -- failed state, MSS gang territorial control
  venezuela  70  -- post-Maduro transition, armed factions, US involvement
  cuba       45  -- declining regime, blackouts, protest suppression
  colombia   40  -- ELN/FARC active, state functioning
  mexico     38  -- cartel military ops, state not collapsed
  brazil     20  -- regional power, low kinetic risk
  panama     18  -- functioning state, Canal sovereignty pressure
  us         12  -- scaffold only, full scoring Phase 2

COPYRIGHT 2025-2026 Asifah Analytics. All rights reserved.
Not for operational use.
"""

# ========================================
# IMPORTS
# ========================================
import os
import json
import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS

# ========================================
# FLASK APP INIT
# ========================================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ========================================
# CONFIGURATION
# ========================================

VERSION = '1.0.0'

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
GDELT_BASE_URL      = 'https://api.gdeltproject.org/api/v2/doc/doc'

CACHE_TTL_HOURS     = 12
CACHE_FILE_DIR      = '/tmp'

# Supported countries
WHA_COUNTRIES = [
    'venezuela', 'cuba', 'haiti', 'panama',
    'colombia', 'mexico', 'brazil', 'us'
]

# ========================================
# MILITARY TRACKER — proxied from ME backend
# ========================================
ME_BACKEND = 'https://asifah-backend.onrender.com'
MILITARY_AVAILABLE = True
print('[WHA Backend] Military tracker proxied from ME backend')

# ========================================
# UPSTASH REDIS HELPERS
# (REST pattern -- mirrors ME/Asia backends)
# ========================================

def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5
        )
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
    except Exception as e:
        print(f'[WHA Redis] GET error for {key}: {e}')
    return None


def _redis_set(key, value, ttl_seconds=None):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    if ttl_seconds is None:
        ttl_seconds = CACHE_TTL_HOURS * 3600
    try:
        payload = json.dumps(value, default=str)
        resp = requests.post(
            f'{UPSTASH_REDIS_URL}/set/{key}',
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json'
            },
            data=payload,
            params={'EX': ttl_seconds},
            timeout=5
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f'[WHA Redis] SET error for {key}: {e}')
    return False


# ========================================
# FILE CACHE FALLBACK
# ========================================

def _file_cache_path(key):
    safe_key = key.replace(':', '_')
    return Path(CACHE_FILE_DIR) / f'wha_{safe_key}.json'


def _file_get(key):
    try:
        p = _file_cache_path(key)
        if p.exists():
            with open(p, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f'[WHA FileCache] GET error for {key}: {e}')
    return None


def _file_set(key, value):
    try:
        p = _file_cache_path(key)
        with open(p, 'w') as f:
            json.dump(value, f, default=str)
    except Exception as e:
        print(f'[WHA FileCache] SET error for {key}: {e}')


def cache_get(key):
    result = _redis_get(key)
    if result:
        print(f'[WHA Cache] Redis hit: {key}')
        return result
    result = _file_get(key)
    if result:
        print(f'[WHA Cache] File hit: {key}')
    return result


def cache_set(key, value):
    value['cached_at'] = datetime.now(timezone.utc).isoformat()
    ok = _redis_set(key, value)
    if ok:
        print(f'[WHA Cache] Redis write: {key}')
    _file_set(key, value)


def is_cache_fresh(cached_data, max_hours=None):
    if not cached_data or 'cached_at' not in cached_data:
        return False
    if max_hours is None:
        max_hours = CACHE_TTL_HOURS
    try:
        cached_at = datetime.fromisoformat(cached_data['cached_at'])
        age = datetime.now(timezone.utc) - cached_at
        return age.total_seconds() < (max_hours * 3600)
    except Exception:
        return False


# ========================================
# COUNTRY CONFIGURATIONS
# ========================================

COUNTRY_CONFIG = {
    'venezuela': {
        'name': 'Venezuela',
        'flag': '🇻🇪',
        'base_conflict_pct': 70,
        'context': 'Post-Maduro transition state. Armed factions competing for power. US DEA/military involvement. Narco-military nexus.',
        'labels': {
            'low':    'Stable Transition',
            'medium': 'Transition Stress',
            'high':   'Conflict Risk',
            'surge':  'Active Crisis'
        },
        'gdelt_queries_en': [
            'venezuela military transition maduro',
            'venezuela armed factions power struggle',
            'venezuela colectivos armed violence',
            'venezuela DEA operation military',
            'venezuela US military sanctions',
            'tren de aragua venezuela violence',
            'venezuela cuba military cooperation',
            'venezuela crisis instability',
            'venezuela opposition military',
            'venezuela protest crackdown',
        ],
        'gdelt_queries_es': [
            'venezuela crisis militar transicion',
            'venezuela colectivos armados violencia',
            'venezuela fuerzas armadas faccion',
            'venezuela maduro capturado detenido',
            'venezuela tren de aragua crimen',
        ],
        'newsapi_queries': [
            'Venezuela military transition instability',
            'Venezuela armed groups violence crisis',
            'Venezuela US DEA military operation',
            'Venezuela Maduro regime collapse',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=venezuela+military+OR+maduro+transition+OR+crisis&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=venezuela+armed+groups+OR+colectivos+OR+tren+de+aragua&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'civil war', 'armed conflict', 'military coup', 'power struggle',
            'colectivos attack', 'armed factions', 'us military venezuela',
            'dea operation venezuela', 'regime collapse', 'government collapse',
            'maduro arrested', 'maduro captured', 'venezuela war',
            # Transition chaos (v1.1.0 — post-Maduro)
            'maduro extradited', 'maduro detention', 'maduro trial',
            'venezuela transition', 'venezuela new government',
            'venezuela unrest', 'venezuela crisis', 'venezuela violence',
            'colectivos', 'pro-maduro militia', 'venezuela militia',
            'venezuela political prisoners', 'venezuela opposition',
            'venezuela sanctions', 'venezuela oil embargo',
            'venezuela humanitarian', 'venezuela food shortage',
            'nicolas maduro', 'chavismo', 'psuv',
        ],
        'keywords_stability': [
            'venezuela peace', 'venezuela ceasefire', 'venezuela agreement',
            'venezuela election', 'venezuela transition government',
            'venezuela negotiations', 'venezuela humanitarian aid',
        ],
        'score_modifiers': {
            'transition_chaos': -15,
            'us_military_presence': -8,
            'armed_faction_activity': -12,
            'narco_military': -10,
            'international_support': +5,
            'ceasefire_agreement': +10,
        }
    },

    'cuba': {
        'name': 'Cuba',
        'flag': '🇨🇺',
        'base_conflict_pct': 45,
        'context': 'Declining regime stability. Chronic blackouts fueling unrest. Russian/Chinese military interest. Protest suppression ongoing.',
        'labels': {
            'low':    'Stable',
            'medium': 'Stressed',
            'high':   'Unstable',
            'surge':  'Crisis'
        },
        'gdelt_queries_en': [
            'cuba protests military crackdown',
            'cuba regime stability crisis',
            'russia cuba military base',
            'china cuba spy intelligence',
            'cuba economic collapse blackout',
            'cuba armed forces stability',
            'cuba dissidents arrested military',
            'cuba mass exodus instability',
        ],
        'gdelt_queries_es': [
            'cuba protestas represion militar',
            'cuba crisis economica apagon',
            'cuba militares estabilidad',
            'cuba detenidos presos politicos',
        ],
        'newsapi_queries': [
            'Cuba protests crackdown instability',
            'Cuba Russia military base Caribbean',
            'Cuba economic crisis blackouts unrest',
            'Cuba regime stability armed forces',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=cuba+protests+military+OR+crackdown+OR+instability&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=cuba+russia+military+OR+china+cuba+spy+base&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'cuba protests', 'cuba crackdown', 'cuba uprising', 'cuba unrest',
            'blackout protests', 'food shortage protests', 'cuba arrested',
            'russia cuba military', 'china cuba base', 'cuba economic collapse',
            'cuba mass exodus', 'july 11', 'cuba dissidents',
        ],
        'keywords_stability': [
            'cuba stability', 'cuba government control', 'cuba military loyal',
            'cuba economy recovering', 'cuba aid',
        ],
        'score_modifiers': {
            'protest_activity': -12,
            'foreign_military_presence': -8,
            'economic_collapse': -10,
            'blackout_unrest': -8,
            'regime_crackdown': -5,
            'government_stability': +8,
        }
    },

    'haiti': {
        'name': 'Haiti',
        'flag': '🇭🇹',
        'base_conflict_pct': 85,
        'context': 'Failed state. MSS/Viv Ansanm gang coalition controls majority of Port-au-Prince. Kenyan-led MSS security mission active. No functioning central government.',
        'labels': {
            'low':    'Reduced Violence',
            'medium': 'Active Gang War',
            'high':   'Crisis',
            'surge':  'Catastrophic'
        },
        'gdelt_queries_en': [
            'haiti gang violence MSS Viv Ansanm',
            'haiti Kenyan security mission',
            'haiti port-au-prince gang control',
            'haiti G9 gang attack police',
            'haiti government collapse security',
            'haiti multinational security force',
            'haiti gang weapons territory',
            'haiti hostage kidnapping',
            'haiti police overwhelmed gang',
            'haiti cite soleil violence',
        ],
        'gdelt_queries_es': [
            'haiti pandillas armadas violencia',
            'haiti mision seguridad kenia',
            'haiti crisis gobierno pandillas',
        ],
        'newsapi_queries': [
            'Haiti gang violence MSS security mission',
            'Haiti Kenyan police security force',
            'Haiti Viv Ansanm gang control',
            'Haiti government collapse instability',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=haiti+gang+violence+OR+mss+mission+OR+security&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=haiti+viv+ansanm+OR+g9+gang+OR+port-au-prince+security&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'gang attack', 'gang violence', 'gang control', 'gang seize',
            'gang massacre', 'viv ansanm', 'g9 gang', 'mss gang',
            'police overwhelmed', 'police retreat', 'government collapse',
            'port-au-prince attack', 'cite soleil', 'hostage', 'kidnapping',
            'haiti crisis', 'armed gang', 'gang territory',
        ],
        'keywords_stability': [
            'security mission progress', 'gang surrender', 'gang dismantled',
            'kenyan mission success', 'haiti police restored', 'gang arrested',
            'security restored', 'haiti ceasefire',
        ],
        'score_modifiers': {
            'gang_territorial_control': -20,
            'police_collapse': -15,
            'government_absence': -12,
            'mass_atrocity': -15,
            'security_mission_active': +8,
            'gang_retreat': +10,
            'international_support': +5,
        }
    },

    'panama': {
        'name': 'Panama',
        'flag': '🇵🇦',
        'base_conflict_pct': 18,
        'context': 'Functioning state. Canal sovereignty under political pressure. Chinese port presence at both ends of Canal. Darien Gap migration-security nexus.',
        'labels': {
            'low':    'Stable',
            'medium': 'Elevated Tension',
            'high':   'Political Crisis',
            'surge':  'Security Crisis'
        },
        'gdelt_queries_en': [
            'panama canal sovereignty military',
            'china panama canal port control',
            'trump panama canal pressure',
            'panama darien gap military security',
            'panama narco trafficking security',
            'panama political instability',
            'panama canal disruption threat',
            'us panama military relations',
        ],
        'gdelt_queries_es': [
            'panama canal soberania militar',
            'china canal panama control',
            'panama darien migracion seguridad',
            'panama narcotrafico militar',
        ],
        'newsapi_queries': [
            'Panama Canal sovereignty China military',
            'Trump Panama Canal pressure',
            'Panama Darien Gap security military',
            'Panama narco trafficking instability',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=panama+canal+military+OR+china+panama+OR+sovereignty&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'canal sovereignty crisis', 'china canal control', 'canal closure',
            'canal disruption', 'trump panama', 'us panama tension',
            'panama protest canal', 'darien crisis', 'narco panama attack',
            'canal military threat', 'canal seized',
        ],
        'keywords_stability': [
            'canal operating normally', 'panama stability', 'panama economy',
            'canal traffic normal', 'panama us relations stable',
        ],
        'score_modifiers': {
            'canal_sovereignty_pressure': -8,
            'chinese_influence': -6,
            'narco_activity': -5,
            'darien_crisis': -4,
            'us_military_support': +6,
            'canal_normal_ops': +5,
        }
    },

    'colombia': {
        'name': 'Colombia',
        'flag': '🇨🇴',
        'base_conflict_pct': 40,
        'context': 'ELN and FARC dissidents active. Functioning state conducting military operations. US military advisors present. Venezuela border tension.',
        'labels': {
            'low':    'Managed Conflict',
            'medium': 'Elevated Violence',
            'high':   'Conflict Surge',
            'surge':  'Crisis'
        },
        'gdelt_queries_en': [
            'colombia ELN attack military',
            'colombia FARC dissident operation',
            'colombia military operation guerrilla',
            'colombia US military advisors',
            'colombia venezuela border military',
            'colombia cartel clan del golfo',
            'colombia peace negotiation breakdown',
            'colombia security forces attack',
        ],
        'gdelt_queries_es': [
            'colombia eln ataque militar',
            'colombia farc disidentes operacion',
            'colombia ejercito operacion guerrilla',
            'colombia frontera venezuela militar',
            'colombia clan del golfo operacion',
        ],
        'newsapi_queries': [
            'Colombia ELN FARC military operation',
            'Colombia guerrilla attack security forces',
            'Colombia US military advisors',
            'Colombia Venezuela border violence',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=colombia+ELN+OR+FARC+military+OR+guerrilla+attack&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'eln attack', 'farc dissident', 'guerrilla attack', 'colombia bomb',
            'colombia ambush', 'colombia military casualties', 'pipeline attack',
            'colombia peace breakdown', 'colombia ceasefire collapse',
            'clan del golfo attack', 'colombia massacre',
        ],
        'keywords_stability': [
            'colombia ceasefire', 'colombia peace talks', 'colombia negotiations',
            'eln ceasefire', 'colombia security improvement', 'guerrilla surrender',
        ],
        'score_modifiers': {
            'eln_attack': -10,
            'farc_dissident_attack': -10,
            'us_military_support': +6,
            'ceasefire_active': +8,
            'peace_talks_progress': +6,
            'venezuela_border_tension': -5,
        }
    },

    'mexico': {
        'name': 'Mexico',
        'flag': '🇲🇽',
        'base_conflict_pct': 38,
        'context': 'Cartel military operations ongoing. Inward-facing conflict. CJNG and Sinaloa Cartel conducting military-style operations. US border pressure and cartel terrorist designation.',
        'labels': {
            'low':    'Baseline Violence',
            'medium': 'Elevated Cartel Activity',
            'high':   'Cartel Surge',
            'surge':  'Crisis'
        },
        'gdelt_queries_en': [
            'mexico cartel military operation',
            'CJNG sinaloa cartel attack',
            'mexico army cartel confrontation',
            'mexico cartel drone attack',
            'us mexico border military',
            'mexico cartel terrorist designation',
            'mexico fentanyl military operation',
            'mexico cartel massacre civilians',
            'mexico state capture cartel',
            'mexico police cartel corruption',
        ],
        'gdelt_queries_es': [
            'mexico cartel operacion militar',
            'cjng jalisco cartel ataque',
            'mexico ejercito cartel enfrentamiento',
            'narco drones mexico',
            'mexico guardia nacional cartel',
            'mexico masacre cartel civiles',
        ],
        'newsapi_queries': [
            'Mexico cartel military operation violence',
            'CJNG Sinaloa cartel attack military',
            'Mexico army cartel confrontation',
            'Mexico US border military deployment',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=mexico+cartel+military+OR+cjng+attack+OR+army+cartel&hl=en&gl=US&ceid=US:en',
            'https://news.google.com/rss/search?q=mexico+cartel+massacre+OR+drone+attack+OR+state+capture&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'cartel attack', 'cartel ambush', 'cartel massacre', 'cartel drone',
            'cjng attack', 'sinaloa attack', 'narco roadblock', 'cartel convoy',
            'mexico army casualties', 'cartel territory', 'state capture',
            'police cartel', 'mayor cartel', 'governor cartel',
            'mexico massacre', 'mass grave mexico',
        ],
        'keywords_stability': [
            'cartel arrested', 'cartel leader captured', 'cartel dismantled',
            'mexico security operation success', 'cartel surrender',
        ],
        'score_modifiers': {
            'cartel_military_ops': -12,
            'drone_attack': -8,
            'state_capture': -10,
            'us_military_pressure': -3,
            'cartel_leader_captured': +8,
            'security_operation_success': +5,
        }
    },

    'brazil': {
        'name': 'Brazil',
        'flag': '🇧🇷',
        'base_conflict_pct': 20,
        'context': 'Regional power. Low kinetic risk nationally. Amazon military operations active. PCC organized crime significant in urban areas. Democratic institutions stressed but holding.',
        'labels': {
            'low':    'Stable',
            'medium': 'Elevated',
            'high':   'Stressed',
            'surge':  'Crisis'
        },
        'gdelt_queries_en': [
            'brazil amazon military operation',
            'brazil armed forces exercise',
            'brazil organized crime PCC violence',
            'brazil political instability military',
            'brazil coup attempt military',
            'brazil favela military operation',
            'brazil venezuela border military',
            'brazil democratic institutions',
        ],
        'gdelt_queries_es': [
            'brasil militares operacion amazonia',
            'brasil crimen organizado pcc violencia',
            'brasil golpe militares',
            'brasil favela operacion policial',
        ],
        'newsapi_queries': [
            'Brazil Amazon military operation',
            'Brazil political instability military',
            'Brazil PCC organized crime violence',
            'Brazil armed forces exercise',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=brazil+military+OR+amazon+military+OR+armed+forces+operation&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            'brazil coup', 'military coup brazil', 'brazil political crisis',
            'pcc attack', 'brazil organized crime attack', 'brazil favela war',
            'brazil democratic crisis', 'brazil institutions crisis',
            'brazil amazon conflict', 'brazil border military conflict',
        ],
        'keywords_stability': [
            'brazil stability', 'brazil democracy', 'brazil economy',
            'brazil lula stability', 'brazil institutions', 'brazil elections',
        ],
        'score_modifiers': {
            'coup_attempt': -20,
            'political_crisis': -10,
            'organized_crime_surge': -8,
            'democratic_stability': +8,
            'military_loyalty': +6,
            'economy_stable': +5,
        }
    },

    'us': {
        'name': 'United States',
        'flag': '🇺🇸',
        'base_conflict_pct': 12,
        'context': 'SCAFFOLD -- Phase 2 full scoring. Tracks: economic indicators (S&P, gas, CPI), political cohesion, democratic institutions, military posture, social stability. Active combat operations in Iran (March 2026).',
        'labels': {
            'low':    'Resilient',
            'medium': 'Stressed',
            'high':   'Fractured',
            'surge':  'Constitutional Crisis'
        },
        'gdelt_queries_en': [
            'united states political instability',
            'us democratic institutions crisis',
            'us military operations iran',
            'us domestic unrest protests',
            'us economic crisis recession',
            'us constitutional crisis',
            'no kings protest united states',
            'anti trump protest rally',
            'mass protest washington dc',
            'nationwide protest demonstration',
            'us political protest crackdown',
            'trump executive order protest',
            'federal workers protest',
            'us tariffs economic impact',
            'us recession fears market',
        ],
        'gdelt_queries_es': [],
        'newsapi_queries': [
            'United States political instability crisis',
            'US democratic institutions stress',
            'US domestic unrest military',
        ],
        'rss_feeds': [
            'https://news.google.com/rss/search?q=united+states+political+crisis+OR+instability+OR+constitutional+crisis&hl=en&gl=US&ceid=US:en',
        ],
        'keywords_escalation': [
            # Protests / demonstrations (v1.1.0 — No Kings, anti-administration)
            'no kings protest', 'no kings rally', 'anti-trump protest',
            'protest washington', 'protest united states', 'mass protest',
            'nationwide protest', 'demonstration washington dc',
            'protest crackdown', 'protest arrested', 'protest violence',
            'rally washington', 'march washington', 'civil disobedience',
            # Political instability
            'constitutional crisis', 'democratic backsliding', 'political violence',
            'us civil unrest', 'institutional collapse', 'us martial law',
            'us government shutdown extended', 'debt default',
            'executive overreach', 'congress standoff', 'political crisis',
            'impeachment', 'federal standoff', 'state federal conflict',
            # Economic stress signals
            'market crash', 'recession fears', 'economic crisis united states',
            'tariff crisis', 'trade war escalation', 'federal layoffs',
        ],
        'keywords_stability': [
            'us economic recovery', 'bipartisan', 'democratic norms',
            'institutions holding', 'us stability',
        ],
        'score_modifiers': {
            'active_war_operations': -5,
            'political_crisis': -8,
            'economic_stress': -5,
            'institutional_stability': +8,
            'military_cohesion': +5,
        }
    }
}


# ========================================
# GDELT FETCH
# ========================================

def fetch_gdelt(query, days=7, language='eng', max_records=50):
    try:
        params = {
            'query': query,
            'mode': 'artlist',
            'maxrecords': max_records,
            'timespan': f'{days}d',
            'format': 'json',
            'sourcelang': language
        }
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=(5, 30))
        if resp.status_code == 429:
            print(f'[WHA GDELT] 429 rate limit -- skipping: {query[:40]}')
            return []
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = data.get('articles', [])
        return [{
            'title': a.get('title', ''),
            'url': a.get('url', ''),
            'source': a.get('domain', 'GDELT'),
            'published': a.get('seendate', ''),
            'content': a.get('title', ''),
            'feed_type': 'gdelt'
        } for a in articles]
    except Exception as e:
        print(f'[WHA GDELT] Error: {str(e)[:80]}')
        return []


# ========================================
# NEWSAPI FETCH
# ========================================

def fetch_newsapi(query, days=7):
    if not NEWSAPI_KEY:
        return []
    try:
        from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        resp = requests.get(
            'https://newsapi.org/v2/everything',
            params={
                'q': query,
                'from': from_date,
                'sortBy': 'publishedAt',
                'language': 'en',
                'apiKey': NEWSAPI_KEY,
                'pageSize': 30
            },
            timeout=(5, 15)
        )
        if resp.status_code != 200:
            return []
        articles = resp.json().get('articles', [])
        return [{
            'title': a.get('title', ''),
            'url': a.get('url', ''),
            'source': a.get('source', {}).get('name', 'NewsAPI'),
            'published': a.get('publishedAt', ''),
            'content': (a.get('description') or '') + ' ' + (a.get('title') or ''),
            'feed_type': 'newsapi'
        } for a in articles]
    except Exception as e:
        print(f'[WHA NewsAPI] Error: {str(e)[:80]}')
        return []


# ========================================
# RSS FETCH
# ========================================

def fetch_rss(feed_url, max_items=15):
    import xml.etree.ElementTree as ET
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; AsifahAnalytics/1.0)'}
        resp = requests.get(feed_url, headers=headers, timeout=(5, 15))
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        items = root.findall('.//item')
        articles = []
        for item in items[:max_items]:
            title_el = item.find('title')
            link_el  = item.find('link')
            desc_el  = item.find('description')
            if title_el is None:
                continue
            articles.append({
                'title': title_el.text or '',
                'url': link_el.text if link_el is not None else '',
                'source': feed_url.split('/')[2],
                'published': '',
                'content': (desc_el.text or '') if desc_el is not None else '',
                'feed_type': 'rss'
            })
        return articles
    except Exception as e:
        print(f'[WHA RSS] Error {feed_url[:50]}: {str(e)[:60]}')
        return []


# ========================================
# OSINT SCAN -- per country
# ========================================

def scan_country(country_id, days=7):
    config = COUNTRY_CONFIG.get(country_id)
    if not config:
        return None

    print(f'[WHA Scan] Scanning {country_id} ({days}d)...')
    all_articles = []

    # GDELT English
    for query in config['gdelt_queries_en']:
        articles = fetch_gdelt(query, days=days, language='eng')
        all_articles.extend(articles)
        time.sleep(0.5)

    # GDELT Spanish
    for query in config.get('gdelt_queries_es', []):
        articles = fetch_gdelt(query, days=days, language='spa')
        all_articles.extend(articles)
        time.sleep(0.5)

    # NewsAPI
    for query in config['newsapi_queries']:
        articles = fetch_newsapi(query, days=days)
        all_articles.extend(articles)
        time.sleep(0.3)

    # RSS feeds
    for feed_url in config['rss_feeds']:
        articles = fetch_rss(feed_url)
        all_articles.extend(articles)
        time.sleep(0.5)

    # Deduplicate by URL
    seen_urls = set()
    unique_articles = []
    for a in all_articles:
        url = a.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_articles.append(a)

    print(f'[WHA Scan] {country_id}: {len(unique_articles)} unique articles')

    # ---- Scoring ----
    base = config['base_conflict_pct']
    score = float(base)
    signals_found = []
    escalation_hits = []
    stability_hits  = []

    for article in unique_articles:
        text = (
            (article.get('title') or '') + ' ' +
            (article.get('content') or '')
        ).lower()

        # Escalation keywords
        for kw in config['keywords_escalation']:
            if kw.lower() in text:
                escalation_hits.append({
                    'keyword': kw,
                    'title': article.get('title', '')[:120],
                    'url': article.get('url', ''),
                    'source': article.get('source', ''),
                    'published': article.get('published', ''),
                    'feed_type': article.get('feed_type', '')
                })
                score = min(score + 1.5, 99)
                break

        # Stability keywords
        for kw in config['keywords_stability']:
            if kw.lower() in text:
                stability_hits.append({
                    'keyword': kw,
                    'title': article.get('title', '')[:120],
                    'url': article.get('url', ''),
                    'source': article.get('source', '')
                })
                score = max(score - 0.8, 1)
                break

    # Cap score
    score = round(max(1.0, min(99.0, score)), 1)

    # Conflict level label
    if score >= 75:
        level = 'surge'
        level_label = config['labels']['surge']
    elif score >= 55:
        level = 'high'
        level_label = config['labels']['high']
    elif score >= 35:
        level = 'medium'
        level_label = config['labels']['medium']
    else:
        level = 'low'
        level_label = config['labels']['low']

    # Top signals for frontend
    top_signals = sorted(escalation_hits, key=lambda x: x.get('published', ''), reverse=True)[:10]

    return {
        'success': True,
        'country': country_id,
        'country_name': config['name'],
        'flag': config['flag'],
        'conflict_probability': score,
        'level': level,
        'level_label': level_label,
        'context': config['context'],
        'articles_scanned': len(unique_articles),
        'escalation_signals': len(escalation_hits),
        'stability_signals': len(stability_hits),
        'top_signals': top_signals,
        'days_analyzed': days,
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'cached': False,
        'version': VERSION
    }


# ========================================
# BACKGROUND REFRESH
# ========================================

_scan_locks = {c: threading.Lock() for c in WHA_COUNTRIES}
_scan_running = {c: False for c in WHA_COUNTRIES}


def _background_scan_country(country_id, days=7):
    if _scan_running.get(country_id):
        print(f'[WHA Background] {country_id} scan already running, skipping')
        return
    with _scan_locks[country_id]:
        _scan_running[country_id] = True
    try:
        result = scan_country(country_id, days=days)
        if result:
            cache_set(f'wha:threat:{country_id}', result)
            print(f'[WHA Background] {country_id} cached OK')
    except Exception as e:
        print(f'[WHA Background] {country_id} error: {e}')
    finally:
        with _scan_locks[country_id]:
            _scan_running[country_id] = False


def _run_all_countries_background(days=7):
    for country_id in WHA_COUNTRIES:
        t = threading.Thread(
            target=_background_scan_country,
            args=(country_id, days),
            daemon=True
        )
        t.start()
        time.sleep(5)  # stagger starts to avoid GDELT rate limits


def _start_background_refresh():
    def _loop():
        # Initial boot delay
        print('[WHA Background] Boot delay 90s before first scan...')
        time.sleep(90)
        while True:
            try:
                print('[WHA Background] Starting full WHA scan...')
                _run_all_countries_background(days=7)
                print('[WHA Background] Full scan complete. Sleeping 12 hours.')
                time.sleep(12 * 3600)
            except Exception as e:
                print(f'[WHA Background] Loop error: {e}')
                time.sleep(3600)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print('[WHA Background] Refresh thread started (12hr cycle)')


# ========================================
# FLASK ENDPOINTS
# ========================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'service': 'asifah-wha-backend',
        'version': VERSION,
        'countries': WHA_COUNTRIES,
        'military_available': MILITARY_AVAILABLE,
        'redis_configured': bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
        'newsapi_configured': bool(NEWSAPI_KEY),
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/wha/threat/<country_id>', methods=['GET', 'OPTIONS'])
def api_wha_threat(country_id):
    if request.method == 'OPTIONS':
        return '', 200

    if country_id not in WHA_COUNTRIES:
        return jsonify({'success': False, 'error': f'Unknown country: {country_id}'}), 404

    force   = request.args.get('force', 'false').lower() == 'true'
    days    = int(request.args.get('days', 7))
    cache_key = f'wha:threat:{country_id}'

    # Serve cache if fresh and not forced
    if not force:
        cached = cache_get(cache_key)
        if cached and is_cache_fresh(cached, max_hours=CACHE_TTL_HOURS):
            cached['cached'] = True
            return jsonify(cached)
        # Stale cache -- return it and trigger background refresh
        if cached:
            cached['cached'] = True
            cached['stale']  = True
            threading.Thread(
                target=_background_scan_country,
                args=(country_id, days),
                daemon=True
            ).start()
            return jsonify(cached)

    # Force or no cache -- run scan now
    result = scan_country(country_id, days=days)
    if result:
        cache_set(cache_key, result)
        return jsonify(result)

    return jsonify({'success': False, 'error': 'Scan failed', 'country': country_id}), 500


@app.route('/api/wha/stability/<country_id>', methods=['GET', 'OPTIONS'])
def api_wha_stability(country_id):
    """Lightweight stability summary card -- reads from threat cache."""
    if request.method == 'OPTIONS':
        return '', 200

    if country_id not in WHA_COUNTRIES:
        return jsonify({'success': False, 'error': f'Unknown country: {country_id}'}), 404

    force = request.args.get('force', 'false').lower() == 'true'
    cache_key = f'wha:threat:{country_id}'

    cached = cache_get(cache_key)

    if cached and not force:
        config = COUNTRY_CONFIG.get(country_id, {})
        return jsonify({
            'success': True,
            'country': country_id,
            'country_name': cached.get('country_name', country_id),
            'flag': cached.get('flag', ''),
            'conflict_probability': cached.get('conflict_probability', config.get('base_conflict_pct', 50)),
            'level': cached.get('level', 'medium'),
            'level_label': cached.get('level_label', ''),
            'context': cached.get('context', config.get('context', '')),
            'articles_scanned': cached.get('articles_scanned', 0),
            'last_updated': cached.get('last_updated', ''),
            'cached': True,
            'version': VERSION
        })

    # No cache yet -- return baseline from config
    config = COUNTRY_CONFIG.get(country_id, {})
    base = config.get('base_conflict_pct', 50)
    if base >= 75:
        level, label = 'surge', config.get('labels', {}).get('surge', 'Crisis')
    elif base >= 55:
        level, label = 'high', config.get('labels', {}).get('high', 'High')
    elif base >= 35:
        level, label = 'medium', config.get('labels', {}).get('medium', 'Elevated')
    else:
        level, label = 'low', config.get('labels', {}).get('low', 'Stable')

    return jsonify({
        'success': True,
        'country': country_id,
        'country_name': config.get('name', country_id),
        'flag': config.get('flag', ''),
        'conflict_probability': base,
        'level': level,
        'level_label': label,
        'context': config.get('context', ''),
        'articles_scanned': 0,
        'last_updated': None,
        'cached': False,
        'scan_pending': True,
        'message': 'Initial scan in progress. Data will populate within 2-3 minutes.',
        'version': VERSION
    })


@app.route('/api/wha/countries', methods=['GET'])
def api_wha_countries():
    """Return summary of all WHA countries -- used by the WHA index page."""
    summaries = []
    for country_id in WHA_COUNTRIES:
        config = COUNTRY_CONFIG.get(country_id, {})
        cached = cache_get(f'wha:threat:{country_id}')
        base   = config.get('base_conflict_pct', 50)
        if cached:
            conflict_pct = cached.get('conflict_probability', base)
            level        = cached.get('level', 'medium')
            level_label  = cached.get('level_label', '')
            last_updated = cached.get('last_updated', '')
        else:
            conflict_pct = base
            level        = 'medium'
            level_label  = config.get('labels', {}).get('medium', 'Pending')
            last_updated = None

        summaries.append({
            'country': country_id,
            'country_name': config.get('name', country_id),
            'flag': config.get('flag', ''),
            'conflict_probability': conflict_pct,
            'level': level,
            'level_label': level_label,
            'last_updated': last_updated,
            'cached': bool(cached)
        })

    summaries.sort(key=lambda x: x['conflict_probability'], reverse=True)

    return jsonify({
        'success': True,
        'countries': summaries,
        'count': len(summaries),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'version': VERSION
    })


# ========================================
# MILITARY TRACKER ENDPOINTS
# ========================================

@app.route('/api/military-posture', methods=['GET', 'OPTIONS'])
def api_military_posture():
    if request.method == 'OPTIONS':
        return '', 200
    try:
        params = dict(request.args)
        resp = requests.get(
            f'{ME_BACKEND}/api/military-posture',
            params=params,
            timeout=(5, 60)
        )
        return app.response_class(
            response=resp.content,
            status=resp.status_code,
            mimetype='application/json'
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 503


@app.route('/api/military-posture/<target>', methods=['GET', 'OPTIONS'])
def api_military_posture_target(target):
    if request.method == 'OPTIONS':
        return '', 200
    try:
        params = dict(request.args)
        resp = requests.get(
            f'{ME_BACKEND}/api/military-posture/{target}',
            params=params,
            timeout=(5, 30)
        )
        return app.response_class(
            response=resp.content,
            status=resp.status_code,
            mimetype='application/json'
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:200]}), 503

print('[WHA Backend] Military tracker proxy endpoints registered')


# ========================================
# TRAVEL ADVISORY ENDPOINT
# ========================================

WHA_TRAVEL_ADVISORY_URLS = {
    'venezuela':  'https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/venezuela-travel-advisory.html',
    'cuba':       'https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/cuba-travel-advisory.html',
    'haiti':      'https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/haiti-travel-advisory.html',
    'panama':     'https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/panama-travel-advisory.html',
    'colombia':   'https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/colombia-travel-advisory.html',
    'mexico':     'https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/mexico-travel-advisory.html',
    'brazil':     'https://travel.state.gov/content/travel/en/traveladvisories/traveladvisories/brazil-travel-advisory.html',
    'us':         None,
}

ADVISORY_LEVEL_COLORS = {
    1: '#2563eb',
    2: '#d97706',
    3: '#ea580c',
    4: '#dc2626',
}

ADVISORY_LEVEL_SHORT = {
    1: 'Exercise Normal Precautions',
    2: 'Exercise Increased Caution',
    3: 'Reconsider Travel',
    4: 'Do Not Travel',
}

def _scrape_travel_advisory(country_id):
    url = WHA_TRAVEL_ADVISORY_URLS.get(country_id)
    if not url:
        return None
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; AsifahAnalytics/1.0)'}
        resp = requests.get(url, headers=headers, timeout=(5, 15))
        if resp.status_code != 200:
            return None
        text = resp.text

        # Extract level number
        level = 0
        for lvl in [4, 3, 2, 1]:
            if f'Level {lvl}' in text:
                level = lvl
                break

        if level == 0:
            return None

        return {
            'level': level,
            'level_short': ADVISORY_LEVEL_SHORT.get(level, 'See Advisory'),
            'level_color': ADVISORY_LEVEL_COLORS.get(level, '#6b7280'),
            'link': url,
            'recently_changed': 'recently changed' in text.lower() or 'updated' in text.lower(),
            'change_description': '',
            'country': country_id,
            'scraped_at': datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f'[WHA TA] Scrape error for {country_id}: {e}')
        return None


@app.route('/api/wha/travel-advisories', methods=['GET', 'OPTIONS'])
def api_wha_travel_advisories():
    if request.method == 'OPTIONS':
        return '', 200

    cache_key = 'wha:travel_advisories'
    force = request.args.get('force', 'false').lower() == 'true'

    if not force:
        cached = cache_get(cache_key)
        if cached and is_cache_fresh(cached, max_hours=6):
            cached['cached'] = True
            return jsonify(cached)

    advisories = {}
    for country_id in WHA_COUNTRIES:
        if country_id == 'us':
            continue
        result = _scrape_travel_advisory(country_id)
        if result:
            advisories[country_id] = result
        time.sleep(0.5)

    result = {
        'success': True,
        'advisories': advisories,
        'count': len(advisories),
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'cached': False
    }
    cache_set(cache_key, result)
    return jsonify(result)


# ========================================
# APP STARTUP
# ========================================

_start_background_refresh()

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
