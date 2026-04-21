"""
Asifah Analytics -- Cuba Rhetoric & Pressure Tracker
WHA Backend Module
v1.0.0 -- April 2026

Cuba Rhetoric Tracker -- Inverted Pressure Model

UNLIKE standard outbound trackers (Iran, China, North Korea), Cuba is primarily
the SUBJECT of rhetoric rather than the producer. The analytical frame is three
questions answered simultaneously on every scan:

  1. Is the U.S. escalating pressure toward regime change, military action,
     or migration interdiction? How far is Washington actually willing to go?

  2. Is the Cuban regime stabilizing or fracturing under that pressure?
     Is G2 suppression working? Are dissident signals rising? Is economic
     collapse accelerating regime brittleness?

  3. Are Russia / China / Iran exploiting the friction to gain access
     (SIGINT station rumors, port visits, infrastructure, military delegations)?

Key contextual factors baked in:
  - Lourdes SIGINT station (closed 2001) reactivation rumors recurrent since 2023
  - Mariel Port -- potential PLAN deep-water access, Chinese port investment
  - ~11 million Cubans, largest population decline in Cuban history ongoing
  - Economic collapse: chronic blackouts, dollarization, tourism downturn
  - Migration: ~500k Cubans arrived US 2022-2024, Darien Gap secondary route
  - Regime transition risk: Diaz-Canel weak successor to Castros, opaque PCC
  - US policy: Trump II restored terror designation, remittance caps,
    OFAC actions, travel restrictions
  - Havana Syndrome unresolved -- possible Russian/Cuban SIGINT ties

ACTORS (9):
  us_government             -- WH/State/Treasury rhetoric toward Cuba
  us_sanctions_regulatory   -- OFAC, Commerce, Treasury specific actions
  us_military_posture       -- SOUTHCOM, GTMO, Coast Guard interdictions
  cuban_government          -- Diaz-Canel, PCC, Granma editorial line
  cuban_military_security   -- FAR, MININT, G2 posture
  cuban_dissidents          -- Opposition signals (INVERSE indicator)
  russia_cuba_axis          -- Kremlin-Havana signals
  china_cuba_axis           -- Beijing-Havana signals
  iran_cuba_axis            -- Tehran-Havana signals

COMPOSITE VECTORS (3):
  us_pressure        -- max(us_gov, us_sanc, us_mil)
  regime_fracture    -- max(cu_diss - cu_mil, 0)  [inverse: high diss + low suppress = fracture]
  adversary_access   -- max(ru_axis, cn_axis, ir_axis)

REDIS KEYS:
  Cache:         rhetoric:cuba:latest
  History:       rhetoric:cuba:history
  Cross-theater: rhetoric:crosstheater:fingerprints (READS + WRITES)
  Summary:       rhetoric:cuba:summary

ENDPOINTS:
  GET /api/rhetoric/cuba
  GET /api/rhetoric/cuba/summary
  GET /api/rhetoric/cuba/history

CROSS-THEATER:
  READS from russia, iran, china fingerprints for boost multipliers
  WRITES cuba fingerprint with migration_surge_signal for WHA spillover tracking

SOURCE STRATEGY:
  Primary RSS:  Granma, Cubadebate, Prensa Latina (state),
                14ymedio, Diario de Cuba, CiberCuba, ADN Cuba, CubaNet (dissident),
                Miami Herald Cuba beat (English),
                OFAC Recent Actions (US govt)
  GDELT:        eng, spa, rus, zho, fas -- multi-language (Spanish is CRITICAL)
  Bluesky:      Trump Truth Social mirror, State Dept, Rubio (deferred to Session B)

CHANGELOG:
  v1.0.0 (2026-04-20): Initial build -- 9-actor inverted model with three-question frame

COPYRIGHT 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import threading
import time
import requests
import xml.etree.ElementTree as ET
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from flask import jsonify, request

# Signal interpreter (Red Lines + So What)
try:
    from cuba_signal_interpreter import (
        check_red_lines,
        build_so_what,
        build_historical_matches,
    )
    _INTERPRETER_AVAILABLE = True
except ImportError as e:
    print(f"[Cuba Rhetoric] WARNING: cuba_signal_interpreter not available ({e})")
    _INTERPRETER_AVAILABLE = False


# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
GDELT_BASE_URL      = 'https://api.gdeltproject.org/api/v2/doc/doc'

RHETORIC_CACHE_KEY  = 'rhetoric:cuba:latest'
HISTORY_KEY         = 'rhetoric:cuba:history'
SUMMARY_KEY         = 'rhetoric:cuba:summary'
CROSSTHEATER_KEY    = 'rhetoric:crosstheater:fingerprints'

RHETORIC_CACHE_TTL  = 12 * 3600
SCAN_INTERVAL_HOURS = 12

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ESCALATION LEVELS
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Baseline',        'color': '#6b7280', 'description': 'Routine statements, no significant signals above noise'},
    1: {'label': 'Rhetoric',        'color': '#3b82f6', 'description': 'Standard rhetoric, formulaic warnings, routine diplomatic language'},
    2: {'label': 'Warning',         'color': '#f59e0b', 'description': 'Elevated signal tempo, escalatory language above baseline'},
    3: {'label': 'Confrontation',   'color': '#f97316', 'description': 'Named actions, explicit threat signals, sanctions designations, access agreements'},
    4: {'label': 'Coercion',        'color': '#ef4444', 'description': 'Hard-power posturing, military deployment, confirmed adversary access'},
    5: {'label': 'Active Conflict', 'color': '#dc2626', 'description': 'Kinetic action, regime collapse, confirmed SIGINT/base operational'},
}


# ============================================
# ACTORS (9)
# ============================================
# Note: keywords list is a starting set. Expand during tuning with live data.
# Rule of thumb: if a keyword does NOT help answer one of the three analytical
# questions, it does not belong in the ladder.

ACTORS = {

    # ============================================
    # GROUP A: INBOUND US PRESSURE ACTORS (3)
    # ============================================

    'us_government': {
        'name': 'U.S. Government',
        'flag': '🇺🇸',
        'icon': '🏛️',
        'color': '#2563eb',
        'role': 'WH / State / Treasury -- Political Rhetoric Toward Cuba',
        'description': (
            'US executive branch political rhetoric and policy language targeting Cuba. '
            'Watch for: regime change framing, terror designations, democracy/human rights '
            'language, Rubio statements (Cuban-American, direct signal source), Trump Cuba '
            'rhetoric, State Department briefings.'
        ),
        'keywords': [
            # Executive
            'trump cuba', 'biden cuba', 'white house cuba', 'us president cuba',
            'state department cuba', 'secretary of state cuba', 'rubio cuba',
            'marco rubio cuba', 'us ambassador cuba', 'us embassy havana',
            'us chief of mission havana',
            # Political framing
            'cuba regime change', 'cuba dictatorship', 'cuban communist regime',
            'cuba human rights', 'cuba political prisoners', 'cuba repression',
            'cuba free elections', 'cuba democracy', 'cuba freedom',
            # Designations & policy
            'cuba state sponsor of terrorism', 'cuba terror list',
            'cuba national security', 'cuba threat', 'cuba policy review',
            'cuba national security memorandum',
            # Policy instruments
            'cuba sanctions bill', 'cuba congress', 'cuba legislation',
            'cuba-related executive order',
            # Spanish equivalents
            'estados unidos cuba', 'washington cuba', 'gobierno cuba estados unidos',
            'casa blanca cuba', 'departamento de estado cuba',
            'rubio declara cuba', 'trump declara cuba',
        ],
        'baseline_statements_per_week': 15,
        'tripwires': [
            'trump threatens cuba',
            'us warns cuba',
            'us calls for cuba regime change',
            'us reviews cuba policy',
            'rubio cuba ultimatum',
            'us breaks diplomatic relations cuba',
        ],
    },

    'us_sanctions_regulatory': {
        'name': 'U.S. Sanctions & Regulatory',
        'flag': '🇺🇸',
        'icon': '⚖️',
        'color': '#1e40af',
        'role': 'OFAC / Commerce / Treasury -- Specific Regulatory Actions',
        'description': (
            'Named sanctions, designations, and regulatory actions (distinct from rhetoric). '
            'Watch for: OFAC SDN additions, remittance caps, travel restrictions, Helms-Burton '
            'Title III activations, GAESA/CIMEX designations, secondary sanctions.'
        ),
        'keywords': [
            # OFAC actions
            'ofac cuba', 'treasury cuba sanctions', 'sdn list cuba',
            'cuba sanctions designation', 'cuba blocking order',
            'cuba sanctions list', 'cuba sanctions update',
            # Remittance
            'cuba remittance cap', 'cuba remittance restriction', 'western union cuba',
            'cuba remittance ban', 'cuba money transfer',
            # Travel
            'cuba travel ban', 'cuba travel restriction', 'us travel warning cuba',
            'cuba people-to-people travel', 'cuba tourism ban',
            # Trade/business
            'cuba embargo', 'helms-burton', 'title iii cuba', 'helms burton title iii',
            'commerce department cuba', 'cuba export control',
            'cuba trade restriction',
            # Terror list
            'cuba state sponsor of terrorism', 'cuba sstl',
            'cuba terror designation', 'cuba terror list',
            # Actions against specific entities
            'cimex sanctions', 'gaesa sanctions', 'cuba military holding',
            'gaesa designation', 'cimex designation',
            # Spanish
            'sanciones cuba', 'lista negra cuba', 'embargo estados unidos cuba',
            'lista sdn cuba', 'restricciones remesas cuba',
        ],
        'baseline_statements_per_week': 8,
        'tripwires': [
            'new cuba sanctions',
            'cuba added to sdn list',
            'cuba remittance ban',
            'helms burton title iii activated',
            'secondary sanctions cuba',
        ],
    },

    'us_military_posture': {
        'name': 'U.S. Military Posture',
        'flag': '🇺🇸',
        'icon': '⚓',
        'color': '#0891b2',
        'role': 'SOUTHCOM / GTMO / Coast Guard -- Kinetic / Hard Posture',
        'description': (
            'US military and law-enforcement posture toward Cuba. Watch for: SOUTHCOM exercises '
            'in Caribbean, GTMO reinforcement signals, Coast Guard interdiction tempo (migration '
            'indicator), US naval presence Florida Straits, military contingency discussions.'
        ),
        'keywords': [
            # SOUTHCOM
            'southcom cuba', 'southern command cuba', 'southcom commander cuba',
            'southcom exercise caribbean', 'southcom posture cuba',
            'southcom caribbean', 'ussouthcom cuba',
            # Guantanamo
            'guantanamo bay', 'gtmo cuba', 'guantanamo naval station',
            'guantanamo exercise', 'gtmo expansion', 'guantanamo migrants',
            'guantanamo migrant processing', 'gtmo facility',
            # Coast Guard (migration interdiction)
            'coast guard cuba', 'cuba migrant interdiction', 'cuba maritime',
            'cuban rafters intercepted', 'florida straits coast guard',
            'cuba migrants intercepted', 'uscg cuba',
            'coast guard havana', 'florida straits migration',
            # Naval
            'us navy caribbean', 'us destroyer cuba', 'us navy gulf mexico',
            'us military exercise cuba', 'us forces caribbean',
            'us naval presence caribbean', 'us warship caribbean',
            # Spanish
            'marina estados unidos cuba', 'guardia costera cuba',
            'southcom ejercicio caribe', 'base guantanamo',
        ],
        'baseline_statements_per_week': 5,
        'tripwires': [
            'us warship cuba',
            'gtmo reinforcement',
            'coast guard surge cuba',
            'southcom cuba contingency',
            'us naval blockade cuba',
            'us forces caribbean deployment',
        ],
    },

    # ============================================
    # GROUP B: CUBAN REGIME RESPONSE ACTORS (3)
    # ============================================

    'cuban_government': {
        'name': 'Cuban Government',
        'flag': '🇨🇺',
        'icon': '🏛️',
        'color': '#dc2626',
        'role': 'Diaz-Canel / PCC / MINREX -- Regime Political Line',
        'description': (
            'Cuban regime rhetoric -- defensive framing, anti-imperialist language, '
            'diplomatic posture. Watch for: Diaz-Canel speeches, Granma editorial shifts, '
            'MINREX statements, UN ambassador posture, "bloqueo" framing intensification, '
            'mobilization rhetoric.'
        ),
        'keywords': [
            # Leadership
            'diaz-canel', 'miguel diaz-canel', 'diaz canel',
            'cuba president', 'presidente cuba',
            'raul castro', 'esteban lazo', 'manuel marrero',
            'cuba prime minister', 'primer ministro cuba',
            'cuba foreign minister', 'bruno rodriguez cuba', 'bruno rodriguez parrilla',
            'cuba parliament', 'asamblea nacional cuba',
            # Party
            'communist party cuba', 'partido comunista cuba', 'pcc cuba',
            'central committee cuba', 'comite central cuba',
            # Official media
            'granma editorial', 'granma cuba', 'prensa latina cuba',
            'cubadebate', 'juventud rebelde', 'trabajadores cuba',
            # Framing
            'cuba sovereignty', 'cuba revolution', 'cuba anti-imperialist',
            'cuba blockade', 'cuba us aggression', 'cuba resistance',
            'bloqueo yankee', 'injerencia estados unidos cuba',
            'cuba victima', 'soberania cubana',
            'revolucion cubana', 'imperialismo yanqui cuba',
            # Diplomatic
            'cuba foreign ministry', 'minrex cuba', 'cuba un ambassador',
            'cuba condemns us', 'cuba rejects us',
            'cuba recalls ambassador', 'cuba summons ambassador',
            # Spanish
            'presidente cuba', 'gobierno cuba declara', 'cancilleria cuba',
            'revolucion cubana', 'bloqueo economico cuba',
            'cuba denuncia estados unidos',
        ],
        'baseline_statements_per_week': 20,
        'tripwires': [
            'diaz-canel mobilizes',
            'cuba state of emergency',
            'cuba breaks diplomatic relations',
            'cuba ambassador recalled',
            'cuba martial law',
            'cuba emergency powers',
        ],
    },

    'cuban_military_security': {
        'name': 'Cuban Military & Security',
        'flag': '🇨🇺',
        'icon': '🪖',
        'color': '#991b1b',
        'role': 'FAR / MININT / G2 -- Coercive Apparatus',
        'description': (
            'Regime security forces: FAR (army), MININT (interior ministry), G2 (state security). '
            'Watch for: protest suppression intensity, mass arrests, Boinas Negras deployments, '
            'military exercises, mobilization against dissidents. Crossing from MININT-only to '
            'FAR deployment against civilians = major red line.'
        ),
        'keywords': [
            # Military
            'cuban armed forces', 'far cuba', 'fuerzas armadas cuba',
            'cuba ministry of interior', 'minint cuba',
            'cuba general lopez-calleja', 'cuban generals',
            'cuban military command', 'cuba defense minister',
            'general alvaro lopez miera', 'cuba military leadership',
            # Security services
            'g2 cuba', 'cuban intelligence', 'cuban state security',
            'seguridad del estado cuba', 'dsi cuba',
            'cuban secret police', 'cuban counterintelligence',
            # Protest suppression
            'cuba protest crackdown', 'cuba arrests protesters',
            'cuba black berets', 'boinas negras cuba',
            'cuba dissident detention', 'cuba political prisoner',
            'cuba rapid response brigade', 'brigada de respuesta rapida',
            'cuba mass arrests', 'represion cuba',
            'cuba detention protesters', 'cuba jailed dissidents',
            # Military exercises
            'cuba military exercise', 'bastion exercise cuba',
            'cuba mobilization', 'cuba military drill',
            'ejercicio bastion cuba', 'cuba war games',
            # Cyber
            'cuba cyber operation', 'cuba hacking', 'cuban intelligence operation',
            'cuba state hacking', 'cuba cyber attack',
        ],
        'baseline_statements_per_week': 5,
        'tripwires': [
            'cuba deploys troops',
            'cuba arrests dissidents mass',
            'cuba bastion exercise',
            'cuba military mobilization',
            'far deployed cuba',
            'cuba army street',
        ],
    },

    'cuban_dissidents': {
        'name': 'Cuban Dissidents',
        'flag': '🇨🇺',
        'icon': '✊',
        'color': '#f59e0b',
        'role': 'Opposition / Diaspora / Civil Society -- INVERSE INDICATOR',
        'description': (
            'INVERSE INDICATOR: high dissident activity = weaker regime, not stronger Cuba. '
            'This actor feeds into regime_fracture_level as "high diss - low suppression = '
            'fracture." Watch for: protest waves, 11J anniversaries, San Isidro movement, '
            'independent media signal, diaspora mobilization, named dissident arrests/releases.'
        ),
        'keywords': [
            # Movements & protests
            'cuba protest', 'protesta cuba', '11 julio cuba', '11j cuba',
            'cuba manifestacion', 'cuba civil unrest', 'patria y vida',
            'cuba san isidro', 'movimiento san isidro',
            'cuba uprising', 'cuba street protest',
            'cuba demonstrations', 'cuba nationwide protest',
            # Figures
            'jose daniel ferrer', 'oscar elias biscet', 'guillermo farinas',
            'ladies in white', 'damas de blanco',
            'yoani sanchez', 'luis manuel otero alcantara',
            'maykel osorbo', 'el funky',
            'carolina barrero', 'julio cesar alfonso',
            # Organizations
            'cuba decide', 'comision cubana derechos humanos',
            'observatorio cubano derechos humanos',
            'unpacu cuba', 'patriotic union cuba',
            'cuban commission human rights',
            # Diaspora
            'cuban american national foundation', 'fnca cuba',
            'cuba diaspora', 'miami cuban', 'cuban exile',
            'cuban-american community', 'little havana',
            # Independent media
            '14ymedio', 'diario de cuba', 'cibercuba', 'adn cuba',
            'cubanet', 'periodismo de barrio',
            'el toque cuba', 'tremenda nota',
            # Signals
            'cuba defector', 'cuba dissident released', 'cuba dissident jailed',
            'cuba prisoner of conscience',
        ],
        'baseline_statements_per_week': 10,
        'tripwires': [
            'cuba nationwide protests',
            'cuba general strike',
            'cuba regime collapse',
            'cuba defectors mass',
            'cuba uprising',
            'cuba revolution 2.0',
        ],
    },

    # ============================================
    # GROUP C: ADVERSARY EXPLOITATION ACTORS (3)
    # ============================================

    'russia_cuba_axis': {
        'name': 'Russia-Cuba Axis',
        'flag': '🇷🇺',
        'icon': '🤝',
        'color': '#7c3aed',
        'role': 'Kremlin-Havana Cooperation Signals',
        'description': (
            'Russian access, military presence, and economic support signals in Cuba. '
            'Watch for: Lourdes SIGINT rumors, Russian warship Caribbean visits, Lavrov/Medvedev '
            'Cuba visits, Rosneft oil shipments, ruble cooperation, intelligence signals. '
            'Lourdes reactivation would be Category 5.'
        ),
        'keywords': [
            # Diplomatic
            'russia cuba', 'rusia cuba', 'putin cuba', 'medvedev cuba',
            'lavrov cuba visit', 'lavrov havana', 'russia foreign minister cuba',
            'rosneft cuba', 'russian delegation cuba',
            'russia cuba agreement', 'russia cuba mou',
            'russia cuba partnership', 'russia cuba cooperation',
            # Military / SIGINT
            'lourdes cuba', 'lourdes sigint', 'lourdes station cuba',
            'lourdes reactivation', 'lourdes listening post',
            'bejucal cuba russia', 'russian sigint cuba', 'russian signals cuba',
            'russian submarine cuba', 'russian warship cuba', 'russian naval cuba',
            'admiral gorshkov cuba', 'russia black sea fleet cuba',
            'russian navy caribbean', 'russian fleet cuba',
            # Energy / economic
            'russia oil cuba', 'russia tanker cuba', 'russia cuba oil shipment',
            'russia cuba financial', 'russia cuba ruble',
            'russia cuba economy', 'rosneft havana',
            'russia cuba credit', 'russia cuba loan',
            'russia cuba fuel', 'russia cuba energy',
            # Intelligence
            'russia cuba espionage', 'russian intelligence cuba',
            'gru cuba', 'svr cuba', 'russian spies cuba',
            # Russian-language
            'Куба Россия', 'Россия Куба визит', 'Путин Куба',
            'Лавров Куба', 'Росснефть Куба',
        ],
        'baseline_statements_per_week': 3,
        'tripwires': [
            'russian warship docked cuba',
            'lourdes reactivated',
            'russia cuba defense pact',
            'russian troops cuba',
            'russian submarine havana',
            'lourdes sigint operational',
        ],
    },

    'china_cuba_axis': {
        'name': 'China-Cuba Axis',
        'flag': '🇨🇳',
        'icon': '🤝',
        'color': '#be185d',
        'role': 'Beijing-Havana Access & Investment Signals',
        'description': (
            'Chinese access, SIGINT, port investment, and infrastructure signals in Cuba. '
            'Watch for: spy base reporting (WSJ 2023 pattern), PLAN warship visits to Mariel, '
            'Huawei/ZTE infrastructure, BRI inclusion, Xi/Wang Yi Cuba visits. PLAN Mariel '
            'visit = Category 5.'
        ),
        'keywords': [
            # Diplomatic
            'china cuba', 'xi jinping cuba', 'wang yi cuba',
            'china ambassador havana', 'chinese delegation cuba',
            'china cuba partnership', 'china cuba cooperation',
            'belt and road cuba', 'bri cuba', 'china cuba agreement',
            'china cuba strategic partnership',
            # SIGINT (WSJ 2023 reporting)
            'china spy base cuba', 'china sigint cuba', 'chinese listening post cuba',
            'bejucal china', 'wsj cuba china spy',
            'china listening station cuba', 'china signals cuba',
            'china eavesdropping cuba',
            # Military
            'china plan cuba', 'chinese navy cuba', 'plan warship cuba',
            'chinese military cuba', 'china cuba military training',
            'china warship caribbean', 'pla navy cuba',
            'chinese fleet cuba',
            # Infrastructure
            'mariel port china', 'china cuba port', 'china cuba railway',
            'huawei cuba', 'zte cuba', 'china cuba telecom',
            'china cuba 5g', 'china cuba infrastructure',
            'china cuba fiber optic', 'cofco cuba',
            # Economic
            'china cuba loan', 'china cuba credit', 'china cuba debt',
            'china cuba tourism', 'china cuba trade',
            'china cuba investment', 'china cuba finance',
            # Chinese-language
            '中国古巴', '习近平古巴', '古巴外交',
            '中古关系', '王毅古巴',
        ],
        'baseline_statements_per_week': 2,
        'tripwires': [
            'china spy base cuba confirmed',
            'plan warship mariel',
            'xi visits cuba',
            'china cuba defense agreement',
            'china naval base cuba',
            'chinese warship havana',
        ],
    },

    'iran_cuba_axis': {
        'name': 'Iran-Cuba Axis',
        'flag': '🇮🇷',
        'icon': '🤝',
        'color': '#059669',
        'role': 'Tehran-Havana IRGC / Oil / Proxy Signals',
        'description': (
            'Iranian access signals in Cuba. Sparser than RU/CN but strategically significant. '
            'Watch for: IRGC delegations, Iranian oil tanker destinations, Pezeshkian/Khamenei '
            'statements on Cuba, Hezbollah Cuba activity, Iran-Cuba MOUs. Iran tanker '
            'dockings = recurring pattern since 2020.'
        ),
        'keywords': [
            # Diplomatic
            'iran cuba', 'raisi cuba', 'pezeshkian cuba',
            'iran cuba delegation', 'iran cuba agreement',
            'khamenei cuba', 'iran foreign minister cuba',
            'iran president cuba', 'iran cuba cooperation',
            'iran cuba visit',
            # IRGC
            'irgc cuba', 'quds force cuba', 'iran revolutionary guard cuba',
            'iran military cuba', 'iran defense cuba',
            'irgc havana', 'quds force caribbean',
            # Oil & economic
            'iran oil cuba', 'iran tanker cuba', 'iran cuba oil shipment',
            'iran cuba fuel', 'iran cuba petroleum',
            'iran cuba economy', 'iran cuba trade',
            'iranian tanker havana', 'iran crude cuba',
            'iran venezuela cuba',  # often triangulated
            # Proxy / hezbollah
            'hezbollah cuba', 'iran proxy cuba', 'iran latin america',
            'hezbollah latin america',
            # Persian-language
            'ایران کوبا', 'کوبا تهران', 'رئیسی کوبا',
            'پزشکیان کوبا', 'خامنه‌ای کوبا',
        ],
        'baseline_statements_per_week': 1,
        'tripwires': [
            'iran tanker cuba docked',
            'irgc cuba presence',
            'iran cuba defense pact',
            'hezbollah cuba cell',
            'iran warship cuba',
            'quds force havana',
        ],
    },
}


# ============================================
# COMPOSITE VECTOR TRIGGERS
# ============================================
# Unlike Russia's 5 vectors (nuclear/ground_ops/nato_flank/arctic/hybrid),
# Cuba uses 3 composite vectors that map to the three analytical questions.
# These are COMPUTED from actor escalation levels (see _compute_vectors below)
# rather than keyword-scored directly -- so this section is mostly documentation.
#
# us_pressure      = max(us_gov.level, us_sanc.level, us_mil.level)
# regime_fracture  = max(cu_diss.level - cu_mil.level, 0)
# adversary_access = max(ru_axis.level, cn_axis.level, ir_axis.level)

VECTOR_DESCRIPTIONS = {
    'us_pressure':      'Maximum of us_government, us_sanctions_regulatory, us_military_posture escalation levels. Answers: "Is Washington escalating?"',
    'regime_fracture':  'Cuban dissident level minus regime security level (floored at 0). Answers: "Is the regime cracking?"',
    'adversary_access': 'Maximum of russia_cuba_axis, china_cuba_axis, iran_cuba_axis escalation levels. Answers: "Who else is circling?"',
}


# ============================================
# SOURCE STRATEGY
# ============================================
RHETORIC_RSS_FEEDS = [
    # Cuban state media (Spanish)
    {'url': 'http://www.granma.cu/rss.xml',                      'name': 'Granma (Official)',           'weight': 1.0, 'lang': 'es'},
    {'url': 'https://www.cubadebate.cu/feed/',                   'name': 'Cubadebate (State)',          'weight': 0.95, 'lang': 'es'},
    {'url': 'https://www.prensa-latina.cu/feed/',                'name': 'Prensa Latina (State)',       'weight': 0.90, 'lang': 'es'},

    # Cuban dissident / independent
    {'url': 'https://www.14ymedio.com/rss/',                     'name': '14ymedio (Dissident)',        'weight': 1.0, 'lang': 'es'},
    {'url': 'https://diariodecuba.com/rss.xml',                  'name': 'Diario de Cuba (Dissident)',  'weight': 0.95, 'lang': 'es'},
    {'url': 'https://www.cibercuba.com/rss.xml',                 'name': 'CiberCuba (Dissident)',       'weight': 0.90, 'lang': 'es'},
    {'url': 'https://adncuba.com/feed',                          'name': 'ADN Cuba (Dissident)',        'weight': 0.90, 'lang': 'es'},
    {'url': 'https://www.cubanet.org/feed/',                     'name': 'CubaNet (Dissident)',         'weight': 0.90, 'lang': 'es'},

    # English-language Cuba coverage
    {'url': 'https://www.miamiherald.com/news/nation-world/world/americas/cuba/?widgetName=rssfeed&widgetContentId=712015&getXmlFeed=true',
                                                                 'name': 'Miami Herald Cuba',           'weight': 1.0, 'lang': 'en'},

    # US govt
    {'url': 'https://ofac.treasury.gov/recent-actions/rss',      'name': 'OFAC Recent Actions',         'weight': 1.0, 'lang': 'en'},

    # Regional context (Spanish wire services)
    {'url': 'https://www.efe.com/efe/america/rss/1',             'name': 'EFE Americas',                'weight': 0.80, 'lang': 'es'},
]

# GDELT query strategy: Cuba in multiple languages.
# Spanish is CRITICAL -- signal volume ~= English for this tracker.
GDELT_QUERIES = {
    'eng': 'Cuba OR Havana OR "Cuban regime" OR "Cuba sanctions"',
    'spa': 'Cuba OR "La Habana" OR "régimen cubano" OR "bloqueo cubano"',
    'rus': 'Куба OR Гавана',
    'zho': '古巴 OR 哈瓦那',
    'fas': 'کوبا OR هاوانا',
}


# ============================================
# REDIS HELPERS
# ============================================
def _redis_get(key):
    """Upstash REST GET."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        r = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{urllib.parse.quote(key, safe='')}",
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get('result') is None:
                return None
            return json.loads(data['result'])
    except Exception as e:
        print(f"[Cuba Rhetoric] Redis GET error ({key}): {e}")
    return None


def _redis_set(key, value, ttl=None):
    """Upstash REST SET."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value)
        url = f"{UPSTASH_REDIS_URL}/set/{urllib.parse.quote(key, safe='')}"
        if ttl:
            url += f"?EX={ttl}"
        r = requests.post(
            url,
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            data=payload,
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[Cuba Rhetoric] Redis SET error ({key}): {e}")
        return False


def _redis_lpush_trim(key, value, max_len=336):
    """LPUSH + LTRIM to keep rolling history (336 = 14 days of 1-hour entries)."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value)
        r = requests.post(
            f"{UPSTASH_REDIS_URL}/lpush/{urllib.parse.quote(key, safe='')}",
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            data=payload,
            timeout=10,
        )
        if r.status_code != 200:
            return False
        requests.post(
            f"{UPSTASH_REDIS_URL}/ltrim/{urllib.parse.quote(key, safe='')}/0/{max_len - 1}",
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=10,
        )
        return True
    except Exception as e:
        print(f"[Cuba Rhetoric] Redis LPUSH error ({key}): {e}")
        return False


# ============================================
# DATE PARSING
# ============================================
def _parse_pub_date(pub_str):
    if not pub_str:
        return None
    try:
        return datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
    except Exception:
        pass
    try:
        return parsedate_to_datetime(pub_str).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        clean = pub_str.replace('T', '').replace('Z', '').replace('-', '').replace(':', '').replace(' ', '')
        if len(clean) >= 14:
            return datetime.strptime(clean[:14], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        elif len(clean) == 8:
            return datetime.strptime(clean[:8], '%Y%m%d').replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None


# ============================================
# FETCHERS
# ============================================
def _fetch_rss(url, source_name, weight=0.85, lang='en', max_items=20):
    """Fetch RSS feed and normalize to article dicts."""
    articles = []
    try:
        resp = requests.get(
            url,
            timeout=(5, 12),
            headers={'User-Agent': 'Mozilla/5.0 AsifahAnalytics/1.0'},
        )
        if resp.status_code != 200:
            print(f"[Cuba RSS] {source_name}: HTTP {resp.status_code}")
            return []
        root = ET.fromstring(resp.content)
        for item in root.findall('.//item')[:max_items]:
            title_el = item.find('title')
            link_el  = item.find('link')
            pub_el   = item.find('pubDate')
            desc_el  = item.find('description')
            if title_el is None or not title_el.text:
                continue
            articles.append({
                'title':       title_el.text.strip(),
                'description': (desc_el.text or title_el.text or '')[:500] if desc_el is not None else '',
                'url':         link_el.text.strip() if link_el is not None and link_el.text else '',
                'publishedAt': pub_el.text if pub_el is not None else '',
                'source':      {'name': source_name},
                'content':     title_el.text.strip(),
                'source_weight_override': weight,
                'language':    lang,
                'feed_type':   'rss',
            })
        print(f"[Cuba RSS] {source_name}: {len(articles)} articles")
    except ET.ParseError as e:
        print(f"[Cuba RSS] {source_name}: XML parse error: {str(e)[:80]}")
    except Exception as e:
        print(f"[Cuba RSS] {source_name}: {str(e)[:80]}")
    return articles


def _fetch_gdelt(query, language='eng', days=3, max_records=25):
    """Fetch GDELT articles for a language/query. Returns normalized article dicts."""
    articles = []
    try:
        params = {
            'query':      query,
            'mode':       'artlist',
            'maxrecords': max_records,
            'timespan':   f'{days}d',
            'format':     'json',
            'sourcelang': language,
        }
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=(5, 15))
        if resp.status_code == 429:
            print(f"[Cuba GDELT] 429 rate limit -- skipping: {language}")
            return []
        if resp.status_code == 200:
            # GDELT returns non-JSON on soft-block -- defensive parse
            try:
                payload = resp.json()
            except Exception:
                print(f"[Cuba GDELT] {language}: non-JSON response (soft block)")
                return []
            lang_map = {'eng': 'en', 'spa': 'es', 'rus': 'ru', 'zho': 'zh', 'fas': 'fa'}
            for art in payload.get('articles', []):
                articles.append({
                    'title':       art.get('title', ''),
                    'description': art.get('title', ''),
                    'url':         art.get('url', ''),
                    'publishedAt': art.get('seendate', ''),
                    'source':      {'name': f"GDELT ({language})"},
                    'content':     art.get('title', ''),
                    'language':    lang_map.get(language, language),
                    'feed_type':   'gdelt',
                })
        else:
            print(f"[Cuba GDELT] {language}: HTTP {resp.status_code}")
        time.sleep(0.5)  # polite spacing between language calls
    except Exception as e:
        print(f"[Cuba GDELT] {language} error: {str(e)[:80]}")
    return articles


def _fetch_all_articles():
    """Fetch from all RSS sources and GDELT. Returns deduplicated article list."""
    articles = []

    # RSS feeds
    for src in RHETORIC_RSS_FEEDS:
        try:
            fetched = _fetch_rss(
                src['url'],
                src['name'],
                weight=src.get('weight', 0.85),
                lang=src.get('lang', 'en'),
            )
            articles.extend(fetched)
        except Exception as e:
            print(f"[Cuba RSS] {src.get('name', 'unknown')} error: {str(e)[:80]}")

    # GDELT -- all language queries
    gdelt_count = 0
    for language, query in GDELT_QUERIES.items():
        try:
            fetched = _fetch_gdelt(query, language=language)
            articles.extend(fetched)
            gdelt_count += len(fetched)
        except Exception as e:
            print(f"[Cuba GDELT] {language} error: {str(e)[:80]}")

    print(f"[Cuba Rhetoric] Total articles fetched: {len(articles)} ({gdelt_count} from GDELT)")

    # Deduplicate by URL or title
    seen = set()
    unique = []
    for art in articles:
        key = art.get('url') or art.get('title', '')
        if key and key not in seen:
            seen.add(key)
            unique.append(art)

    print(f"[Cuba Rhetoric] After dedup: {len(unique)} articles")
    return unique


# ============================================
# ARTICLE CLASSIFICATION
# ============================================
def _score_article_for_actor(article, actor_key, actor_def):
    """Score an article for a specific actor. Returns (level, trigger_phrase)."""
    title = (article.get('title') or '').lower()
    desc  = (article.get('description') or '').lower()
    text  = f"{title} {desc}"

    for kw in actor_def.get('keywords', []):
        if kw.lower() in text:
            # Tripwires elevate match to L4 (Coercion level)
            for tw in actor_def.get('tripwires', []):
                if tw.lower() in text:
                    return 4, tw
            return 1, kw
    return 0, None


def _classify_articles(articles):
    """
    Classify all articles against the 9 Cuba actors.
    Returns actor_results dict keyed by actor_key.
    """
    actor_results = {}
    for actor_key, actor_def in ACTORS.items():
        matched = []
        max_level = 0
        max_trigger = None

        for art in articles:
            level, trigger = _score_article_for_actor(art, actor_key, actor_def)
            if level > 0:
                art_copy = dict(art)
                art_copy['escalation_level'] = level
                art_copy['trigger_phrase']   = trigger
                matched.append(art_copy)
                if level > max_level:
                    max_level   = level
                    max_trigger = trigger

        # If multiple keywords matched at L1, count of matches bumps level
        # (5+ matches = L2, 10+ = L3 -- reasonable density heuristic)
        if max_level == 1 and len(matched) >= 10:
            max_level = 3
        elif max_level == 1 and len(matched) >= 5:
            max_level = 2

        # Sort matched by escalation desc, then by date desc
        matched.sort(key=lambda x: -x.get('escalation_level', 0))

        actor_results[actor_key] = {
            'name':              actor_def['name'],
            'flag':              actor_def.get('flag', ''),
            'icon':              actor_def.get('icon', ''),
            'color':             actor_def.get('color', '#6b7280'),
            'role':              actor_def.get('role', ''),
            'description':       actor_def.get('description', ''),
            'escalation_level':  max_level,
            'escalation_label':  ESCALATION_LEVELS.get(max_level, {}).get('label', 'Baseline'),
            'escalation_color':  ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
            'escalation_phrase': max_trigger,
            'statement_count':   len(matched),
            'top_articles':      matched[:5],
            'silence_alert':     len(matched) == 0,
        }

    return actor_results


# ============================================
# COMPOSITE VECTORS (Cuba-specific)
# ============================================
def _compute_vectors(actor_results):
    """
    Compute the three composite vectors that map to the three analytical questions.

    us_pressure       -- Q1: Is Washington escalating?
    regime_fracture   -- Q2: Is the regime cracking?
    adversary_access  -- Q3: Who else is circling?
    """
    def lvl(key):
        return actor_results.get(key, {}).get('escalation_level', 0)

    us_gov   = lvl('us_government')
    us_sanc  = lvl('us_sanctions_regulatory')
    us_mil   = lvl('us_military_posture')
    cu_gov   = lvl('cuban_government')
    cu_mil   = lvl('cuban_military_security')
    cu_diss  = lvl('cuban_dissidents')
    ru_axis  = lvl('russia_cuba_axis')
    cn_axis  = lvl('china_cuba_axis')
    ir_axis  = lvl('iran_cuba_axis')

    us_pressure      = max(us_gov, us_sanc, us_mil)
    regime_fracture  = max(cu_diss - cu_mil, 0)
    adversary_access = max(ru_axis, cn_axis, ir_axis)

    return {
        'us_pressure':      us_pressure,
        'us_pressure_label': ESCALATION_LEVELS.get(us_pressure, {}).get('label', 'Baseline'),
        'regime_fracture':  regime_fracture,
        'regime_fracture_label': ESCALATION_LEVELS.get(regime_fracture, {}).get('label', 'Baseline'),
        'adversary_access': adversary_access,
        'adversary_access_label': ESCALATION_LEVELS.get(adversary_access, {}).get('label', 'Baseline'),
        # Raw actor levels for So What consumption
        'us_gov':   us_gov,
        'us_sanc':  us_sanc,
        'us_mil':   us_mil,
        'cu_gov':   cu_gov,
        'cu_mil':   cu_mil,
        'cu_diss':  cu_diss,
        'ru_axis':  ru_axis,
        'cn_axis':  cn_axis,
        'ir_axis':  ir_axis,
    }


# ============================================
# CROSS-THEATER READS (boost Cuba actors from RU/IR/CN fingerprints)
# ============================================
def _apply_crosstheater_reads(actor_results):
    """
    Pull Russia, Iran, China fingerprints and boost Cuba axis actors accordingly.
    Boost only applies if the Cuba actor is already at L2+ (otherwise we'd create
    signals from nothing). This models "reinforcement," not "fabrication."
    """
    cross = _redis_get(CROSSTHEATER_KEY) or {}

    russia_fp = cross.get('russia', {})
    iran_fp   = cross.get('iran', {})
    china_fp  = cross.get('china', {})

    boosts_applied = []

    # Russia cross-theater axis active --> boost russia_cuba_axis
    if russia_fp.get('iran_russia_active') or russia_fp.get('dprk_russia_active'):
        ru_result = actor_results.get('russia_cuba_axis', {})
        if ru_result.get('escalation_level', 0) >= 2:
            old = ru_result['escalation_level']
            ru_result['escalation_level'] = min(5, old + 1)
            ru_result['escalation_label'] = ESCALATION_LEVELS.get(ru_result['escalation_level'], {}).get('label', 'Baseline')
            ru_result['escalation_color'] = ESCALATION_LEVELS.get(ru_result['escalation_level'], {}).get('color', '#6b7280')
            ru_result['crosstheater_boost'] = 'Russia cross-theater axis active'
            boosts_applied.append(f'russia_cuba_axis L{old}->L{ru_result["escalation_level"]}')

    # Russia nuclear signaling --> boost us_military_posture (response posture)
    if russia_fp.get('nuclear_signaling'):
        us_mil = actor_results.get('us_military_posture', {})
        if us_mil.get('escalation_level', 0) >= 2:
            old = us_mil['escalation_level']
            us_mil['escalation_level'] = min(5, old + 1)
            us_mil['escalation_label'] = ESCALATION_LEVELS.get(us_mil['escalation_level'], {}).get('label', 'Baseline')
            us_mil['escalation_color'] = ESCALATION_LEVELS.get(us_mil['escalation_level'], {}).get('color', '#6b7280')
            us_mil['crosstheater_boost'] = 'Nuclear signaling triggers US posture response'
            boosts_applied.append(f'us_military_posture L{old}->L{us_mil["escalation_level"]}')

    # Iran IRGC high --> boost iran_cuba_axis
    if iran_fp.get('irgc_activity_level', 0) >= 3:
        ir_result = actor_results.get('iran_cuba_axis', {})
        if ir_result.get('escalation_level', 0) >= 2:
            old = ir_result['escalation_level']
            ir_result['escalation_level'] = min(5, old + 1)
            ir_result['escalation_label'] = ESCALATION_LEVELS.get(ir_result['escalation_level'], {}).get('label', 'Baseline')
            ir_result['escalation_color'] = ESCALATION_LEVELS.get(ir_result['escalation_level'], {}).get('color', '#6b7280')
            ir_result['crosstheater_boost'] = 'Iran IRGC activity elevated'
            boosts_applied.append(f'iran_cuba_axis L{old}->L{ir_result["escalation_level"]}')

    # China-Iran axis --> boost BOTH china_cuba_axis AND iran_cuba_axis
    if china_fp.get('china_iran_axis_level', 0) >= 3:
        for k in ['china_cuba_axis', 'iran_cuba_axis']:
            r = actor_results.get(k, {})
            if r.get('escalation_level', 0) >= 2:
                old = r['escalation_level']
                r['escalation_level'] = min(5, old + 1)
                r['escalation_label'] = ESCALATION_LEVELS.get(r['escalation_level'], {}).get('label', 'Baseline')
                r['escalation_color'] = ESCALATION_LEVELS.get(r['escalation_level'], {}).get('color', '#6b7280')
                r['crosstheater_boost'] = 'CN-IR axis reinforcing Cuba access'
                boosts_applied.append(f'{k} L{old}->L{r["escalation_level"]}')

    if boosts_applied:
        print(f"[Cuba Rhetoric] Cross-theater boosts: {', '.join(boosts_applied)}")
    else:
        print(f"[Cuba Rhetoric] No cross-theater boosts applied")

    return actor_results


# ============================================
# CROSS-THEATER WRITES (expose Cuba signals to other trackers)
# ============================================
def _write_crosstheater_fingerprint(actor_results, vectors):
    """
    Write Cuba signals to shared Redis cross-theater fingerprint key.
    Readable by Asia, Europe, ME, and (eventually) the Global Pressure Index.
    """
    ru_active = actor_results.get('russia_cuba_axis', {}).get('escalation_level', 0) >= 3
    cn_active = actor_results.get('china_cuba_axis',  {}).get('escalation_level', 0) >= 3
    ir_active = actor_results.get('iran_cuba_axis',   {}).get('escalation_level', 0) >= 3

    # Migration surge heuristic: high dissident activity + elevated US military posture
    migration_surge = (
        actor_results.get('cuban_dissidents', {}).get('escalation_level', 0) >= 3
        and actor_results.get('us_military_posture', {}).get('escalation_level', 0) >= 2
    )

    fingerprint = {
        'cuba': {
            'updated_at':             datetime.now(timezone.utc).isoformat(),
            'us_pressure_level':      vectors.get('us_pressure', 0),
            'regime_fracture_level':  vectors.get('regime_fracture', 0),
            'adversary_access_level': vectors.get('adversary_access', 0),
            'russia_cuba_active':     ru_active,
            'china_cuba_active':      cn_active,
            'iran_cuba_active':       ir_active,
            'us_escalation_active':   vectors.get('us_pressure', 0) >= 3,
            'migration_surge_signal': migration_surge,
        }
    }

    existing = _redis_get(CROSSTHEATER_KEY) or {}
    existing.update(fingerprint)
    _redis_set(CROSSTHEATER_KEY, existing)
    print(f"[Cuba Rhetoric] Cross-theater fingerprint written: "
          f"us={vectors.get('us_pressure', 0)} "
          f"fracture={vectors.get('regime_fracture', 0)} "
          f"adv={vectors.get('adversary_access', 0)} "
          f"migration={migration_surge}")


# ============================================
# MAIN SCAN
# ============================================
def run_cuba_rhetoric_scan(force=False):
    """Full Cuba rhetoric scan. Returns result dict."""
    global _rhetoric_running

    with _rhetoric_lock:
        if _rhetoric_running and not force:
            print("[Cuba Rhetoric] Scan already running -- returning cached")
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                return cached
            return {'success': False, 'error': 'Scan in progress'}
        _rhetoric_running = True

    try:
        print("[Cuba Rhetoric] Starting scan at " + datetime.now(timezone.utc).isoformat())
        start = time.time()

        # 1. Fetch all articles
        articles = _fetch_all_articles()

        # 2. Classify against 9 actors
        actor_results = _classify_articles(articles)

        # 3. Apply cross-theater boosts (Russia/Iran/China fingerprints)
        actor_results = _apply_crosstheater_reads(actor_results)

        # 4. Compute three composite vectors
        vectors = _compute_vectors(actor_results)

        # 5. Red Lines + So What (via signal interpreter)
        red_lines_triggered = []
        so_what = None
        if _INTERPRETER_AVAILABLE:
            try:
                red_lines_triggered = check_red_lines(articles, actor_results)
            except Exception as e:
                print(f"[Cuba Rhetoric] Red lines error: {str(e)[:120]}")
            try:
                scan_data_for_so_what = {'actors': actor_results, **vectors}
                historical_matches = build_historical_matches(actor_results, vectors) \
                    if 'build_historical_matches' in globals() else []
                so_what = build_so_what(scan_data_for_so_what, red_lines_triggered, historical_matches)
            except Exception as e:
                print(f"[Cuba Rhetoric] So What error: {str(e)[:120]}")

        # 6. Compute articles classified count
        articles_classified = sum(
            a.get('statement_count', 0) for a in actor_results.values()
        )

        # 7. Per-source count breakdowns (for Gold Standard pill strip on frontend)
        source_counts = _compute_source_counts(articles)

        scan_time = round(time.time() - start, 1)

        def _lvl(n):
            return ESCALATION_LEVELS.get(n, {}).get('label', 'Baseline')

        # Theatre-level headline score:
        # Cuba's theatre score = max of the three composite vectors
        theatre_level = max(
            vectors.get('us_pressure', 0),
            vectors.get('regime_fracture', 0),
            vectors.get('adversary_access', 0),
        )

        result = {
            'success':               True,
            'theatre':               'Cuba',
            'theatre_level':         theatre_level,
            'theatre_escalation_label': _lvl(theatre_level),
            'theatre_color':         '#38bdf8',  # arctic scheme accent

            # 9 actors
            'actors':                actor_results,

            # 3 composite vectors
            'us_pressure':           vectors.get('us_pressure', 0),
            'us_pressure_label':     vectors.get('us_pressure_label', 'Baseline'),
            'regime_fracture':       vectors.get('regime_fracture', 0),
            'regime_fracture_label': vectors.get('regime_fracture_label', 'Baseline'),
            'adversary_access':      vectors.get('adversary_access', 0),
            'adversary_access_label': vectors.get('adversary_access_label', 'Baseline'),

            # Interpreter output
            'red_lines':             red_lines_triggered,
            'so_what':               so_what,

            # Metadata
            'total_articles':        len(articles),
            'articles_classified':   articles_classified,
            'source_counts':         source_counts,

            # Gold Standard pill strip fields (on regional dashboard if ever embedded)
            'articles_scanned':      len(articles),

            'scan_time_seconds':     scan_time,
            'scanned_at':            datetime.now(timezone.utc).isoformat(),
            'timestamp':             datetime.now(timezone.utc).isoformat(),
            'from_cache':            False,
            'refresh_triggered':     True,
            'version':               '1.0.0',
        }

        # Write cache + history + fingerprint
        _redis_set(RHETORIC_CACHE_KEY, result)
        _redis_lpush_trim(HISTORY_KEY, {
            'theatre_level':    theatre_level,
            'us_pressure':      vectors.get('us_pressure', 0),
            'regime_fracture':  vectors.get('regime_fracture', 0),
            'adversary_access': vectors.get('adversary_access', 0),
            'scanned_at':       result['scanned_at'],
            'red_lines_count':  len(red_lines_triggered),
        })
        _write_crosstheater_fingerprint(actor_results, vectors)

        print(f"[Cuba Rhetoric] Scan complete: theatre=L{theatre_level}, "
              f"us_pressure=L{vectors.get('us_pressure', 0)}, "
              f"fracture=L{vectors.get('regime_fracture', 0)}, "
              f"adversary=L{vectors.get('adversary_access', 0)} "
              f"({scan_time}s, {len(articles)} articles, {len(red_lines_triggered)} red lines)")

        return result

    except Exception as e:
        print(f"[Cuba Rhetoric] Scan error: {str(e)[:200]}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)[:200]}
    finally:
        _rhetoric_running = False


def _compute_source_counts(articles):
    """Count articles per source type for Gold Standard pill strip."""
    counts = {
        'gdelt':    0,
        'rss':      0,
        'bluesky':  0,
        'telegram': 0,
        'reddit':   0,
    }
    for art in articles:
        ft = (art.get('feed_type') or '').lower()
        if ft in counts:
            counts[ft] += 1
        else:
            counts['rss'] += 1  # unknown = default to RSS bucket
    return counts


def get_cuba_rhetoric_cache():
    """Convenience: return cached scan result or None."""
    return _redis_get(RHETORIC_CACHE_KEY)


# ============================================
# BACKGROUND REFRESH
# ============================================
def _background_refresh():
    """Background thread: refresh every SCAN_INTERVAL_HOURS hours."""
    time.sleep(90)  # Boot delay (let Render warm up)
    while True:
        try:
            print("[Cuba Rhetoric] Background refresh starting...")
            run_cuba_rhetoric_scan(force=True)
        except Exception as e:
            print(f"[Cuba Rhetoric] Background refresh error: {str(e)[:80]}")
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


def start_background_refresh():
    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()
    print("[Cuba Rhetoric] Background refresh thread started")


# ============================================
# FLASK ENDPOINTS
# ============================================
def register_cuba_rhetoric_endpoints(app):
    """Register /api/rhetoric/cuba endpoints on the Flask app."""

    @app.route('/api/rhetoric/cuba', methods=['GET'])
    def cuba_rhetoric():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        if not force:
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                return jsonify(cached)

        # Non-blocking scan with 25s timeout -- return cached if scan takes longer
        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(run_cuba_rhetoric_scan, True)
        executor.shutdown(wait=False)

        try:
            result = future.result(timeout=25)
            return jsonify(result)
        except Exception:
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                cached['scan_triggered'] = True
                return jsonify(cached)
            return jsonify({'success': False, 'error': 'Scan timeout, no cache available'}), 503

    @app.route('/api/rhetoric/cuba/summary', methods=['GET'])
    def cuba_rhetoric_summary():
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if not cached:
            return jsonify({'success': False, 'error': 'No data yet -- trigger a scan first'}), 404

        actors = cached.get('actors', {})
        return jsonify({
            'success':                True,
            'theatre_level':          cached.get('theatre_level', 0),
            'us_pressure':            cached.get('us_pressure', 0),
            'regime_fracture':        cached.get('regime_fracture', 0),
            'adversary_access':       cached.get('adversary_access', 0),
            'us_government_level':    actors.get('us_government',        {}).get('escalation_level', 0),
            'us_sanctions_level':     actors.get('us_sanctions_regulatory',{}).get('escalation_level', 0),
            'us_military_level':      actors.get('us_military_posture',  {}).get('escalation_level', 0),
            'cuban_government_level': actors.get('cuban_government',     {}).get('escalation_level', 0),
            'cuban_military_level':   actors.get('cuban_military_security',{}).get('escalation_level', 0),
            'cuban_dissidents_level': actors.get('cuban_dissidents',     {}).get('escalation_level', 0),
            'russia_cuba_level':      actors.get('russia_cuba_axis',     {}).get('escalation_level', 0),
            'china_cuba_level':       actors.get('china_cuba_axis',      {}).get('escalation_level', 0),
            'iran_cuba_level':        actors.get('iran_cuba_axis',       {}).get('escalation_level', 0),
            'red_lines_count':        len(cached.get('red_lines', [])),
            'scenario':               (cached.get('so_what') or {}).get('scenario', ''),
            'scanned_at':             cached.get('scanned_at', ''),
            'from_cache':             True,
        })

    @app.route('/api/rhetoric/cuba/history', methods=['GET'])
    def cuba_rhetoric_history():
        history = _redis_get(HISTORY_KEY) or []
        return jsonify({'success': True, 'history': history, 'count': len(history)})

    print("[Cuba Rhetoric] Endpoints registered: /api/rhetoric/cuba, /summary, /history")
