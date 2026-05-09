"""
rhetoric_tracker_peru.py
=========================================================
Peru Rhetoric Tracker v1.0.0 — Asifah Analytics
Built: May 9, 2026

Architecture: 8-actor frame, 4-vector analytical lens, multilingual signal
collection (English + Spanish), cross-tracker fingerprint integration.

ACTORS (8 total):
─────────────────────────────────────────────────────────
Domestic:
  1. presidency           — Boluarte / successor administration rhetoric
  2. cancilleria          — Foreign Ministry / MRE statements
  3. ffaa                 — Armed Forces (broken out post-Castillo arrest era)
  4. mining_sector        — CONFIEMP, Antamina, Cerro Verde, Toromocho operators
  5. las_bambas           — Single-mine flashpoint actor (community vs. MMG)
  6. vraem_sendero        — VRAEM region + Sendero Luminoso remnants + narco
External Vectors:
  7. us_peru              — Bilateral relations: embassy, INL, DoD, FTA
                            (USAID dissolved 2025; historical context only)
  8. china_peru           — BRI axis: Chancay megaport (COSCO), FTA, lithium/copper offtake

ANALYTICAL FRAME (4-vector composite score):
  • Domestic Stability Pressure  (presidency + cancilleria + ffaa + las_bambas + vraem_sendero)
  • Resource-Sector Politics     (mining_sector + las_bambas)
  • US Alignment Vector          (us_peru)
  • China Alignment Vector       (china_peru)

CROSS-TRACKER INTEGRATION:
  • READS commodity:copper:peru_supply_risk + commodity:silver:peru_supply_risk
    (from commodity_tracker.py via read_country_supply_risk)
  • READS china_lac_active fingerprint from China rhetoric tracker (if exists)
  • READS Iran rhetoric tracker for Hezbollah/extremist-network signals
    (Tri-Border Area, Quds Force activity in LatAm)
  • WRITES peru_china_axis_active, peru_chancay_pressure, peru_mining_disruption
    fingerprints for downstream consumers (regional BLUF, GPI)

SIGNAL SOURCES:
  • RSS: El Comercio, La República, Gestión, Ojo Público, RPP (native Spanish);
         Reuters Americas, AP Peru (English aggregators)
  • GDELT: English + Spanish queries (~30 distinct queries)
  • NewsAPI: Peru-specific keyword queries (English + Spanish)
  • Brave Search: tertiary fallback when GDELT/NewsAPI return <10 articles

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import threading
import traceback
from datetime import datetime, timezone, timedelta

import requests

# Optional dependencies — degrade gracefully if missing
try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False
    print("[Peru Rhetoric] ⚠️  feedparser unavailable — RSS disabled")

# Cross-tracker commodity fingerprints — read via local WHA proxy.
# Architecture note: rhetoric_tracker_peru lives on the WHA backend, but
# commodity_tracker.py lives on the ME backend. We don't import across
# backends — instead, the WHA backend has commodity_proxy_wha.py which
# caches commodity fingerprints in WHA-local Redis with a 1-hour TTL.
# This tracker calls the WHA-local proxy endpoint (same Flask app —
# resolves over localhost or the public URL with negligible overhead).
WHA_BACKEND_SELF_URL = os.environ.get(
    'WHA_BACKEND_SELF_URL',
    'http://localhost:10000'  # default Render port for in-process calls
)
COMMODITY_FINGERPRINT_AVAILABLE = True  # always — we use HTTP proxy, not import

print("[Peru Rhetoric] Module loading...")

# Try to import signal interpreter for prose generation
try:
    from peru_signal_interpreter import (
        build_top_signals,
        build_executive_summary,
        build_so_what_factor,
    )
    PERU_INTERPRETER_AVAILABLE = True
    print("[Peru Rhetoric] ✅ Signal interpreter loaded")
except ImportError:
    PERU_INTERPRETER_AVAILABLE = False
    print("[Peru Rhetoric] ⚠️  peru_signal_interpreter unavailable (will ship in shipment 2)")

# ============================================
# CONFIGURATION
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY       = os.environ.get('BRAVE_API_KEY')

CACHE_TTL_HOURS                = 12
BACKGROUND_REFRESH_HOURS       = 12
INITIAL_SCAN_DELAY_SECONDS     = 90
CROSSTHEATER_FINGERPRINT_TTL_HOURS = 13   # 12h refresh + 1h buffer

REDIS_KEY_LATEST       = 'rhetoric:peru:latest'
REDIS_KEY_FINGERPRINT_AXIS         = 'rhetoric:peru:china_axis_active'
REDIS_KEY_FINGERPRINT_CHANCAY      = 'rhetoric:peru:chancay_pressure'
REDIS_KEY_FINGERPRINT_MINING       = 'rhetoric:peru:mining_disruption'

GDELT_BASE_URL   = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI_BASE_URL = 'https://newsapi.org/v2/everything'
BRAVE_BASE_URL   = 'https://api.search.brave.com/res/v1/news/search'


# ============================================
# ALERT-LEVEL THRESHOLDS (per actor)
# ============================================
# Score → alert level mapping. These are tuned for an 8-actor 4-vector model
# at typical Peru news volume (~50-150 articles/scan). Compare to baseline
# statements_per_week in each actor definition to detect surge conditions.
def actor_alert_level(score, baseline):
    """Map a numeric actor-score to a discrete alert level using the actor's baseline."""
    if score < baseline * 0.5:
        return 'low'
    if score < baseline * 1.0:
        return 'normal'
    if score < baseline * 1.8:
        return 'elevated'
    if score < baseline * 2.8:
        return 'high'
    return 'surge'


# ============================================
# ACTOR DEFINITIONS — 8 actors total
# ============================================
ACTORS = {
    # ════════════════════════════════════════════════════════════
    # DOMESTIC ACTORS (6)
    # ════════════════════════════════════════════════════════════
    'presidency': {
        'name': 'Presidency',
        'flag': '🇵🇪', 'icon': '🏛️',
        'color': '#dc2626',
        'role': 'Executive — Boluarte administration rhetoric / 2026 election context',
        'description': 'Statements from Casa de Pizarro, presidential cabinet, official spokesperson, presidential guard incidents, electoral-cycle rhetoric',
        'vector': 'domestic_stability',
        'keywords': [
            # English
            'boluarte', 'dina boluarte', 'peru president', 'peruvian president',
            'casa de pizarro', 'palacio de gobierno peru', 'peruvian palace',
            'peru cabinet', 'peruvian cabinet', 'peru prime minister',
            'gustavo adrianzen', 'peru pm', 'peruvian pm',
            'peru election 2026', 'peruvian election 2026', 'peru presidential election',
            'peru impeachment', 'boluarte impeachment', 'vacancia presidencial',
            'peru congress motion', 'peru no confidence',
            # Spanish
            'boluarte declaracion', 'presidenta boluarte', 'boluarte rechaza',
            'dina boluarte declaró', 'casa de pizarro declara',
            'consejo de ministros perú', 'consejo de ministros peru',
            'palacio de gobierno declaró', 'gabinete peruano',
            'elecciones generales 2026 perú', 'elecciones presidenciales perú',
            'vacancia boluarte', 'moción de vacancia', 'impedimento de salida',
            'crisis política perú', 'crisis politica peru',
            # Castillo aftermath references (still active rhetoric anchor)
            'castillo trial', 'pedro castillo', 'castillo arrest',
            'castillo juicio', 'castillo prisión', 'castillo cárcel',
        ],
        'baseline_statements_per_week': 12,
    },

    'cancilleria': {
        'name': 'Cancillería (MRE)',
        'flag': '🇵🇪', 'icon': '🤝',
        'color': '#0891b2',
        'role': 'Foreign Ministry — diplomatic statements, OAS posture, regional positioning',
        'description': 'Ministerio de Relaciones Exteriores statements, ambassadorial rhetoric, OAS/UN voting, bilateral statements with US/China/Brazil/Chile',
        'vector': 'domestic_stability',
        'keywords': [
            # English
            'peru foreign ministry', 'peruvian foreign ministry', 'cancilleria peru',
            'peru foreign minister', 'peru fm', 'peruvian fm',
            'elmer schialer', 'peru cancilleria',
            'peru oas', 'peru organization of american states',
            'peru un statement', 'peru united nations statement',
            'peru summons ambassador', 'peruvian ambassador summoned',
            'peru-mexico relations', 'peru-chile dispute', 'peru-bolivia',
            'peru-ecuador border', 'peru ecuador',
            'peru pacific alliance', 'pacific alliance peru',
            # Spanish
            'cancillería perú', 'ministro de relaciones exteriores perú',
            'ministerio de relaciones exteriores perú',
            'cancillería declaración', 'cancilleria declara',
            'embajador peruano', 'embajador del perú',
            'oea perú', 'perú onu', 'perú oea declaración',
            'alianza del pacífico perú',
            'perú méxico', 'perú chile', 'perú bolivia', 'perú ecuador',
            'frontera perú ecuador', 'frontera perú chile',
        ],
        'baseline_statements_per_week': 6,
    },

    'ffaa': {
        'name': 'Armed Forces (FFAA)',
        'flag': '🇵🇪', 'icon': '🪖',
        'color': '#7c3aed',
        'role': 'Military — Comando Conjunto, Army, Navy, Air Force institutional rhetoric',
        'description': 'Comando Conjunto FFAA statements, MoD postures, military deployments to mining regions, VRAEM operations, civil-military relations signals',
        'vector': 'domestic_stability',
        'keywords': [
            # English
            'peru armed forces', 'peruvian armed forces', 'peru ffaa',
            'peru military', 'peruvian military', 'peru army',
            'peruvian army', 'peru navy', 'peruvian navy', 'peru air force',
            'peruvian air force',
            'peru defense minister', 'peru defense ministry', 'peru mod',
            'peru joint command', 'comando conjunto peru',
            'peruvian troops deploy', 'peru military deployment',
            'peru state of emergency', 'peruvian state of emergency',
            'peru martial law',
            'peru military mining', 'peruvian troops mining',
            'peru civil-military', 'peru civilian military',
            # Spanish
            'fuerzas armadas perú', 'ffaa perú', 'ejército peruano',
            'comando conjunto fuerzas armadas',
            'marina de guerra perú', 'fuerza aérea perú',
            'ministro de defensa perú', 'ministerio de defensa perú',
            'estado de emergencia perú', 'estado de emergencia',
            'despliegue militar perú', 'tropas perú',
            'jefe del estado mayor conjunto',
        ],
        'baseline_statements_per_week': 5,
    },

    'mining_sector': {
        'name': 'Mining Sector',
        'flag': '🇵🇪', 'icon': '⛏️',
        'color': '#f59e0b',
        'role': 'Industry — CONFIEMP, mining association, major operators',
        'description': 'CONFIEMP statements, Sociedad Nacional de Minería rhetoric, Antamina/Cerro Verde/Toromocho/Yanacocha operator postures, labor strikes, royalty/contract negotiations',
        'vector': 'resource_sector',
        'keywords': [
            # English — sector level
            'peru mining', 'peruvian mining', 'peru mining sector',
            'peruvian mining sector', 'peru copper mine', 'peru silver mine',
            'peru gold mine', 'peru zinc mine',
            'peru mining strike', 'peruvian mining strike', 'peru mining shutdown',
            'peru mining suspended', 'peru mining royalty',
            'snmpe peru', 'sociedad nacional de mineria peru',
            'mineria peru protest', 'peru mineria',
            # Major operators (English)
            'antamina', 'cerro verde', 'toromocho', 'yanacocha',
            'cuajone', 'toquepala', 'tia maria', 'conga peru',
            'southern copper peru', 'freeport peru', 'newmont peru',
            'glencore peru', 'mmg peru', 'minera chinalco peru',
            'shougang peru', 'jinzhao mining peru',
            # Labor / strike specific
            'peru miners strike', 'peruvian miners strike',
            'peru mining union', 'peruvian mining union',
            # Spanish
            'minería peruana', 'sector minero peruano',
            'huelga minera perú', 'paro minero perú',
            'sindicato minero perú', 'sindicato de mineros',
            'snmpe declaración', 'snmpe peru',
            'cobre peruano', 'plata peruana', 'oro peruano',
            'antamina huelga', 'cerro verde paralización',
            'tía maría protesta', 'proyecto tía maría',
            'consulta previa minería', 'minería ilegal perú',
        ],
        'baseline_statements_per_week': 10,
    },

    'las_bambas': {
        'name': 'Las Bambas — Single-Mine Flashpoint',
        'flag': '🇵🇪', 'icon': '🔥',
        'color': '#ef4444',
        'role': 'Apurímac copper-corridor conflict — community vs. MMG operator',
        'description': 'Las Bambas (MMG) blockades, community protests, Cotabambas/Chumbivilcas/Espinar/Apurímac corridor disruptions, indigenous-consultation disputes, transport-route blockades — single-actor breakout because Las Bambas alone affects ~2% global copper supply',
        'vector': 'resource_sector',
        'keywords': [
            # English
            'las bambas', 'las bambas mine', 'mmg las bambas',
            'apurimac mine', 'apurimac mining', 'cotabambas',
            'chumbivilcas', 'espinar peru', 'fuerabamba',
            'las bambas blockade', 'las bambas protest',
            'las bambas closure', 'las bambas suspended',
            'las bambas community', 'las bambas dialogue',
            'las bambas corridor', 'apurimac corridor',
            'mmg peru protest', 'minera las bambas',
            # Spanish — community / blockade language
            'las bambas bloqueo', 'las bambas paralización',
            'las bambas cierre', 'las bambas suspende',
            'las bambas comunidad', 'comunidades fuerabamba',
            'corredor minero apurímac', 'corredor minero del sur',
            'minera las bambas', 'protesta las bambas',
            'cotabambas protesta', 'chumbivilcas protesta',
            'espinar conflicto', 'espinar protesta',
            'consulta previa las bambas', 'comuneros las bambas',
            'diálogo las bambas', 'mesa diálogo las bambas',
            'huelga indefinida las bambas',
        ],
        'baseline_statements_per_week': 4,
    },

    'vraem_sendero': {
        'name': 'VRAEM / Sendero Remnants',
        'flag': '🇵🇪', 'icon': '⚠️',
        'color': '#991b1b',
        'role': 'Insurgency + narco — VRAEM region, Sendero Luminoso remnants, drug trafficking',
        'description': 'VRAEM (Valle de los Ríos Apurímac, Ene y Mantaro) operations, Sendero Luminoso remnants under Comrade José/Comrade Olga, narco-trafficking interdiction, military-police operations, extremist-network monitoring (Hezbollah Tri-Border, Iran proxies)',
        'vector': 'domestic_stability',
        'keywords': [
            # English
            'vraem', 'vraem peru', 'vraem operation',
            'sendero luminoso', 'shining path', 'shining path peru',
            'sendero remnants', 'comrade jose', 'comrade olga',
            'comrade artemio', 'sendero attack',
            'peru narco', 'peruvian narco', 'peru cocaine',
            'peru drug trafficking', 'peruvian drug trafficking',
            'peru cartels', 'peruvian cartels',
            'peru counter-narcotics', 'peru counter narcotics',
            'devida peru', 'peru drug enforcement',
            # Cross-vector: extremist networks in LatAm — should be quiet for Peru but
            # tripwire stays active (architecture decision: better quiet+watching than absent)
            'hezbollah peru', 'hizballah peru', 'iran peru proxy',
            'tri-border area', 'tri border area', 'tba latam',
            'iranian operative latam', 'quds force latam',
            # Spanish
            'vraem operación', 'vraem perú',
            'sendero luminoso perú', 'remanentes sendero luminoso',
            'narcoterrorismo perú', 'narcotráfico perú',
            'cocaína perú', 'cocaine perú', 'incautación cocaína perú',
            'devida perú', 'devida peru declaración',
            'frente policial vraem', 'comando especial vraem',
            'camarada josé', 'camarada olga',
        ],
        'baseline_statements_per_week': 6,
    },

    # ════════════════════════════════════════════════════════════
    # EXTERNAL VECTORS (2)
    # ════════════════════════════════════════════════════════════
    'us_peru': {
        'name': 'US-Peru Bilateral',
        'flag': '🇺🇸', 'icon': '🤝',
        'color': '#3b82f6',
        'role': 'United States bilateral relations — embassy, INL, DoD, FTA',
        'description': "Embassy Lima statements, INL drug-enforcement cooperation, DoD/SOUTHCOM military cooperation, US-Peru FTA dynamics, security assistance. NOTE: USAID was dissolved in 2025 — historical context only, no current implications.",
        'vector': 'us_alignment',
        'keywords': [
            # Embassy / State Department / White House
            'us embassy peru', 'us embassy lima', 'embassy lima',
            'us-peru', 'us peru', 'usa peru', 'united states peru',
            'us ambassador peru', 'us ambassador lima', 'kenna keisling',
            'state department peru', 'state dept peru', 'us state department peru',
            'white house peru', 'biden peru', 'trump peru',
            # Drug enforcement (INL — successor to USAID counter-narco programs)
            'us inl peru', 'inl peru', 'bureau international narcotics peru',
            'us drug enforcement peru', 'dea peru', 'us-peru counter narcotics',
            # DoD / SOUTHCOM
            'southcom peru', 'us southern command peru',
            'us military peru', 'us troops peru', 'us-peru military',
            'us-peru defense', 'us-peru security cooperation',
            # FTA
            'us-peru fta', 'us-peru free trade', 'us peru trade',
            'us-peru tpa', 'peru trade promotion agreement',
            # Spanish
            'embajada eeuu perú', 'embajada estados unidos perú',
            'embajador estadounidense perú', 'eeuu perú',
            'estados unidos perú', 'tratado libre comercio perú estados unidos',
            'cooperación militar eeuu perú', 'asistencia militar eeuu perú',
            # USAID — historical reference only (program dissolved 2025)
            # Listed as keywords to detect rhetoric ABOUT the dissolution / legacy programs,
            # NOT to imply current activity
            'usaid peru historical', 'usaid peru legacy', 'former usaid peru',
        ],
        'baseline_statements_per_week': 5,
    },

    'china_peru': {
        'name': 'China-Peru / Belt and Road',
        'flag': '🇨🇳', 'icon': '🚢',
        'color': '#dc2626',
        'role': 'China bilateral relations + Belt and Road — Chancay megaport, FTA, lithium/copper offtake',
        'description': 'Chancay megaport (COSCO 60% stake, opened Nov 2024), Belt and Road infrastructure, Lima-Beijing FTA upgrades, COSCO/Huawei activity, Chinese mining-sector investment (Chinalco/Shougang/Jinzhao), copper+silver offtake politics, Xi-Boluarte / Xi-successor diplomacy',
        'vector': 'china_alignment',
        'keywords': [
            # Chancay megaport — central BRI flashpoint
            'chancay port', 'chancay megaport', 'puerto chancay',
            'chancay terminal', 'cosco chancay', 'cosco shipping peru',
            'chancay opening', 'chancay inauguration',
            'megapuerto chancay', 'chancay multipurpose',
            # General China-Peru
            'china peru', 'china-peru', 'beijing peru', 'beijing lima',
            'china ambassador peru', 'china embassy peru',
            'xi jinping peru', 'xi peru', 'xi boluarte',
            'china peru fta', 'china-peru fta', 'china peru free trade',
            'china peru trade agreement', 'china peru cooperation',
            # Belt and Road — explicit
            'belt and road peru', 'bri peru', 'belt road peru',
            'silk road peru', 'one belt one road peru',
            # Chinese mining investment in Peru
            'chinalco peru', 'shougang peru', 'jinzhao mining peru',
            'minera chinalco', 'mmg peru china', 'china las bambas',
            'china mining peru', 'chinese investment peru',
            'huawei peru', 'zte peru',
            # Spanish
            'china perú', 'beijing perú', 'embajada china perú',
            'embajador chino perú', 'puerto de chancay',
            'cosco perú', 'inversión china perú',
            'tlc china perú', 'tratado libre comercio china perú',
            'ruta de la seda perú', 'franja y la ruta perú',
            'iniciativa franja y ruta perú', 'cooperación china perú',
            'chinalco perú', 'shougang perú', 'jinzhao mineria perú',
            'huawei perú declaración',
        ],
        'baseline_statements_per_week': 6,
    },
}

# Helper sets for downstream classification logic
DOMESTIC_ACTORS = ['presidency', 'cancilleria', 'ffaa', 'mining_sector', 'las_bambas', 'vraem_sendero']
EXTERNAL_ACTORS = ['us_peru', 'china_peru']
RESOURCE_ACTORS = ['mining_sector', 'las_bambas']
ALIGNMENT_ACTORS = {'us_peru': 'us_alignment', 'china_peru': 'china_alignment'}

# Vector groupings for the 4-vector composite score
VECTOR_GROUPS = {
    'domestic_stability':  ['presidency', 'cancilleria', 'ffaa', 'las_bambas', 'vraem_sendero'],
    'resource_sector':     ['mining_sector', 'las_bambas'],
    'us_alignment':        ['us_peru'],
    'china_alignment':     ['china_peru'],
}


# ============================================
# TRIPWIRES — high-severity events that escalate alert level regardless of volume
# ============================================
TRIPWIRES = {
    'state_of_emergency': {
        'patterns': [
            'state of emergency peru', 'state of emergency in peru',
            'state of emergency declared peru', 'peru state of emergency',
            'estado de emergencia perú', 'estado de emergencia peru',
            'estado de emergencia en perú', 'estado de emergencia en peru',
            'martial law peru', 'curfew peru', 'toque de queda perú',
        ],
        'severity': 'surge',
        'description': 'Peru state of emergency declared — domestic stability rupture',
    },
    'las_bambas_full_closure': {
        'patterns': [
            'las bambas suspended operations', 'las bambas full closure',
            'las bambas indefinite shutdown', 'las bambas paralización indefinida',
            'las bambas cierre indefinido', 'las bambas operaciones suspendidas',
        ],
        'severity': 'surge',
        'description': 'Las Bambas full operational closure — global copper supply impact',
    },
    'chancay_disruption': {
        'patterns': [
            'chancay closed', 'chancay shutdown', 'chancay disruption',
            'chancay strike', 'chancay incident', 'chancay accident',
            'puerto chancay cerrado', 'huelga chancay',
        ],
        'severity': 'high',
        'description': 'Chancay megaport disruption — BRI signal + Pacific trade flow risk',
    },
    'presidential_vacancy': {
        'patterns': [
            'boluarte impeached', 'boluarte impeachment vote',
            'vacancia boluarte aprobada', 'moción de vacancia aprobada',
            'boluarte removed', 'boluarte resigna', 'boluarte renuncia',
        ],
        'severity': 'surge',
        'description': 'Presidential vacancy / impeachment vote — institutional rupture',
    },
    'ffaa_intervention': {
        'patterns': [
            'military takes power peru', 'coup peru', 'golpe perú',
            'fuerzas armadas asumen poder', 'autogolpe peru',
            'self-coup peru',
        ],
        'severity': 'surge',
        'description': 'Military intervention / coup — institutional rupture',
    },
    'mass_casualty_protest': {
        'patterns': [
            'peru protesters killed', 'peruvian protesters killed',
            'manifestantes muertos perú', 'protestas mortales perú',
            'massacre peru', 'masacre perú',
        ],
        'severity': 'high',
        'description': 'Mass-casualty protest event — domestic stability rupture',
    },
    'sendero_attack': {
        'patterns': [
            'sendero luminoso attack', 'shining path attack',
            'ataque sendero luminoso', 'emboscada sendero',
            'narco-terror attack peru',
        ],
        'severity': 'high',
        'description': 'Sendero / narco-insurgent attack — security perimeter event',
    },
    'extremist_network_signal': {
        'patterns': [
            'hezbollah peru', 'hizballah peru', 'iran cell peru',
            'tri-border arrest peru', 'iranian operative peru',
            'quds force peru',
        ],
        'severity': 'high',
        'description': 'External extremist-network signal in Peru territory — quiet tripwire (architecture: tripwires stay active even when expected silent)',
    },
}


# ============================================
# RSS FEEDS — Spanish + English Peru sources
# ============================================
RSS_FEEDS = {
    'el_comercio': {
        'name': 'El Comercio',
        'url': 'https://elcomercio.pe/feed/',
        'language': 'es',
        'weight': 1.0,
    },
    'la_republica': {
        'name': 'La República',
        'url': 'https://larepublica.pe/feed/',
        'language': 'es',
        'weight': 1.0,
    },
    'gestion': {
        'name': 'Gestión',
        'url': 'https://gestion.pe/arcio/rss/',
        'language': 'es',
        'weight': 1.0,
    },
    'rpp': {
        'name': 'RPP',
        'url': 'https://rpp.pe/feed',
        'language': 'es',
        'weight': 0.95,
    },
    'ojo_publico': {
        'name': 'Ojo Público',
        'url': 'https://ojo-publico.com/rss.xml',
        'language': 'es',
        'weight': 0.95,
    },
    'reuters_americas': {
        'name': 'Reuters Americas',
        'url': 'https://feeds.reuters.com/Reuters/worldNews',
        'language': 'en',
        'weight': 0.85,  # general — Peru filtering happens at keyword stage
    },
}


# ============================================
# GDELT QUERIES — English + Spanish, ~30 distinct queries
# ============================================
GDELT_QUERIES_EN = [
    # Presidency / political
    '"Peru" AND ("Boluarte" OR "Castillo" OR "presidential")',
    '"Peru" AND ("impeachment" OR "vacancia" OR "no-confidence")',
    '"Peru" AND ("election" OR "elections" OR "2026 election")',
    # Cancillería / foreign policy
    '"Peru" AND ("foreign ministry" OR "cancilleria" OR "OAS")',
    # FFAA / military
    '"Peru" AND ("armed forces" OR "military" OR "state of emergency")',
    # Mining sector
    '"Peru" AND ("mining" OR "miner" OR "copper" OR "silver")',
    '"Peru" AND ("Antamina" OR "Cerro Verde" OR "Toromocho" OR "Yanacocha")',
    # Las Bambas — single-mine flashpoint
    '"Las Bambas" OR "MMG Peru"',
    '"Apurimac" AND ("blockade" OR "protest" OR "mining")',
    # VRAEM / narco
    '"Peru" AND ("VRAEM" OR "Sendero Luminoso" OR "Shining Path")',
    '"Peru" AND ("narco" OR "drug trafficking" OR "cocaine")',
    # US-Peru
    '"US" AND "Peru" AND ("ambassador" OR "embassy" OR "FTA" OR "trade")',
    '"Peru" AND ("SOUTHCOM" OR "INL" OR "DEA")',
    # China-Peru / BRI
    '"Chancay" AND ("port" OR "megaport" OR "COSCO")',
    '"China" AND "Peru" AND ("Xi" OR "Belt and Road" OR "BRI")',
    '"Peru" AND ("Chinalco" OR "Shougang" OR "Jinzhao")',
]

GDELT_QUERIES_ES = [
    # Presidency / political
    '"Boluarte" AND ("Perú" OR "Peru")',
    '"vacancia presidencial" OR "moción de vacancia"',
    '"elecciones generales 2026" AND ("Perú" OR "Peru")',
    # Cancillería
    '"cancillería" AND ("Perú" OR "Peru")',
    # FFAA
    '"fuerzas armadas" AND ("Perú" OR "Peru")',
    '"estado de emergencia" AND ("Perú" OR "Peru")',
    # Mining
    '"minería peruana" OR "huelga minera"',
    '"Antamina" OR "Cerro Verde" OR "Toromocho" OR "Yanacocha"',
    # Las Bambas
    '"Las Bambas" AND ("bloqueo" OR "paralización")',
    '"Apurímac" AND ("conflicto" OR "minería")',
    # VRAEM
    '"VRAEM" OR "Sendero Luminoso"',
    '"narcotráfico" AND ("Perú" OR "Peru")',
    # US-Peru
    '"Estados Unidos" AND "Perú" AND ("embajador" OR "embajada" OR "TLC")',
    # China-Peru
    '"Chancay" AND ("puerto" OR "COSCO")',
    '"China" AND "Perú" AND ("Xi" OR "TLC" OR "ruta de la seda")',
]


# ============================================
# CACHE / REDIS HELPERS
# ============================================
CACHE_FILE = '/tmp/peru_rhetoric_cache.json'
_background_scan_running = False
_background_scan_lock = threading.Lock()
_last_scan_started_at = None


def _redis_get(key):
    """Read a JSON value from Upstash Redis. Returns None if unavailable / missing."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=8
        )
        if resp.status_code != 200:
            return None
        body = resp.json()
        raw = body.get('result')
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        print(f"[Peru Rhetoric] Redis GET error ({key}): {str(e)[:120]}")
        return None


def _redis_set(key, value, ttl_hours=CACHE_TTL_HOURS):
    """Write a JSON value to Upstash Redis with TTL. Returns True on success."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        ttl_seconds = int(ttl_hours * 3600)
        url = f"{UPSTASH_REDIS_URL}/setex/{key}/{ttl_seconds}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(value, default=str),
            timeout=8
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Peru Rhetoric] Redis SET error ({key}): {str(e)[:120]}")
        return False


def load_cache():
    """Try Redis first, fallback to /tmp file."""
    cached = _redis_get(REDIS_KEY_LATEST)
    if cached:
        return cached
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_cache(data):
    """Save to Redis + /tmp fallback."""
    data['cached_at'] = datetime.now(timezone.utc).isoformat()
    if _redis_set(REDIS_KEY_LATEST, data, ttl_hours=CACHE_TTL_HOURS):
        print("[Peru Rhetoric] ✅ Saved to Redis")
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as e:
        print(f"[Peru Rhetoric] /tmp save error: {e}")


def is_cache_fresh(data):
    """Check if cache is younger than CACHE_TTL_HOURS."""
    if not data or 'cached_at' not in data:
        return False
    try:
        cached_at = datetime.fromisoformat(data['cached_at'])
        age = datetime.now(timezone.utc) - cached_at
        return age.total_seconds() < (CACHE_TTL_HOURS * 3600)
    except Exception:
        return False


# ============================================
# DATA FETCHERS — RSS / GDELT / NewsAPI / Brave
# ============================================
def fetch_rss_articles(feed_id, feed_config, max_articles=30):
    """Fetch + parse a single RSS feed."""
    if not FEEDPARSER_AVAILABLE:
        return []
    articles = []
    try:
        feed = feedparser.parse(feed_config['url'])
        for entry in feed.entries[:max_articles]:
            articles.append({
                'title':       entry.get('title', ''),
                'description': entry.get('summary', '') or entry.get('description', ''),
                'url':         entry.get('link', ''),
                'published':   entry.get('published', ''),
                'source':      feed_config['name'],
                'feed_id':     feed_id,
                'feed_type':   'rss',
                'language':    feed_config.get('language', 'en'),
                'feed_weight': feed_config.get('weight', 1.0),
            })
    except Exception as e:
        print(f"[Peru Rhetoric] RSS fetch error ({feed_id}): {str(e)[:120]}")
    return articles


def fetch_all_rss():
    all_articles = []
    for feed_id, feed_config in RSS_FEEDS.items():
        articles = fetch_rss_articles(feed_id, feed_config)
        if articles:
            print(f"[Peru Rhetoric] RSS {feed_id}: {len(articles)} articles")
        all_articles.extend(articles)
    return all_articles


def fetch_gdelt_query(query, language='eng', days=7, max_articles=50):
    """Fetch a single GDELT query with circuit-breaker timeout."""
    params = {
        'query':       f'{query} sourcelang:{language}',
        'mode':        'artlist',
        'maxrecords':  max_articles,
        'format':      'json',
        'timespan':    f'{days}d',
    }
    try:
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=(5, 12))
        if resp.status_code == 429:
            return []  # rate limited — bail silently
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for item in data.get('articles', []):
            articles.append({
                'title':       item.get('title', ''),
                'description': '',
                'url':         item.get('url', ''),
                'published':   item.get('seendate', ''),
                'source':      item.get('domain', 'GDELT'),
                'feed_id':     'gdelt',
                'feed_type':   'gdelt',
                'language':    'es' if language == 'spa' else 'en',
                'feed_weight': 0.85,
            })
        return articles
    except Exception:
        return []


def fetch_all_gdelt(days=7):
    all_articles = []
    for q in GDELT_QUERIES_EN:
        all_articles.extend(fetch_gdelt_query(q, language='eng', days=days))
        time.sleep(0.5)
    for q in GDELT_QUERIES_ES:
        all_articles.extend(fetch_gdelt_query(q, language='spa', days=days))
        time.sleep(0.5)
    print(f"[Peru Rhetoric] GDELT: {len(all_articles)} articles")
    return all_articles


def fetch_newsapi(query, days=7):
    """Fetch from NewsAPI."""
    if not NEWSAPI_KEY:
        return []
    from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    params = {
        'q':        query,
        'from':     from_date,
        'language': 'en',
        'sortBy':   'publishedAt',
        'pageSize': 30,
        'apiKey':   NEWSAPI_KEY,
    }
    try:
        resp = requests.get(NEWSAPI_BASE_URL, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for item in data.get('articles', []):
            articles.append({
                'title':       item.get('title', ''),
                'description': item.get('description', ''),
                'url':         item.get('url', ''),
                'published':   item.get('publishedAt', ''),
                'source':      (item.get('source') or {}).get('name', 'NewsAPI'),
                'feed_id':     'newsapi',
                'feed_type':   'newsapi',
                'language':    'en',
                'feed_weight': 0.9,
            })
        return articles
    except Exception:
        return []


def fetch_all_newsapi(days=7):
    queries = [
        'Peru Boluarte OR Castillo',
        'Peru mining strike OR blockade',
        'Las Bambas OR Antamina',
        'Chancay port OR megaport',
        'Peru China Belt and Road',
        'Peru US embassy OR FTA',
        'VRAEM OR Sendero Luminoso',
    ]
    all_articles = []
    for q in queries:
        all_articles.extend(fetch_newsapi(q, days=days))
        time.sleep(0.5)
    if all_articles:
        print(f"[Peru Rhetoric] NewsAPI: {len(all_articles)} articles")
    return all_articles


def fetch_brave(query, days=7):
    """Brave Search News API — tertiary fallback."""
    if not BRAVE_API_KEY:
        return []
    params = {'q': query, 'count': 20, 'spellcheck': '0'}
    try:
        resp = requests.get(
            BRAVE_BASE_URL,
            params=params,
            headers={
                'Accept':                'application/json',
                'Accept-Encoding':       'gzip',
                'X-Subscription-Token':  BRAVE_API_KEY,
            },
            timeout=10
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        articles = []
        for item in data.get('results', []):
            articles.append({
                'title':       item.get('title', ''),
                'description': item.get('description', ''),
                'url':         item.get('url', ''),
                'published':   item.get('age', ''),
                'source':      (item.get('source') or '') or 'Brave',
                'feed_id':     'brave',
                'feed_type':   'brave',
                'language':    'en',
                'feed_weight': 0.75,
            })
        return articles
    except Exception:
        return []


def fetch_all_brave(days=7, gdelt_count=0, newsapi_count=0):
    """Brave fallback — only fires when GDELT + NewsAPI returned <10 articles total."""
    if gdelt_count + newsapi_count >= 10:
        return []
    queries = [
        'Peru Boluarte 2026',
        'Las Bambas blockade',
        'Chancay port COSCO',
        'Peru mining strike',
    ]
    all_articles = []
    for q in queries:
        all_articles.extend(fetch_brave(q, days=days))
        time.sleep(0.5)
    if all_articles:
        print(f"[Peru Rhetoric] Brave fallback: {len(all_articles)} articles")
    return all_articles


# ============================================
# CLASSIFICATION + SCORING
# ============================================
def _normalize_text(text):
    """Lowercase + strip diacritics-light for keyword matching."""
    return (text or '').lower()


def _classify_article_actor(article):
    """
    Match an article against actor keyword lists. Returns (actor_id, hit_count) tuples
    for all matching actors. Multi-actor matching is allowed (e.g., a "Boluarte visits
    Las Bambas" headline can hit both presidency AND las_bambas).
    """
    title = _normalize_text(article.get('title', ''))
    desc  = _normalize_text(article.get('description', ''))
    text  = title + ' ' + desc

    matches = []
    for actor_id, actor_data in ACTORS.items():
        hit_count = 0
        for kw in actor_data['keywords']:
            if kw.lower() in text:
                hit_count += 1
        if hit_count > 0:
            matches.append((actor_id, hit_count))
    return matches


def _check_tripwires(text):
    """Check article text against TRIPWIRES patterns. Returns list of (tripwire_id, severity)."""
    text_lower = _normalize_text(text)
    triggered = []
    for tw_id, tw_data in TRIPWIRES.items():
        for pattern in tw_data['patterns']:
            if pattern.lower() in text_lower:
                triggered.append((tw_id, tw_data['severity']))
                break  # only count each tripwire once per article
    return triggered


def _score_actor_articles(articles_for_actor, actor_id):
    """
    Compute weighted score for an actor: sum of (feed_weight × keyword-density × recency).
    Returns dict with score, article_count, language_breakdown, sources, top_articles, tripwires.
    """
    if not articles_for_actor:
        return {
            'score': 0,
            'article_count': 0,
            'language_breakdown': {},
            'sources': [],
            'top_articles': [],
            'tripwires': [],
        }

    score = 0
    lang_count = {}
    src_count = {}
    tripwires_seen = set()

    for art in articles_for_actor:
        feed_w = art.get('feed_weight', 1.0)
        kw_hits = art.get('_actor_hits', 1)  # set by classifier
        kw_factor = min(1.0 + (kw_hits - 1) * 0.15, 2.0)  # diminishing returns
        article_score = feed_w * kw_factor
        score += article_score

        lang = art.get('language', 'en')
        lang_count[lang] = lang_count.get(lang, 0) + 1
        src = art.get('source', 'Unknown')
        src_count[src] = src_count.get(src, 0) + 1

        # Tripwire check
        full_text = f"{art.get('title', '')} {art.get('description', '')}"
        for tw_id, severity in _check_tripwires(full_text):
            tripwires_seen.add((tw_id, severity))

    # Sort articles by article_score descending
    sorted_articles = sorted(
        articles_for_actor,
        key=lambda a: a.get('feed_weight', 1.0) * min(1.0 + (a.get('_actor_hits', 1) - 1) * 0.15, 2.0),
        reverse=True,
    )
    top_articles = []
    for a in sorted_articles[:8]:
        top_articles.append({
            'title':       a.get('title', ''),
            'url':         a.get('url', ''),
            'source':      a.get('source', ''),
            'language':    a.get('language', 'en'),
            'published':   a.get('published', ''),
            'feed_type':   a.get('feed_type', ''),
        })

    sources = sorted(src_count.items(), key=lambda x: -x[1])[:6]

    return {
        'score':              round(score, 2),
        'article_count':      len(articles_for_actor),
        'language_breakdown': lang_count,
        'sources':            [{'source': s, 'count': c} for s, c in sources],
        'top_articles':       top_articles,
        'tripwires':          [{'id': tw_id, 'severity': sev} for tw_id, sev in tripwires_seen],
    }


# ============================================
# CROSS-TRACKER FINGERPRINT INTEGRATION
# ============================================
def _read_commodity_pressure_for_peru():
    """
    Read commodity supply-risk fingerprints for Peru's exposed commodities
    via the WHA-local commodity proxy (commodity_proxy_wha.py).

    The proxy caches ME-backend fingerprints in WHA Redis with 1-hour TTL,
    so this call is a cheap localhost hit on the proxy — no cross-backend
    HTTP latency unless the WHA-local cache misses.

    Returns dict {commodity_id: risk_dict} for any active pressure.
    Returns {} on error / empty / proxy unavailable — graceful degradation.
    """
    try:
        url = f"{WHA_BACKEND_SELF_URL}/api/wha/commodity-fingerprint/peru"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        # Proxy returns {fingerprints: {commodity_id: risk_dict}, ...}
        return data.get('fingerprints', {}) or {}
    except Exception as e:
        print(f"[Peru Rhetoric] commodity proxy read error: {str(e)[:120]}")
        return {}


def _read_crosstheater_amplifiers():
    """
    Read fingerprints from sibling trackers that affect Peru's analytical context:
      • China rhetoric tracker — Latin America focus
      • Iran rhetoric tracker — Hezbollah/extremist-network signals (TBA, Quds)
    """
    amplifiers = {}
    candidate_keys = {
        'china_lac_active':     'rhetoric:china:lac_active',
        'china_bri_latam':      'rhetoric:china:bri_latam_active',
        'iran_latam_active':    'rhetoric:iran:latam_active',
        'iran_hezbollah_tba':   'rhetoric:iran:hezbollah_tba_active',
    }
    for label, redis_key in candidate_keys.items():
        val = _redis_get(redis_key)
        if val:
            amplifiers[label] = val
    return amplifiers


def _write_peru_fingerprints(actor_levels, vector_scores, tripwires_global):
    """
    Write Peru-side fingerprints for downstream consumers (regional BLUF, GPI, sibling trackers).
      • peru_china_axis_active     — active when china_peru actor at elevated+
      • peru_chancay_pressure      — active when chancay tripwire OR china_peru surge
      • peru_mining_disruption     — active when mining_sector OR las_bambas at high+
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # China axis fingerprint
    china_level = actor_levels.get('china_peru', 'low')
    china_axis = {
        'active':           china_level in ('elevated', 'high', 'surge'),
        'level':            china_level,
        'china_alignment_score': vector_scores.get('china_alignment', 0),
        'last_updated':     now_iso,
    }
    _redis_set(REDIS_KEY_FINGERPRINT_AXIS, china_axis,
               ttl_hours=CROSSTHEATER_FINGERPRINT_TTL_HOURS)

    # Chancay pressure fingerprint
    chancay_active = (
        any(tw.get('id') == 'chancay_disruption' for tw in tripwires_global)
        or china_level in ('high', 'surge')
    )
    chancay = {
        'active':           chancay_active,
        'china_level':      china_level,
        'tripwire_hit':     any(tw.get('id') == 'chancay_disruption' for tw in tripwires_global),
        'last_updated':     now_iso,
    }
    _redis_set(REDIS_KEY_FINGERPRINT_CHANCAY, chancay,
               ttl_hours=CROSSTHEATER_FINGERPRINT_TTL_HOURS)

    # Mining disruption fingerprint
    mining_level = actor_levels.get('mining_sector', 'low')
    bambas_level = actor_levels.get('las_bambas', 'low')
    mining_active = (
        mining_level in ('high', 'surge')
        or bambas_level in ('high', 'surge')
        or any(tw.get('id') == 'las_bambas_full_closure' for tw in tripwires_global)
    )
    mining = {
        'active':           mining_active,
        'mining_level':     mining_level,
        'las_bambas_level': bambas_level,
        'resource_score':   vector_scores.get('resource_sector', 0),
        'last_updated':     now_iso,
    }
    _redis_set(REDIS_KEY_FINGERPRINT_MINING, mining,
               ttl_hours=CROSSTHEATER_FINGERPRINT_TTL_HOURS)


# ============================================
# MAIN SCAN ORCHESTRATOR
# ============================================
def scan_peru_rhetoric(force=False, days=7):
    """
    Full scan: fetch from all sources, classify per actor, score, build summaries,
    write fingerprints, return result.
    """
    global _last_scan_started_at
    _last_scan_started_at = datetime.now(timezone.utc)
    scan_start = time.time()

    print(f"[Peru Rhetoric] === Scan start (force={force}, days={days}) ===")

    # ── Fetch all sources ──
    rss_articles = fetch_all_rss()
    print(f"[Peru Rhetoric] RSS total: {len(rss_articles)}")
    gdelt_articles = fetch_all_gdelt(days=days)
    newsapi_articles = fetch_all_newsapi(days=days)
    brave_articles = fetch_all_brave(
        days=days,
        gdelt_count=len(gdelt_articles),
        newsapi_count=len(newsapi_articles),
    )

    all_articles = rss_articles + gdelt_articles + newsapi_articles + brave_articles
    # Dedupe by URL
    seen_urls = set()
    deduped = []
    for a in all_articles:
        u = a.get('url', '')
        if u and u not in seen_urls:
            seen_urls.add(u)
            deduped.append(a)
    all_articles = deduped
    print(f"[Peru Rhetoric] Articles after dedup: {len(all_articles)}")

    # ── Classify articles by actor ──
    articles_by_actor = {actor_id: [] for actor_id in ACTORS.keys()}
    for art in all_articles:
        matches = _classify_article_actor(art)
        for actor_id, hit_count in matches:
            art_copy = dict(art)
            art_copy['_actor_hits'] = hit_count
            articles_by_actor[actor_id].append(art_copy)

    # ── Score each actor ──
    actor_summaries = {}
    actor_levels = {}
    tripwires_global = []
    for actor_id, actor_data in ACTORS.items():
        scored = _score_actor_articles(articles_by_actor[actor_id], actor_id)
        baseline = actor_data['baseline_statements_per_week']
        level = actor_alert_level(scored['score'], baseline)
        actor_levels[actor_id] = level

        actor_summaries[actor_id] = {
            'name':         actor_data['name'],
            'flag':         actor_data['flag'],
            'icon':         actor_data['icon'],
            'color':        actor_data['color'],
            'role':         actor_data['role'],
            'description':  actor_data['description'],
            'vector':       actor_data['vector'],
            'score':        scored['score'],
            'level':        level,
            'baseline':     baseline,
            'article_count':       scored['article_count'],
            'language_breakdown':  scored['language_breakdown'],
            'sources':             scored['sources'],
            'top_articles':        scored['top_articles'],
            'tripwires':           scored['tripwires'],
        }
        for tw in scored['tripwires']:
            tripwires_global.append({'actor': actor_id, **tw})

    # ── Compute 4-vector composite scores ──
    vector_scores = {}
    vector_levels = {}
    for vector_id, member_actors in VECTOR_GROUPS.items():
        total = sum(actor_summaries[a]['score'] for a in member_actors if a in actor_summaries)
        vector_scores[vector_id] = round(total, 2)
        # Level for vector = max actor level in vector
        levels_seen = [actor_summaries[a]['level'] for a in member_actors if a in actor_summaries]
        order = ['low', 'normal', 'elevated', 'high', 'surge']
        if levels_seen:
            vector_levels[vector_id] = max(levels_seen, key=lambda lv: order.index(lv))
        else:
            vector_levels[vector_id] = 'low'

    # ── Read cross-tracker context ──
    commodity_pressure = _read_commodity_pressure_for_peru()
    crosstheater_amplifiers = _read_crosstheater_amplifiers()

    # ── Write Peru fingerprints for downstream consumers ──
    _write_peru_fingerprints(actor_levels, vector_scores, tripwires_global)

    # ── Build executive summary + so-what + top signals via interpreter ──
    if PERU_INTERPRETER_AVAILABLE:
        try:
            top_signals = build_top_signals(actor_summaries, tripwires_global,
                                             commodity_pressure, crosstheater_amplifiers)
            executive_summary = build_executive_summary(actor_summaries, vector_scores,
                                                       vector_levels, tripwires_global)
            so_what = build_so_what_factor(actor_summaries, vector_scores, vector_levels,
                                           tripwires_global, commodity_pressure)
        except Exception as e:
            print(f"[Peru Rhetoric] Interpreter error: {str(e)[:200]}")
            traceback.print_exc()
            top_signals, executive_summary, so_what = [], '', []
    else:
        top_signals, executive_summary, so_what = [], '', []

    # ── Compute composite Peru pressure score ──
    composite_score = round(sum(vector_scores.values()), 2)
    composite_level = max(
        (actor_summaries[a]['level'] for a in actor_summaries),
        key=lambda lv: ['low', 'normal', 'elevated', 'high', 'surge'].index(lv),
        default='low',
    )

    # ── BLUF compatibility shim ──
    # wha_regional_bluf.py's _normalize_tracker_data() expects an integer
    # theatre_level (0-5) and a 0-100 theatre_score. Peru emits a
    # categorical composite_level + a free-running composite_score; map
    # them so the regional BLUF can ingest Peru cleanly alongside Cuba.
    LEVEL_TO_THEATRE_INT = {'low': 0, 'normal': 1, 'elevated': 2, 'high': 3, 'surge': 4}
    theatre_level = LEVEL_TO_THEATRE_INT.get(composite_level, 0)
    # Cap theatre_score at 100 — composite_score is unbounded by design
    theatre_score = min(100, int(composite_score))

    scan_time = round(time.time() - scan_start, 1)

    result = {
        'success':               True,
        'country':               'peru',
        'composite_score':       composite_score,
        'composite_level':       composite_level,
        # BLUF compatibility shim — see definitions above
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
        'source_breakdown': {
            'rss':     len(rss_articles),
            'gdelt':   len(gdelt_articles),
            'newsapi': len(newsapi_articles),
            'brave':   len(brave_articles),
        },
        'total_articles_scanned': len(all_articles),
        'scan_time_seconds':      scan_time,
        'days_analyzed':          days,
        'last_updated':           datetime.now(timezone.utc).isoformat(),
        'cached':                 False,
        'version':                '1.0.0',
    }

    save_cache(result)
    print(f"[Peru Rhetoric] ✅ Scan complete in {scan_time}s — composite {composite_level} ({composite_score})")
    return result


# ============================================
# BACKGROUND REFRESH LOOP
# ============================================
def _background_refresh_loop():
    """Periodic refresh — initial 90s delay, then every BACKGROUND_REFRESH_HOURS."""
    global _background_scan_running
    time.sleep(INITIAL_SCAN_DELAY_SECONDS)
    while True:
        try:
            with _background_scan_lock:
                if _background_scan_running:
                    time.sleep(60)
                    continue
                _background_scan_running = True
            try:
                print("[Peru Rhetoric] Background refresh starting...")
                scan_peru_rhetoric(force=True, days=7)
                print("[Peru Rhetoric] Background refresh complete.")
            finally:
                with _background_scan_lock:
                    _background_scan_running = False
            time.sleep(BACKGROUND_REFRESH_HOURS * 3600)
        except Exception as e:
            print(f"[Peru Rhetoric] Background loop error: {e}")
            time.sleep(600)


def _start_background_refresh():
    t = threading.Thread(target=_background_refresh_loop, daemon=True, name='PeruRhetoricBG')
    t.start()
    print(f"[Peru Rhetoric] Background refresh thread started (initial delay {INITIAL_SCAN_DELAY_SECONDS}s)")


# ============================================
# FLASK ENDPOINTS
# ============================================
def register_peru_rhetoric_endpoints(app, start_background=True):
    """Register Peru rhetoric endpoints on a Flask app + start background refresh."""
    from flask import jsonify, request

    @app.route('/api/rhetoric/peru', methods=['GET', 'OPTIONS'])
    def api_peru_rhetoric():
        if request.method == 'OPTIONS':
            return ('', 204)
        force = request.args.get('refresh', '').lower() in ('true', '1', 'yes')

        cached = load_cache()
        if cached and is_cache_fresh(cached) and not force:
            cached['cached'] = True
            return jsonify(cached)

        # Cache miss or force refresh — return cached (if any) and trigger background scan
        if cached and not force:
            cached['cached'] = True
            cached['stale'] = True
            # Trigger background scan if not already running
            with _background_scan_lock:
                if not _background_scan_running:
                    threading.Thread(
                        target=lambda: scan_peru_rhetoric(force=True, days=7),
                        daemon=True,
                    ).start()
            return jsonify(cached)

        # No cache at all — do synchronous scan (slow!)
        result = scan_peru_rhetoric(force=force, days=7)
        return jsonify(result)

    @app.route('/api/rhetoric/peru/debug', methods=['GET'])
    def api_peru_rhetoric_debug():
        """Diagnostic — config snapshot + cache freshness."""
        cached = load_cache()
        return jsonify({
            'version':                  '1.0.0',
            'actor_count':              len(ACTORS),
            'actors':                   list(ACTORS.keys()),
            'vector_count':             len(VECTOR_GROUPS),
            'vectors':                  list(VECTOR_GROUPS.keys()),
            'rss_feeds':                len(RSS_FEEDS),
            'gdelt_queries_en':         len(GDELT_QUERIES_EN),
            'gdelt_queries_es':         len(GDELT_QUERIES_ES),
            'tripwires':                len(TRIPWIRES),
            'redis_configured':         bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'newsapi_configured':       bool(NEWSAPI_KEY),
            'brave_configured':         bool(BRAVE_API_KEY),
            'commodity_fingerprint':    COMMODITY_FINGERPRINT_AVAILABLE,
            'interpreter_available':    PERU_INTERPRETER_AVAILABLE,
            'cache_present':            cached is not None,
            'cache_fresh':              is_cache_fresh(cached) if cached else False,
            'cache_age_hours':          None if not cached else round(
                (datetime.now(timezone.utc) - datetime.fromisoformat(cached.get('cached_at', '2020-01-01T00:00:00+00:00'))).total_seconds() / 3600, 2
            ) if cached.get('cached_at') else None,
            'last_scan_started_at':     _last_scan_started_at.isoformat() if _last_scan_started_at else None,
            'background_running':       _background_scan_running,
        })

    print("[Peru Rhetoric] ✅ Endpoints registered:")
    print("  GET  /api/rhetoric/peru")
    print("  GET  /api/rhetoric/peru/debug")

    if start_background:
        _start_background_refresh()
    else:
        print("[Peru Rhetoric] ℹ️ Background refresh disabled on this instance")


print("[Peru Rhetoric] Module loaded.")
