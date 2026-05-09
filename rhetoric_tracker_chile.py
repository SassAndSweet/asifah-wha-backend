"""
rhetoric_tracker_chile.py
=========================================================
Chile Rhetoric Tracker v1.0.0 — Asifah Analytics
Built: May 9, 2026

7-actor rhetoric and pressure tracker for Chile, modeled on the Peru
tracker pattern (Apr 2026) but tuned to Chile's analytical distinctions:

  • More institutionally stable than Peru — `constitutional_politics`
    actor takes the structural-stability slot Peru's FFAA + VRAEM occupied
  • China posture is *cautious* (no Chancay-equivalent flagship); lithium
    dependency is structural — expect lower volume but more economically-
    loaded signals than Peru's Chancay/BRI tempo
  • Mapuche conflict has narrower geographic footprint (Araucanía /
    Biobío) but recurring violent incidents — analytically equivalent
    to Peru's VRAEM in salience but politically/legally distinct
    (autonomy-claim politics, not narco-insurgency)

ACTORS (7 total):
  1. presidency             — Boric admin / 2026 election context
  2. cancilleria             — MINREL / Pacific Alliance / regional posture
  3. mining_sector           — Codelco state + private (BHP, Anglo, Antofagasta)
                                + SQM / Albemarle lithium politics
  4. mapuche_conflict        — Araucanía / Biobío conflict zone
  5. constitutional_politics — post-2022/2023 referendum aftermath,
                                institutional drift, Congressional dynamics
  6. us_chile                — Embassy Santiago / SOUTHCOM / Pacific
                                Council / lithium strategic-minerals dialog / FTA
  7. china_chile             — lithium / copper investment / FTA review /
                                BRI ambivalence

ANALYTICAL VECTORS (4):
  • domestic_stability  = presidency + constitutional_politics + mapuche_conflict
  • resource_sector     = mining_sector
  • us_alignment        = us_chile
  • china_alignment     = china_chile

CROSS-TRACKER ARCHITECTURE:
  • READS  /api/wha/commodity-fingerprint/chile (copper + lithium supply-risk
    fingerprints, via WHA-local proxy with 1h TTL)
  • READS  rhetoric:china:latest, rhetoric:iran:latest, rhetoric:russia:latest
    sibling fingerprints from Asia / ME backends (China LAC, Iran LatAm,
    Hezbollah TBA — quiet tripwires, armed-and-watching by design)
  • WRITES chile_china_axis_active, chile_lithium_disruption,
    chile_copper_disruption, chile_constitutional_pressure for downstream
    consumers (regional BLUF, GPI)

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import threading
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

print("[Chile Rhetoric] Module loading...")

# ============================================
# CONFIGURATION
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY       = os.environ.get('BRAVE_API_KEY')

CACHE_KEY           = 'rhetoric:chile:latest'
CACHE_TTL_HOURS     = 13          # 12h refresh + 1h buffer
SCAN_INTERVAL_HOURS = 12

# WHA-local self URL — for reading commodity fingerprints from the WHA proxy
WHA_BACKEND_SELF_URL = os.environ.get(
    'WHA_BACKEND_SELF_URL',
    'http://localhost:10000'
)
COMMODITY_FINGERPRINT_AVAILABLE = True

# Cross-theater amplifier sibling tracker keys (Redis)
SIBLING_TRACKER_KEYS = {
    'china':    'rhetoric:china:latest',
    'iran':     'rhetoric:iran:latest',
    'russia':   'rhetoric:russia:latest',
}

# Optional signal interpreter (loaded lazily — if absent, tracker still works)
try:
    from chile_signal_interpreter import (
        build_top_signals as _interp_top_signals,
        build_executive_summary as _interp_exec_summary,
        build_so_what_factor as _interp_so_what,
    )
    INTERPRETER_AVAILABLE = True
    print("[Chile Rhetoric] ✅ Signal interpreter loaded")
except ImportError:
    INTERPRETER_AVAILABLE = False
    print("[Chile Rhetoric] ⚠️  Signal interpreter unavailable — tracker will emit raw fields only")


# ============================================
# ACTOR DEFINITIONS
# ============================================
# Each actor:
#   - name, flag, icon, role (for UI)
#   - vector (for 4-vector composite)
#   - keywords (mix of EN + ES for matching across feed languages)
#   - tripwires (low-base-rate high-impact patterns; severity 0-4)
#   - baseline (expected signal volume per week — used for level calibration)

ACTORS = {
    'presidency': {
        'name':     'Presidency',
        'flag':     '🇨🇱',
        'icon':     '🏛️',
        'role':     'Executive Branch / Boric Administration',
        'vector':   'domestic_stability',
        'baseline': 14,
        'keywords': [
            # English
            'boric', 'chilean president', 'chile president', 'la moneda',
            'chilean executive', 'boric administration', 'palacio de la moneda',
            'chile cabinet', 'chilean cabinet reshuffle',
            # Spanish — president direct
            'presidente boric', 'gabriel boric', 'la moneda',
            'gobierno de chile', 'gobierno chileno', 'ejecutivo chileno',
            'palacio de la moneda', 'gabinete', 'cambio de gabinete',
            # Election cycle (2026 generals)
            'elecciones chile 2026', 'chile 2026 election', 'chilean primary',
            'primarias chile', 'jara', 'kast', 'matthei', 'frente amplio',
            # Approval / political position
            'aprobación boric', 'boric approval', 'rechazo a boric',
            'chile poll', 'cadem', 'plaza pública',
        ],
        'tripwires': [
            ('boric_resignation',    4, ['renuncia boric', 'boric resigns', 'dimisión boric']),
            ('cabinet_collapse',     3, ['gabinete renuncia', 'cabinet collapses', 'cabinet resign en masse']),
            ('approval_cliff',       2, ['aprobación 20', 'aprobación 18', 'aprobación 15', 'approval crashes']),
        ],
    },
    'cancilleria': {
        'name':     'Cancillería (MINREL)',
        'flag':     '🇨🇱',
        'icon':     '🤝',
        'role':     'Foreign Ministry / Regional Posture',
        'vector':   'domestic_stability',
        'baseline': 8,
        'keywords': [
            # English
            'chilean foreign ministry', 'chile foreign minister',
            'minrel', 'pacific alliance chile', 'chilean diplomacy',
            'chile-bolivia relations', 'chile-peru relations',
            'chile-argentina relations', 'mercosur chile',
            # Spanish
            'cancillería chile', 'minrel', 'alberto van klaveren',
            'política exterior chile', 'alianza del pacífico',
            'relaciones bolivia chile', 'relaciones peru chile',
            'mercosur chile', 'unasur', 'celac',
            # Maritime / territorial
            'salida al mar bolivia', 'mar territorial chile',
            'demarcación', 'la haya chile', 'icj chile',
        ],
        'tripwires': [
            ('boundary_crisis',      3, ['crisis fronteriza', 'border crisis chile', 'incidente fronterizo']),
            ('icj_filing',           3, ['icj chile filing', 'la haya nuevo caso', 'corte internacional chile']),
        ],
    },
    'mining_sector': {
        'name':     'Mining Sector',
        'flag':     '🇨🇱',
        'icon':     '⛏️',
        'role':     'Codelco + Private (BHP / Anglo / Antofagasta) + SQM/Albemarle Lithium',
        'vector':   'resource_sector',
        'baseline': 18,
        'keywords': [
            # English — copper anchors
            'codelco', 'chuquicamata', 'el teniente', 'andina',
            'salvador mine', 'gabriela mistral mine',
            'escondida', 'bhp escondida', 'minera escondida',
            'collahuasi', 'los pelambres', 'antofagasta minerals',
            'quebrada blanca', 'spence', 'centinela',
            'anglo american chile', 'sur andes', 'los bronces',
            # English — lithium anchors
            'sqm chile', 'sociedad quimica minera',
            'albemarle chile', 'salar de atacama lithium',
            'codelco lithium', 'chile lithium nationalization',
            'national lithium strategy chile',
            # Spanish — copper
            'cobre chile', 'producción cobre chile',
            'codelco chuquicamata', 'mineros chile', 'sindicato cobre',
            'huelga minera chile', 'paralización minera',
            'precio cobre', 'cobre lme', 'comisión chilena del cobre', 'cochilco',
            # Spanish — lithium
            'litio chile', 'litio salar de atacama',
            'sociedad química y minera', 'sqm tianqi',
            'estrategia nacional litio', 'codelco litio',
            'corfo litio', 'royalty litio',
            # Strikes / labor
            'huelga codelco', 'huelga escondida', 'huelga el teniente',
            'paralización minera chile', 'strike codelco', 'strike escondida',
        ],
        'tripwires': [
            ('escondida_strike',          4, ['escondida strike', 'huelga escondida', 'paralización escondida']),
            ('codelco_strike',            4, ['codelco strike', 'huelga codelco', 'paralización codelco']),
            ('chuquicamata_disruption',   3, ['chuquicamata cierre', 'chuquicamata closure', 'chuquicamata suspension']),
            ('lithium_nationalization',   3, ['lithium nationalization', 'nacionalización litio', 'estatización litio']),
            ('mining_fatality',           3, ['minero muerto', 'mining fatality chile', 'accidente fatal mina']),
        ],
    },
    'mapuche_conflict': {
        'name':     'Mapuche Conflict',
        'flag':     '🇨🇱',
        'icon':     '🔥',
        'role':     'Araucanía / Biobío Conflict Zone',
        'vector':   'domestic_stability',
        'baseline': 9,
        'keywords': [
            # English
            'mapuche', 'araucania', 'wallmapu', 'cam mapuche',
            'arauco malleco', 'coordinadora arauco malleco',
            'temuco violence', 'biobio violence',
            'mapuche autonomy', 'mapuche territory claim',
            'chile indigenous conflict',
            # Spanish — direct
            'conflicto mapuche', 'pueblo mapuche', 'wallmapu',
            'cam coordinadora', 'cam arauco malleco',
            'estado de excepción araucanía', 'estado de excepción biobío',
            'macrozona sur', 'zonas conflictuadas',
            # Specific incidents / violence patterns
            'atentado mapuche', 'incendio camiones', 'quema de camiones',
            'usurpación de tierras', 'tomas de fundos',
            'helicóptero pdi', 'pdi araucanía',
            # Communities + leaders
            'temucuicui', 'lof temucuicui', 'héctor llaitul',
            'machi linconao', 'celestino córdova',
        ],
        'tripwires': [
            ('state_of_exception',    4, ['estado de excepción araucanía', 'state of exception araucania', 'estado de excepción macrozona']),
            ('mass_arson',            3, ['quema masiva', 'incendios coordinados', 'mass arson araucania']),
            ('mapuche_fatality',      3, ['mapuche muerto', 'comunero muerto', 'mapuche killed']),
            ('cam_attack',            3, ['atentado cam', 'cam attack', 'coordinadora atentado']),
        ],
    },
    'constitutional_politics': {
        'name':     'Constitutional Politics',
        'flag':     '🇨🇱',
        'icon':     '⚖️',
        'role':     'Post-Referendum Aftermath / Congressional Dynamics',
        'vector':   'domestic_stability',
        'baseline': 11,
        'keywords': [
            # English
            'chilean constitution', 'chile constitution', 'constitutional referendum chile',
            'constitutional convention chile', 'rejection vote 2022',
            'constitutional council chile', 'rejection 2023',
            'chile congressional dynamics', 'chilean senate',
            'chile chamber of deputies', 'chile congress',
            'chile pension reform', 'chile pension afp',
            'chile tax reform', 'chile fiscal pact',
            # Spanish
            'constitución chile', 'nueva constitución chile',
            'plebiscito constitucional', 'rechazo plebiscito',
            'consejo constitucional', 'comisión experta',
            'cámara de diputados', 'senado chile', 'congreso chile',
            'reforma de pensiones', 'reforma previsional chile',
            'afp chile', 'reforma tributaria', 'pacto fiscal',
            # Constitutional crisis / executive-legislative friction
            'acusación constitucional', 'impeachment chile',
            'censura ministro', 'destitución ministro',
            'oposición chilena', 'partidos oposición',
        ],
        'tripwires': [
            ('impeachment_vote',         4, ['acusación constitucional aprobada', 'impeachment passed chile']),
            ('cabinet_minister_ousted',  3, ['ministro destituido', 'minister ousted chile', 'censura ministro aprobada']),
            ('major_reform_collapse',    2, ['reforma previsional rechazada', 'pension reform rejected', 'reforma tributaria rechazada']),
        ],
    },
    'us_chile': {
        'name':     'US-Chile Bilateral',
        'flag':     '🇺🇸',
        'icon':     '🤝',
        'role':     'Embassy Santiago / SOUTHCOM / Strategic Minerals / FTA',
        'vector':   'us_alignment',
        'baseline': 7,
        'keywords': [
            # English
            'us chile relations', 'embassy santiago', 'us embassy chile',
            'southcom chile', 'pacific council chile',
            'chile fta', 'us chile free trade agreement',
            'strategic minerals dialogue', 'chile lithium united states',
            'chile critical minerals', 'irna chile',
            'usaid chile', 'us state department chile',
            'antofagasta basing', 'us military chile',
            # Spanish
            'relaciones eeuu chile', 'embajada eeuu chile',
            'embajador eeuu chile', 'tlc estados unidos chile',
            'minerales críticos chile', 'minerales estratégicos',
            'ejercicios conjuntos chile', 'unitas chile', 'pacific dragon',
            'cooperación bilateral chile estados unidos',
            # USAID — historical context only (dissolved 2025)
            'usaid chile historical', 'former usaid chile',
        ],
        'tripwires': [
            ('strategic_minerals_pact', 3, ['us chile critical minerals agreement', 'pacto minerales críticos chile estados unidos']),
            ('ambassador_recall',       4, ['embajador retirado', 'ambassador recalled chile']),
            ('joint_exercise_friction', 2, ['ejercicio conjunto cancelado', 'joint exercise canceled chile']),
        ],
    },
    'china_chile': {
        'name':     'China-Chile Bilateral',
        'flag':     '🇨🇳',
        'icon':     '🐉',
        'role':     'Lithium / Copper Investment / FTA Review / BRI Ambivalence',
        'vector':   'china_alignment',
        'baseline': 9,
        'keywords': [
            # English
            'china chile relations', 'chile china fta',
            'tianqi sqm', 'tianqi chile', 'tianqi lithium',
            'ganfeng lithium chile', 'byd chile',
            'china investment chile', 'huawei chile',
            'china belt and road chile', 'chile bri',
            'beijing chile bilateral', 'xi jinping chile',
            'china strait of magellan', 'china magellan',
            # Spanish
            'relaciones china chile', 'tlc china chile',
            'tianqi sqm', 'inversión china chile',
            'huawei chile', 'belt and road chile',
            'cumbre china chile', 'embajador china chile',
            'cooperación china chile', 'comercio china chile',
            # Strategic infrastructure
            'cable submarino transpacific', 'humboldt cable',
            'puerto san antonio china', 'puerto valparaíso china',
            'observatorio chino chile', 'estación espacial china',
            # Lithium specifically
            'tianqi sqm 24%', 'china lithium chile',
            'ganfeng codelco', 'byd salar maricunga',
        ],
        'tripwires': [
            ('chinese_naval_visit',     3, ['china naval chile', 'pla navy chile', 'buque chino chile']),
            ('major_infra_milestone',   3, ['china port chile groundbreaking', 'cable transpacífico inauguración']),
            ('fta_renegotiation',       2, ['fta china chile renegotiation', 'tlc china chile renegociación']),
        ],
    },
}

# ============================================
# VECTOR DEFINITIONS
# ============================================
VECTORS = {
    'domestic_stability': {
        'name': 'Domestic Stability',
        'actors': ['presidency', 'cancilleria', 'mapuche_conflict', 'constitutional_politics'],
    },
    'resource_sector': {
        'name': 'Resource-Sector Politics',
        'actors': ['mining_sector'],
    },
    'us_alignment': {
        'name': 'US Alignment',
        'actors': ['us_chile'],
    },
    'china_alignment': {
        'name': 'China Alignment',
        'actors': ['china_chile'],
    },
}


# ============================================
# RSS FEEDS — Native Chilean Spanish + regional
# ============================================
RSS_FEEDS = {
    'la_tercera':  {'url': 'https://www.latercera.com/feed/',                            'name': 'La Tercera',         'language': 'es'},
    'el_mercurio': {'url': 'https://www.emol.com/sindicacion/rss.asp?canal=44',          'name': 'El Mercurio (Emol)', 'language': 'es'},
    'biobio':      {'url': 'https://www.biobiochile.cl/lista_de_noticias.rss',           'name': 'BioBioChile',        'language': 'es'},
    'cooperativa': {'url': 'https://www.cooperativa.cl/noticias/site/tax/port/all/rss_2-1.xml', 'name': 'Cooperativa',  'language': 'es'},
    'reuters_la':  {'url': 'https://www.reutersagency.com/feed/?best-regions=latin-america&post_type=best',
                    'name': 'Reuters LatAm', 'language': 'en'},
}


# ============================================
# GDELT QUERIES — English + Spanish
# ============================================
GDELT_QUERIES_EN = [
    'Chile Boric',                    'Chile cabinet reshuffle',
    'Codelco strike',                 'Escondida strike',
    'Chile mining sector',            'Chile lithium nationalization',
    'SQM Tianqi',                     'Albemarle Chile',
    'Mapuche Araucania',              'Chile state of exception',
    'Chile constitutional reform',    'Chile pension reform',
    'US Chile critical minerals',     'Chile FTA review',
    'China Chile investment',         'Tianqi SQM stake',
]

GDELT_QUERIES_ES = [
    'Boric gabinete',                 'cambio gabinete Chile',
    'huelga Codelco',                 'huelga Escondida',
    'litio Chile nacionalización',    'estrategia nacional litio',
    'mapuche Araucanía',              'estado excepción Araucanía',
    'reforma previsional Chile',      'reforma constitucional',
    'acusación constitucional',       'cancillería Chile',
    'inversión china Chile',          'tianqi SQM',
    'minerales críticos Chile',
]


# ============================================
# ALERT-LEVEL CALIBRATION
# ============================================
def actor_alert_level(score, baseline):
    """Map a weighted score to a categorical alert level."""
    if baseline <= 0: baseline = 1
    ratio = score / baseline
    if ratio >= 2.5:  return 'surge'
    if ratio >= 1.7:  return 'high'
    if ratio >= 1.1:  return 'elevated'
    if ratio >= 0.4:  return 'normal'
    return 'low'


# ============================================
# REDIS HELPERS
# ============================================
def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        body = resp.json()
        if body.get('result'):
            return json.loads(body['result'])
    except Exception as e:
        print(f"[Chile Rhetoric] Redis get error ({key}): {str(e)[:120]}")
    return None


def _redis_set(key, value, ttl_hours=CACHE_TTL_HOURS):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        url = f"{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl_hours * 3600)}"
        resp = requests.post(
            url,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            data=json.dumps(value, default=str),
            timeout=8,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Chile Rhetoric] Redis set error ({key}): {str(e)[:120]}")
        return False


def load_cache():
    return _redis_get(CACHE_KEY)


def save_cache(data):
    return _redis_set(CACHE_KEY, data, ttl_hours=CACHE_TTL_HOURS)


def is_cache_fresh(data):
    if not data or 'scanned_at' not in data:
        return False
    try:
        scanned = datetime.fromisoformat(data['scanned_at'])
        age_hours = (datetime.now(timezone.utc) - scanned).total_seconds() / 3600
        return age_hours < SCAN_INTERVAL_HOURS
    except Exception:
        return False


# ============================================
# SIGNAL FETCHERS — RSS / GDELT / NewsAPI / Brave
# ============================================
def fetch_rss_articles(feed_id, feed_config, max_articles=30):
    """Fetch + parse one RSS feed."""
    out = []
    try:
        parsed = feedparser.parse(feed_config['url'])
        for entry in parsed.entries[:max_articles]:
            out.append({
                'title':    entry.get('title', '')[:300],
                'url':      entry.get('link', ''),
                'source':   feed_config['name'],
                'language': feed_config['language'],
                'published': entry.get('published', ''),
                'feed_type': 'rss',
            })
    except Exception as e:
        print(f"[Chile Rhetoric] RSS error ({feed_id}): {str(e)[:120]}")
    return out


def fetch_all_rss():
    all_articles = []
    for feed_id, cfg in RSS_FEEDS.items():
        all_articles.extend(fetch_rss_articles(feed_id, cfg))
    print(f"[Chile Rhetoric] RSS: {len(all_articles)} articles")
    return all_articles


def fetch_gdelt_query(query, language='eng', days=7, max_articles=50):
    out = []
    try:
        url = (
            "https://api.gdeltproject.org/api/v2/doc/doc"
            f"?query={requests.utils.quote(query)}"
            f"&mode=ArtList&format=json&maxrecords={max_articles}"
            f"&timespan={days}d&sourcelang={language}"
        )
        resp = requests.get(url, timeout=(5, 15))
        if resp.status_code == 429:
            return []
        if resp.status_code != 200:
            return []
        body = resp.json()
        for art in body.get('articles', []):
            out.append({
                'title':     (art.get('title') or '')[:300],
                'url':       art.get('url', ''),
                'source':    art.get('domain', 'GDELT'),
                'language':  language[:2] if language else 'en',
                'published': art.get('seendate', ''),
                'feed_type': 'gdelt',
            })
    except Exception:
        pass
    return out


def fetch_all_gdelt(days=7):
    out = []
    for q in GDELT_QUERIES_EN:
        out.extend(fetch_gdelt_query(q, language='eng', days=days))
        time.sleep(0.5)
    for q in GDELT_QUERIES_ES:
        out.extend(fetch_gdelt_query(q, language='spa', days=days))
        time.sleep(0.5)
    print(f"[Chile Rhetoric] GDELT: {len(out)} articles")
    return out


def fetch_newsapi(query, days=7):
    if not NEWSAPI_KEY:
        return []
    try:
        from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
        resp = requests.get(
            'https://newsapi.org/v2/everything',
            params={
                'q': query, 'from': from_date, 'sortBy': 'relevancy',
                'pageSize': 50, 'apiKey': NEWSAPI_KEY,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        body = resp.json()
        out = []
        for art in body.get('articles', []):
            out.append({
                'title':     (art.get('title') or '')[:300],
                'url':       art.get('url', ''),
                'source':    (art.get('source') or {}).get('name', 'NewsAPI'),
                'language':  'en',
                'published': art.get('publishedAt', ''),
                'feed_type': 'newsapi',
            })
        return out
    except Exception:
        return []


def fetch_all_newsapi(days=7):
    out = []
    for q in ['Chile mining', 'Boric Chile', 'Mapuche Chile', 'Codelco', 'SQM lithium', 'Chile constitutional']:
        out.extend(fetch_newsapi(q, days=days))
        time.sleep(0.3)
    print(f"[Chile Rhetoric] NewsAPI: {len(out)} articles")
    return out


def fetch_brave(query, days=7):
    if not BRAVE_API_KEY:
        return []
    try:
        resp = requests.get(
            'https://api.search.brave.com/res/v1/news/search',
            params={'q': query, 'count': 20, 'freshness': 'pw'},
            headers={'X-Subscription-Token': BRAVE_API_KEY},
            timeout=8,
        )
        if resp.status_code != 200:
            return []
        body = resp.json()
        out = []
        for art in body.get('results', []):
            out.append({
                'title':     (art.get('title') or '')[:300],
                'url':       art.get('url', ''),
                'source':    (art.get('meta_url') or {}).get('hostname', 'Brave'),
                'language':  'en',
                'published': art.get('age', ''),
                'feed_type': 'brave',
            })
        return out
    except Exception:
        return []


def fetch_all_brave(days=7, gdelt_count=0, newsapi_count=0):
    """Brave fires only as fallback when GDELT + NewsAPI are weak."""
    if (gdelt_count + newsapi_count) >= 30:
        return []
    out = []
    for q in ['Chile mining strike', 'Boric Chile politics', 'Mapuche Araucania', 'Chile lithium SQM']:
        out.extend(fetch_brave(q, days=days))
        time.sleep(0.5)
    print(f"[Chile Rhetoric] Brave: {len(out)} articles")
    return out


# ============================================
# ARTICLE → ACTOR CLASSIFICATION
# ============================================
def _normalize_text(text):
    return (text or '').lower()


def _classify_article_actor(article):
    """Match article against actor keywords; return list of matched actors."""
    text = _normalize_text((article.get('title') or '') + ' ' + (article.get('source') or ''))
    matches = []
    for actor_id, cfg in ACTORS.items():
        for kw in cfg['keywords']:
            if kw.lower() in text:
                matches.append(actor_id)
                break
    return matches


def _check_tripwires(text):
    """Return list of (actor_id, tripwire_id, severity) for any pattern match."""
    text = _normalize_text(text)
    fired = []
    for actor_id, cfg in ACTORS.items():
        for tw in cfg.get('tripwires', []):
            tw_id, severity, patterns = tw
            for pat in patterns:
                if pat.lower() in text:
                    fired.append((actor_id, tw_id, severity))
                    break
    return fired


def _score_actor_articles(articles_for_actor, actor_id):
    """Compute a simple weighted score for an actor's article batch."""
    if not articles_for_actor:
        return 0.0
    score = 0.0
    seen_urls = set()
    for art in articles_for_actor:
        url = art.get('url', '')
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # Weight by source type
        ft = art.get('feed_type', '')
        if ft == 'rss':
            score += 1.5
        elif ft == 'gdelt':
            score += 1.0
        elif ft == 'newsapi':
            score += 1.2
        elif ft == 'brave':
            score += 1.0
        else:
            score += 1.0
    return round(score, 2)


# ============================================
# CROSS-TRACKER READS
# ============================================
def _read_commodity_pressure_for_chile():
    """Read commodity supply-risk fingerprints for Chile (copper + lithium)
    via WHA-local commodity proxy. 1h-cached. Graceful degrade on error."""
    try:
        url = f"{WHA_BACKEND_SELF_URL}/api/wha/commodity-fingerprint/chile"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        return data.get('fingerprints', {}) or {}
    except Exception as e:
        print(f"[Chile Rhetoric] commodity proxy read error: {str(e)[:120]}")
        return {}


def _read_crosstheater_amplifiers():
    """Read sibling-tracker fingerprints from Asia/ME/Russia trackers.
    These trigger cross-theater amplification when active."""
    amplifiers = {}
    for theatre, key in SIBLING_TRACKER_KEYS.items():
        sibling = _redis_get(key)
        if not sibling:
            continue
        # Generic amplifier extraction — looks for known keys
        if theatre == 'china':
            if sibling.get('china_lac_active') or sibling.get('china_bri_latam'):
                amplifiers['china_lac_active'] = {'active': True, 'level': 'elevated'}
            if sibling.get('china_bri_latam'):
                amplifiers['china_bri_latam'] = {'active': True, 'level': 'elevated'}
        if theatre == 'iran':
            if sibling.get('iran_latam_active') or sibling.get('iran_hezbollah_tba'):
                amplifiers['iran_latam_active'] = {'active': True, 'level': 'elevated'}
            if sibling.get('iran_hezbollah_tba'):
                amplifiers['iran_hezbollah_tba'] = {'active': True, 'level': 'elevated'}
    return amplifiers


def _write_chile_fingerprints(actor_levels, vector_scores, tripwires_global):
    """Write Chile-side fingerprints to Redis for downstream consumers."""
    try:
        china_lvl = actor_levels.get('china_chile', 'low')
        if china_lvl in ('elevated', 'high', 'surge'):
            _redis_set('chile_china_axis_active',
                       {'active': True, 'level': china_lvl,
                        'scanned_at': datetime.now(timezone.utc).isoformat()},
                       ttl_hours=CACHE_TTL_HOURS)

        if any(t[1] in ('lithium_nationalization', 'codelco_strike', 'escondida_strike',
                        'chuquicamata_disruption') for t in tripwires_global):
            _redis_set('chile_lithium_disruption' if any(t[1] == 'lithium_nationalization' for t in tripwires_global)
                       else 'chile_copper_disruption',
                       {'active': True, 'tripwires': [t[1] for t in tripwires_global],
                        'scanned_at': datetime.now(timezone.utc).isoformat()},
                       ttl_hours=CACHE_TTL_HOURS)

        if any(t[1] in ('impeachment_vote', 'cabinet_minister_ousted',
                        'major_reform_collapse') for t in tripwires_global):
            _redis_set('chile_constitutional_pressure',
                       {'active': True, 'tripwires': [t[1] for t in tripwires_global],
                        'scanned_at': datetime.now(timezone.utc).isoformat()},
                       ttl_hours=CACHE_TTL_HOURS)
    except Exception as e:
        print(f"[Chile Rhetoric] fingerprint write error: {str(e)[:120]}")


# ============================================
# MAIN SCAN
# ============================================
def scan_chile_rhetoric(force=False, days=7):
    """Full scan: fetch → classify → score → tripwires → interpret → cache."""
    if not force:
        cached = load_cache()
        if cached and is_cache_fresh(cached):
            cached['cached'] = True
            return cached

    scan_start = time.time()
    print(f"[Chile Rhetoric] Scan starting (force={force}, days={days})")

    # ── Fetch all signal sources ──
    rss_articles      = fetch_all_rss()
    gdelt_articles    = fetch_all_gdelt(days=days)
    newsapi_articles  = fetch_all_newsapi(days=days)
    brave_articles    = fetch_all_brave(
        days=days,
        gdelt_count=len(gdelt_articles),
        newsapi_count=len(newsapi_articles)
    )
    all_articles = rss_articles + gdelt_articles + newsapi_articles + brave_articles

    # ── Classify articles by actor ──
    articles_by_actor  = {a: [] for a in ACTORS}
    tripwires_global   = []
    for art in all_articles:
        # Actor classification
        for actor_id in _classify_article_actor(art):
            articles_by_actor[actor_id].append(art)
        # Tripwire pattern matching
        for tw in _check_tripwires(art.get('title', '')):
            tripwires_global.append({
                'id':        tw[1],
                'actor':     tw[0],
                'severity':  ['low', 'normal', 'elevated', 'high', 'surge'][tw[2]],
                'article':   {'title': art.get('title', ''), 'url': art.get('url', ''),
                              'source': art.get('source', '')},
            })

    # ── Score actors + compute levels ──
    actor_summaries = {}
    for actor_id, cfg in ACTORS.items():
        arts  = articles_by_actor[actor_id]
        score = _score_actor_articles(arts, actor_id)
        level = actor_alert_level(score, cfg['baseline'])
        actor_tripwires = [tw for tw in tripwires_global if tw['actor'] == actor_id]
        # Top 8 articles per actor for UI display
        sorted_arts = sorted(arts, key=lambda a: a.get('feed_type') == 'rss', reverse=True)[:8]
        actor_summaries[actor_id] = {
            'name':           cfg['name'],
            'flag':           cfg['flag'],
            'icon':           cfg['icon'],
            'role':           cfg['role'],
            'vector':         cfg['vector'],
            'score':          score,
            'baseline':       cfg['baseline'],
            'level':          level,
            'article_count':  len(arts),
            'top_articles':   sorted_arts,
            'tripwires':      actor_tripwires,
        }

    # ── Compute vector scores ──
    vector_scores = {}
    vector_levels = {}
    for vec_id, cfg in VECTORS.items():
        member_scores = [actor_summaries[a]['score'] for a in cfg['actors'] if a in actor_summaries]
        member_levels = [actor_summaries[a]['level'] for a in cfg['actors'] if a in actor_summaries]
        vec_score = round(sum(member_scores), 2)
        vec_level = max(member_levels,
                        key=lambda lv: ['low', 'normal', 'elevated', 'high', 'surge'].index(lv),
                        default='low')
        vector_scores[vec_id] = vec_score
        vector_levels[vec_id] = vec_level

    # ── Compute composite Chile pressure score ──
    composite_score = round(sum(vector_scores.values()), 2)
    composite_level = max(
        (actor_summaries[a]['level'] for a in actor_summaries),
        key=lambda lv: ['low', 'normal', 'elevated', 'high', 'surge'].index(lv),
        default='low',
    )

    # ── BLUF compatibility shim ──
    LEVEL_TO_THEATRE_INT = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
    theatre_level = LEVEL_TO_THEATRE_INT.get(composite_level, 0)
    theatre_score = min(100, int(composite_score))

    # ── Read commodity pressure + cross-theater amplifiers ──
    commodity_pressure       = _read_commodity_pressure_for_chile()
    crosstheater_amplifiers  = _read_crosstheater_amplifiers()

    # ── Interpret signals (top_signals, executive summary, so what) ──
    if INTERPRETER_AVAILABLE:
        try:
            top_signals = _interp_top_signals(
                actor_summaries, tripwires_global,
                commodity_pressure, crosstheater_amplifiers
            )
            executive_summary = _interp_exec_summary(
                actor_summaries, vector_scores, vector_levels, tripwires_global
            )
            so_what = _interp_so_what(
                actor_summaries, vector_scores, vector_levels,
                tripwires_global, commodity_pressure
            )
        except Exception as e:
            print(f"[Chile Rhetoric] Interpreter error: {str(e)[:200]}")
            top_signals, executive_summary, so_what = [], '', []
    else:
        top_signals, executive_summary, so_what = [], '', []

    # ── Write Chile fingerprints for downstream consumers ──
    actor_levels = {a: s['level'] for a, s in actor_summaries.items()}
    _write_chile_fingerprints(actor_levels, vector_scores, tripwires_global)

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success':               True,
        'country':               'chile',
        'composite_score':       composite_score,
        'composite_level':       composite_level,
        'theatre_level':         theatre_level,
        'theatre_score':         theatre_score,
        'vector_scores':         vector_scores,
        'vector_levels':         vector_levels,
        'actor_summaries':       actor_summaries,
        'tripwires_global':      tripwires_global,
        'commodity_pressure':    commodity_pressure,
        'crosstheater_amplifiers': crosstheater_amplifiers,
        'top_signals':           top_signals,
        'executive_summary':     executive_summary,
        'so_what':               so_what,
        'total_articles_scanned': len(all_articles),
        'rss_count':             len(rss_articles),
        'gdelt_count':           len(gdelt_articles),
        'newsapi_count':         len(newsapi_articles),
        'brave_count':           len(brave_articles),
        'scan_time_seconds':     scan_time,
        'scanned_at':            datetime.now(timezone.utc).isoformat(),
        'last_updated':          datetime.now(timezone.utc).isoformat(),
        'cached':                False,
        'version':               '1.0.0',
    }

    save_cache(result)
    print(f"[Chile Rhetoric] ✅ Scan complete: composite={composite_score} ({composite_level}), "
          f"{len(all_articles)} articles, {scan_time}s")
    return result


# ============================================
# BACKGROUND REFRESH
# ============================================
def _background_refresh_loop():
    """Refresh every 12h. 90s warm-up so backend boot completes first."""
    time.sleep(90)
    while True:
        try:
            print("[Chile Rhetoric] Background refresh starting...")
            scan_chile_rhetoric(force=True)
        except Exception as e:
            print(f"[Chile Rhetoric] Background refresh error: {str(e)[:200]}")
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


def _start_background_refresh():
    t = threading.Thread(target=_background_refresh_loop,
                         daemon=True, name='ChileRhetoricBG')
    t.start()
    print("[Chile Rhetoric] ✅ Background refresh worker started (12h cadence)")


# ============================================
# FLASK ENDPOINTS
# ============================================
def register_chile_rhetoric_endpoints(app, start_background=True):
    """Register Chile rhetoric endpoints. Call from app.py."""

    @app.route('/api/rhetoric/chile', methods=['GET', 'OPTIONS'])
    def api_chile_rhetoric():
        if request.method == 'OPTIONS':
            return '', 200
        try:
            force = request.args.get('refresh', 'false').lower() == 'true'
            data  = scan_chile_rhetoric(force=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   str(e)[:200],
                'country': 'chile',
            }), 500

    @app.route('/api/rhetoric/chile/debug', methods=['GET'])
    def api_chile_rhetoric_debug():
        cached = load_cache()
        return jsonify({
            'version':                '1.0.0',
            'cache_key':              CACHE_KEY,
            'cache_ttl_hours':        CACHE_TTL_HOURS,
            'scan_interval_hours':    SCAN_INTERVAL_HOURS,
            'actor_count':            len(ACTORS),
            'vector_count':           len(VECTORS),
            'rss_feed_count':         len(RSS_FEEDS),
            'gdelt_query_count_en':   len(GDELT_QUERIES_EN),
            'gdelt_query_count_es':   len(GDELT_QUERIES_ES),
            'newsapi_configured':     bool(NEWSAPI_KEY),
            'brave_configured':       bool(BRAVE_API_KEY),
            'redis_configured':       bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'interpreter_available':  INTERPRETER_AVAILABLE,
            'commodity_proxy_url':    f"{WHA_BACKEND_SELF_URL}/api/wha/commodity-fingerprint/chile",
            'sibling_tracker_keys':   list(SIBLING_TRACKER_KEYS.values()),
            'cache_status': {
                'has_cache':    bool(cached),
                'cache_fresh':  is_cache_fresh(cached) if cached else False,
                'last_scan':    cached.get('scanned_at') if cached else None,
                'composite':    cached.get('composite_score') if cached else None,
                'composite_lv': cached.get('composite_level') if cached else None,
            },
        })

    if start_background:
        _start_background_refresh()

    print("[Chile Rhetoric] ✅ Endpoints registered: /api/rhetoric/chile, /api/rhetoric/chile/debug")


print("[Chile Rhetoric] Module loaded.")
