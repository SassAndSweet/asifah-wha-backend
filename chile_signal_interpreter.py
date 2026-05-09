"""
chile_signal_interpreter.py
=========================================================
Chile Rhetoric Signal Interpreter v1.0.0 — Asifah Analytics
Built: May 9, 2026

Generates analytical prose for the Chile rhetoric tracker:
  • build_top_signals()       — canonical short_text/long_text top signals
  • build_executive_summary() — 2-4 sentence headline narrative
  • build_so_what_factor()    — bulleted strategic implications

Reads from scan results produced by rhetoric_tracker_chile.scan_chile_rhetoric()
and emits prose calibrated to Chile's 4-vector framework:
  Domestic Stability / Resource-Sector / US Alignment / China Alignment

Architecture notes:
  • Same canonical signal schema as Peru / Japan / Cuba / Greenland trackers:
      {short_text, long_text, level, type, actor, sources}
  • Convergence detection: when ≥2 vectors hit elevated+, surfaces as
    a top signal of type='convergence'
  • Commodity coupling: when commodity_pressure is present (copper / lithium
    supply risk), surfaces as a top signal of type='commodity_coupling'
  • De-escalation detection: dialogue tables, mesa de diálogo Mapuche,
    pact-of-governability rhetoric, cabinet-renewal language
  • USAID is referenced ONLY as historical context (defunct 2025); no
    current-implications language
  • Hezbollah/extremist tripwire prose included but expected dormant
    for Chile (TBA is geographically distant)

CHILE-SPECIFIC FRAMING (vs. Peru):
  • Constitutional-politics actor replaces FFAA + VRAEM as structural-stability
    lever — prose centers on impeachment cycles, pension/fiscal reform fate,
    and the post-2022/2023 plebiscite aftermath
  • Mapuche conflict prose uses autonomy-claim politics (CAM, Wallmapu),
    NOT narco-insurgency framing
  • China-Chile prose acknowledges *cautious* posture — no Chancay-equivalent
    flagship; lithium-side coupling is structural rather than episodic
  • Mining sector prose covers Codelco-monopoly + private + lithium duopoly

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import re
from datetime import datetime, timezone

# ============================================
# CONFIGURATION
# ============================================
LEVEL_ORDER = ['low', 'normal', 'elevated', 'high', 'surge']
ESCALATORY_LEVELS = {'elevated', 'high', 'surge'}

# Vector display names for prose
VECTOR_NAMES = {
    'domestic_stability': 'domestic stability pressure',
    'resource_sector':    'resource-sector politics',
    'us_alignment':       'US alignment vector',
    'china_alignment':    'China alignment vector',
}

# Actor display names for prose (cleaner than the formal `name` field)
ACTOR_PROSE_NAMES = {
    'presidency':              'the Presidency',
    'cancilleria':             'Cancillería',
    'mining_sector':           'the mining sector',
    'mapuche_conflict':        'the Mapuche conflict zone',
    'constitutional_politics': 'constitutional politics',
    'us_chile':                'US-Chile bilateral channels',
    'china_chile':             'China-Chile bilateral channels',
}

# De-escalation patterns — softens elevated readings when actor articles
# contain dialogue / accord / treaty / cabinet-renewal language
DEESCALATION_PATTERNS = [
    'mesa de diálogo', 'mesa de dialogo', 'dialogue table',
    'consulta indígena', 'indigenous consultation',
    'pacto de gobernabilidad', 'governability pact',
    'acuerdo nacional', 'national accord',
    'tregua', 'truce', 'cese de hostilidades',
    'comisión de paz', 'peace commission',
    'reanuda operaciones', 'resumes operations',
    'levanta bloqueo', 'lifts blockade',
    'reform unanimous', 'reforma unánime',
]


# ============================================
# HELPERS
# ============================================
def _level_rank(level):
    """Numeric rank for level comparison."""
    try:
        return LEVEL_ORDER.index(level)
    except ValueError:
        return 0


def _max_level(levels):
    """Return the highest level from a list."""
    if not levels:
        return 'low'
    return max(levels, key=_level_rank)


def _has_deescalation(actor_summary):
    """Check if an actor's articles contain de-escalation patterns."""
    text = ''
    for art in actor_summary.get('top_articles', []):
        text += ' ' + (art.get('title') or '').lower()
    return any(p in text for p in DEESCALATION_PATTERNS)


def _top_article_for_actor(actor_summary):
    """Get the single highest-scoring article for an actor (or None)."""
    arts = actor_summary.get('top_articles', [])
    return arts[0] if arts else None


# ============================================
# TOP SIGNALS BUILDER
# ============================================
def build_top_signals(actor_summaries, tripwires_global, commodity_pressure, crosstheater_amplifiers):
    """
    Build the canonical top_signals[] array for the Chile rhetoric tracker.

    Each signal has the canonical schema:
      {
        'short_text':  one-line headline (≤120 chars)
        'long_text':   2-4 sentence elaboration
        'level':       one of low/normal/elevated/high/surge
        'type':        actor_signal | tripwire | convergence | commodity_coupling | crosstheater
        'actor':       actor_id (or None)
        'sources':     list of {title, url, source} (top 3)
      }

    Sorted by level (surge first), then by signal-richness.
    """
    signals = []

    # ── 1. Tripwire signals (highest priority) ──
    seen_tripwires = set()
    for tw in tripwires_global or []:
        tw_id = tw.get('id')
        if tw_id in seen_tripwires:
            continue
        seen_tripwires.add(tw_id)
        actor_id = tw.get('actor')
        actor_data = actor_summaries.get(actor_id, {}) if actor_id else {}
        top_art = _top_article_for_actor(actor_data) if actor_data else None
        sources = []
        if top_art:
            sources.append({
                'title':  top_art.get('title', ''),
                'url':    top_art.get('url', ''),
                'source': top_art.get('source', ''),
            })

        short, long_text = _tripwire_prose(tw_id, actor_id)
        signals.append({
            'short_text': short,
            'long_text':  long_text,
            'level':      tw.get('severity', 'high'),
            'type':       'tripwire',
            'actor':      actor_id,
            'sources':    sources,
        })

    # ── 2. Convergence signals ──
    # When ≥2 vectors are at elevated+, signal a convergence
    vector_levels = {}
    for actor_id, actor in actor_summaries.items():
        vec = actor.get('vector')
        lvl = actor.get('level', 'low')
        if vec:
            existing = vector_levels.get(vec, 'low')
            if _level_rank(lvl) > _level_rank(existing):
                vector_levels[vec] = lvl
    elevated_vectors = [v for v, lv in vector_levels.items() if lv in ESCALATORY_LEVELS]
    if len(elevated_vectors) >= 2:
        sig = _convergence_signal(elevated_vectors, vector_levels, actor_summaries)
        if sig:
            signals.append(sig)

    # ── 3. Per-actor signals (only at elevated+) ──
    for actor_id, actor in actor_summaries.items():
        level = actor.get('level', 'low')
        if level not in ESCALATORY_LEVELS:
            continue
        # Skip if a tripwire already covered this actor at the same/higher severity
        actor_tw_levels = [
            tw.get('severity') for tw in tripwires_global or []
            if tw.get('actor') == actor_id
        ]
        if actor_tw_levels and _level_rank(_max_level(actor_tw_levels)) >= _level_rank(level):
            continue

        sig = _actor_signal(actor_id, actor)
        if sig:
            signals.append(sig)

    # ── 4. Commodity coupling signals ──
    for commodity_id, risk in (commodity_pressure or {}).items():
        if risk.get('alert_level') in ESCALATORY_LEVELS:
            sig = _commodity_coupling_signal(commodity_id, risk, actor_summaries)
            if sig:
                signals.append(sig)

    # ── 5. Cross-theater amplifier signals ──
    for amp_label, amp_data in (crosstheater_amplifiers or {}).items():
        if not isinstance(amp_data, dict):
            continue
        if not amp_data.get('active'):
            continue
        sig = _crosstheater_signal(amp_label, amp_data)
        if sig:
            signals.append(sig)

    # Sort: surge → high → elevated → normal → low; within same level, signals with sources first
    signals.sort(
        key=lambda s: (-_level_rank(s['level']), -len(s.get('sources', [])))
    )
    return signals[:12]   # cap at 12 — UI shows ~8 by default


def _tripwire_prose(tw_id, actor_id):
    """Generate (short, long) prose for a tripwire."""
    map_ = {
        # ── Presidency tripwires ──
        'boric_resignation': (
            "🚨 Boric resignation signal detected",
            "Reporting indicates a resignation signal from President Boric — verify against "
            "multiple independent sources before treating as confirmed. If confirmed, this would "
            "trigger constitutional succession and almost certainly reset the 2026 election timeline."
        ),
        'cabinet_collapse': (
            "🏛️ Cabinet mass-resignation event",
            "Multiple cabinet ministers have resigned in close succession — a cabinet-collapse "
            "signal. Watch for replacement nominations, Congressional confirmation timing, and "
            "any signals that the resignation tranche is bigger than the named names."
        ),
        'approval_cliff': (
            "📉 Presidential approval cliff event",
            "Boric's approval has crashed to historically low levels (sub-20). Cliff events "
            "correlate with reduced reform passage probability and elevated Congressional opposition "
            "leverage. Watch CADEM and Plaza Pública weekly tracking."
        ),

        # ── Cancillería tripwires ──
        'boundary_crisis': (
            "🌐 Border / boundary crisis signal",
            "A diplomatic crisis with a Chilean neighbor (Bolivia, Peru, Argentina) is signaling. "
            "Chile's southern cone borders are normally low-volatility but recurring; watch OAS "
            "responses, ICJ filings, and Cancillería formal statements."
        ),
        'icj_filing': (
            "⚖️ ICJ / The Hague filing signal",
            "A new International Court of Justice filing involving Chile is signaling. Historically "
            "Chile-Bolivia (maritime access) and Chile-Peru (maritime delimitation) cases have driven "
            "regional posture; watch for binding-vs-advisory implications."
        ),

        # ── Mining sector tripwires ──
        'escondida_strike': (
            "🔥 Escondida operational strike — global copper supply risk",
            "Escondida (BHP, world's largest copper mine) is reporting a strike. Escondida "
            "alone represents ~5% of global copper supply; sustained strike pressures LME copper "
            "pricing. Watch for SUTMIC negotiations, BHP earnings impact, and replacement-worker "
            "deployment statements."
        ),
        'codelco_strike': (
            "🔥 Codelco operational strike — state copper supply risk",
            "Codelco (Chilean state copper enterprise — ~10% of global copper supply across all "
            "divisions) is reporting a strike. Watch division-level scope (Chuquicamata, El Teniente, "
            "Andina), Ministry of Mining mediation, and Cochilco supply-impact statements."
        ),
        'chuquicamata_disruption': (
            "⛏️ Chuquicamata disruption signal",
            "Chuquicamata (Codelco's flagship division) is reporting operational disruption. "
            "Underground transition + community-EIA dynamics make Chuquicamata politically sensitive; "
            "watch Cochilco production guidance and Codelco labor relations."
        ),
        'lithium_nationalization': (
            "⚡ Lithium nationalization signal — global supply chain implications",
            "Reporting indicates active movement on Chile's national lithium strategy "
            "nationalization framework. Chile is the world's #2 lithium producer; movement here "
            "directly affects EV supply chains, Tianqi-SQM's 24% stake fate, and Albemarle's "
            "Salar de Atacama operations. Watch CORFO contract dynamics."
        ),
        'mining_fatality': (
            "⚠️ Mining fatality reported in Chile",
            "A mining fatality has been reported. Chilean mining safety standards are strong but "
            "fatalities trigger ENAMI / SERNAGEOMIN investigations and union demands; watch for "
            "operational suspension orders and labor responses."
        ),

        # ── Mapuche conflict tripwires ──
        'state_of_exception': (
            "🚨 State of exception declared in Araucanía / macrozona sur",
            "A state of exception has been declared in Chile's macrozona sur (Araucanía / Biobío). "
            "Recurring since late 2021; expansion or re-extension signals govt assessment that "
            "civil-public-order tools are insufficient. Watch INDH (human rights institute) "
            "statements and IACHR responses."
        ),
        'mass_arson': (
            "🔥 Coordinated arson event in Mapuche conflict zone",
            "Coordinated arson incidents in the macrozona sur signaling. Forestry-truck-burning "
            "campaigns are CAM (Coordinadora Arauco-Malleco) signature. Watch carabineros / PDI "
            "deployment posture and any escalation toward security forces."
        ),
        'mapuche_fatality': (
            "⚠️ Fatality in Mapuche conflict zone",
            "A fatality has been reported in the Araucanía / Biobío conflict zone — could be a "
            "comunero, carabinero, civilian, or security forces. Verify identity and circumstances; "
            "fatalities historically trigger memorial mobilizations and IACHR observations."
        ),
        'cam_attack': (
            "💥 CAM (Coordinadora Arauco-Malleco) attack signal",
            "An attack attributed to CAM or aligned formations is signaling. CAM advocates "
            "armed Mapuche autonomy and is the most consistent armed actor in the conflict. "
            "Watch for SOE renewal pressure and any expanded Ley Antiterrorista invocation."
        ),

        # ── Constitutional politics tripwires ──
        'impeachment_vote': (
            "🏛️ Constitutional accusation (impeachment) approved in Chile",
            "An acusación constitucional (impeachment vote) has been approved against a senior "
            "official. Chile's mechanism is narrower than US impeachment (specific charges, "
            "Senate trial), but a successful vote unseats the official and amplifies "
            "executive-legislative friction. Watch Senate trial calendar."
        ),
        'cabinet_minister_ousted': (
            "⚖️ Cabinet minister ousted via censura/destitución",
            "A Chilean cabinet minister has been formally censured or destituted. Less severe "
            "than impeachment but still high-friction; signals that opposition has effective "
            "Congressional leverage. Watch successor-nomination dynamics."
        ),
        'major_reform_collapse': (
            "📋 Major Boric reform collapses in Congress",
            "A flagship Boric reform (pension / fiscal pact / constitutional) has been formally "
            "rejected. Collapse events compress political-capital reserves and accelerate "
            "lame-duck dynamics ahead of 2026. Watch coalition-stability rhetoric."
        ),

        # ── US-Chile tripwires ──
        'strategic_minerals_pact': (
            "🤝 US-Chile strategic minerals agreement signal",
            "Reporting indicates active movement on a US-Chile critical-minerals dialog or "
            "agreement (lithium / copper / molybdenum focused). Embeds Chile firmly in "
            "post-IRA Western supply chains and may provoke Beijing pushback. Watch State "
            "Department / Embajada Santiago readouts."
        ),
        'ambassador_recall': (
            "🚨 US-Chile ambassadorial recall signal",
            "Reporting indicates a recall of either US or Chilean ambassador. Low-base-rate event "
            "implying bilateral friction. Verify against multiple independent sources; bilateral "
            "FTA + lithium / copper trade make a sustained recall costly for both sides."
        ),
        'joint_exercise_friction': (
            "🪖 US-Chile joint military exercise friction",
            "Reporting indicates cancellation, postponement, or political friction over a "
            "US-Chile joint exercise (UNITAS / Pacific Dragon). Chilean civilian-democratic "
            "preferences sometimes friction with US naval-cooperation calendars."
        ),

        # ── China-Chile tripwires ──
        'chinese_naval_visit': (
            "🚢 Chinese naval visit / port call in Chile",
            "Reporting indicates a People's Liberation Army Navy port call or naval-cooperation "
            "exercise on Chilean coastline. Chile has been more cautious than Peru on Chinese "
            "naval access; any visit warrants attention to US-Embassy response posture."
        ),
        'major_infra_milestone': (
            "🏗️ Major China-Chile infrastructure milestone",
            "Reporting indicates a milestone on a major China-funded infrastructure project in "
            "Chile (cable transpacific, port investment, Chinese space observatory). "
            "Watch Cancillería readouts and any pushback from US Embassy Santiago."
        ),
        'fta_renegotiation': (
            "📝 China-Chile FTA renegotiation signal",
            "Reporting indicates active movement on China-Chile FTA renegotiation or amendment. "
            "China is Chile's largest trading partner; FTA terms touch lithium / copper export "
            "logistics directly. Watch DIRECON statements."
        ),
    }
    return map_.get(tw_id, ("⚠️ Tripwire signal", "A tripwire event has been detected. See raw signals for context."))


def _convergence_signal(elevated_vectors, vector_levels, actor_summaries):
    """When 2+ vectors are at elevated+, build a convergence signal."""
    vec_names = [VECTOR_NAMES.get(v, v) for v in elevated_vectors]
    max_level = _max_level([vector_levels[v] for v in elevated_vectors])
    short = f"⚡ Convergence: {' + '.join(vec_names[:2])}{' + …' if len(vec_names) > 2 else ''} at {max_level}"
    long_parts = [f"Multiple analytical vectors are simultaneously elevated:"]
    for v in elevated_vectors:
        lvl = vector_levels[v]
        long_parts.append(f"• {VECTOR_NAMES.get(v, v).title()} at {lvl}")
    long_parts.append(
        "Convergence is more analytically significant than any individual vector — when "
        "domestic-stability pressure intersects with resource-sector or alignment vectors, "
        "Chile's risk profile compounds across normally-independent dimensions."
    )
    return {
        'short_text': short,
        'long_text':  '\n'.join(long_parts),
        'level':      max_level,
        'type':       'convergence',
        'actor':      None,
        'sources':    [],
    }


def _actor_signal(actor_id, actor):
    """Build a per-actor signal at elevated+."""
    name = ACTOR_PROSE_NAMES.get(actor_id, actor.get('name', actor_id))
    level = actor.get('level', 'normal')
    article_count = actor.get('article_count', 0)
    icon = actor.get('icon', '📊')

    deescalation = _has_deescalation(actor)

    # Build short_text
    if deescalation and level in ('elevated', 'high'):
        short = f"{icon} {name} — {level} but with de-escalatory rhetoric (dialogue / consultation)"
    elif level == 'surge':
        short = f"{icon} {name} — SURGE-level rhetoric ({article_count} signals)"
    elif level == 'high':
        short = f"{icon} {name} — high-level rhetoric tempo ({article_count} signals)"
    else:
        short = f"{icon} {name} — elevated rhetoric tempo ({article_count} signals)"

    long_text = _actor_specific_long_text(actor_id, actor, deescalation)

    sources = []
    for art in actor.get('top_articles', [])[:3]:
        sources.append({
            'title':  art.get('title', ''),
            'url':    art.get('url', ''),
            'source': art.get('source', ''),
        })

    return {
        'short_text': short,
        'long_text':  long_text,
        'level':      level,
        'type':       'actor_signal',
        'actor':      actor_id,
        'sources':    sources,
    }


def _actor_specific_long_text(actor_id, actor, deescalation):
    """Generate actor-specific framing prose."""
    level = actor.get('level', 'normal')
    articles = actor.get('article_count', 0)

    base_map = {
        'presidency': (
            f"Presidential rhetoric tempo at {level} ({articles} signals). "
            f"Chile's executive cycle is 4-year-single-term; Boric administration tempo correlates "
            f"with Congressional reform-fight calendars and 2026 generals positioning. CADEM and "
            f"Plaza Pública weekly tracking are leading indicators."
        ),
        'cancilleria': (
            f"Foreign-ministry rhetoric tempo at {level} ({articles} signals). "
            f"Cancillería signals typically track Pacific Alliance positioning (vs. Mercosur), "
            f"Chile-Bolivia / Chile-Peru maritime issues, OAS posture, and bilateral statements "
            f"with US / China. Elevated tempo often precedes a multilateral inflection."
        ),
        'mining_sector': (
            f"Mining-sector rhetoric tempo at {level} ({articles} signals). "
            f"Chile is the world's #1 copper producer (Codelco state + private — BHP, Anglo, "
            f"Antofagasta) and #2 lithium producer (SQM + Albemarle duopoly). Sector tempo "
            f"tracks labor-strike cycles, royalty disputes, lithium-nationalization politics, "
            f"and environmental/EIA rulings. Industry tempo typically leads price-impact by days."
        ),
        'mapuche_conflict': (
            f"Mapuche / macrozona sur conflict tempo at {level} ({articles} signals). "
            f"The Araucanía-Biobío conflict zone has been under recurrent state-of-exception "
            f"since late 2021. Signal tempo tracks CAM (Coordinadora Arauco-Malleco) operations, "
            f"forestry-truck-burning campaigns, and judicial responses (Ley Antiterrorista, "
            f"Ley de Seguridad del Estado). Watch for SOE-renewal cycles."
        ),
        'constitutional_politics': (
            f"Constitutional-politics rhetoric tempo at {level} ({articles} signals). "
            f"Chile's post-2022/2023 referendum aftermath leaves the country with the 1980 "
            f"constitution intact but a more polarized constitutional-reform discourse. Tempo "
            f"tracks Congressional opposition-leverage, pension reform / fiscal pact dynamics, "
            f"and impeachment / censure motions. Elevated tempo often signals reform-collapse "
            f"or coalition-stability inflection."
        ),
        'us_chile': (
            f"US-Chile bilateral rhetoric tempo at {level} ({articles} signals). "
            f"Channel includes Embassy Santiago, SOUTHCOM, the Pacific Council, US-Chile FTA, "
            f"and the strategic-minerals (lithium / copper) dialog. Post-IRA, lithium has become "
            f"the central US-Chile bilateral economic conversation. (Note: USAID was dissolved "
            f"in 2025; cooperation now via State INL and DoD.)"
        ),
        'china_chile': (
            f"China-Chile bilateral rhetoric tempo at {level} ({articles} signals). "
            f"Channel includes lithium investment (Tianqi's 24% SQM stake, BYD Salar de Maricunga, "
            f"Ganfeng-Codelco partnership), copper trade (China is Chile's largest copper buyer), "
            f"FTA review, and BRI ambivalence (Chile is more cautious than Peru). Elevated tempo "
            f"often precedes a state-visit announcement or contract milestone."
        ),
    }
    base = base_map.get(actor_id, f"{ACTOR_PROSE_NAMES.get(actor_id, actor_id)} rhetoric at {level}.")
    if deescalation:
        base += " Notably, current articles include de-escalatory language (dialogue / consultation / accord) — softens the elevated reading."
    return base


def _commodity_coupling_signal(commodity_id, risk, actor_summaries):
    """Build a commodity-coupling signal from a supply-risk fingerprint."""
    role = risk.get('role', 'producer')
    rank = risk.get('rank')
    rank_str = f" (#{rank} globally)" if rank else ""
    alert = risk.get('alert_level', 'normal')
    sig_count = risk.get('signal_count', 0)
    top_signal = risk.get('top_signal') or {}

    short = f"⛏️ Commodity coupling: {commodity_id} {role}{rank_str} — {alert} pressure from sector signals"

    # Chile-specific commodity narrative
    if commodity_id == 'copper':
        coupling_note = (
            "Chile is the world's #1 copper producer; what mining_sector rhetoric tracks "
            "directly couples to LME copper pricing through Codelco / BHP / Antofagasta supply."
        )
    elif commodity_id == 'lithium':
        coupling_note = (
            "Chile is the world's #2 lithium producer; what mining_sector rhetoric tracks "
            "couples directly to EV-battery supply chains through SQM / Albemarle Salar de Atacama "
            "operations and (depending on signal) the national lithium strategy."
        )
    else:
        coupling_note = (
            f"What mining_sector rhetoric tracks here has direct supply-side implications "
            f"for global {commodity_id} markets."
        )

    long_text = (
        f"The commodity tracker is reporting {alert}-level pressure on Chile's {commodity_id} "
        f"sector (Chile is a {role}{rank_str}). {sig_count} cross-tracker signals flagged. "
        f"This is a coupling event — {coupling_note} Watch for sector-rhetoric and price-impact alignment."
    )
    sources = []
    if top_signal.get('title'):
        sources.append({
            'title':  top_signal.get('title', ''),
            'url':    top_signal.get('url', ''),
            'source': top_signal.get('source', ''),
        })

    return {
        'short_text': short,
        'long_text':  long_text,
        'level':      alert,
        'type':       'commodity_coupling',
        'actor':      'mining_sector',
        'sources':    sources,
    }


def _crosstheater_signal(amp_label, amp_data):
    """Build a cross-theater amplifier signal."""
    label_map = {
        'china_lac_active':   ('China-LAC posture active', 'China rhetoric tracker is reporting elevated Latin America-focused activity. Chile is China\'s largest South American trading partner; amplifies any Chile-side China-alignment vector signals.'),
        'china_bri_latam':    ('China BRI-LatAm posture active', 'BRI-LatAm-specific posture is active per the China rhetoric tracker. Chile is more cautious than Peru on BRI but lithium / copper investment channels still amplify.'),
        'iran_latam_active':  ('Iran LatAm posture active', 'Iran rhetoric tracker is reporting elevated Latin America activity. Chile is not a primary Iranian theater, but amplification triggers extra vigilance on the extremist-network tripwire.'),
        'iran_hezbollah_tba': ('Hezbollah Tri-Border Area active', 'Iran tracker is reporting Hezbollah TBA-network activity. Chile is geographically distant from the TBA but supply-chain / financing routes can reach Santiago; quiet tripwire stays armed.'),
    }
    short_root, long_text = label_map.get(amp_label, (amp_label, 'External tracker amplification active.'))
    short = f"🌐 Cross-theater: {short_root}"
    return {
        'short_text': short,
        'long_text':  long_text,
        'level':      amp_data.get('level', 'elevated'),
        'type':       'crosstheater',
        'actor':      None,
        'sources':    [],
    }


# ============================================
# EXECUTIVE SUMMARY BUILDER
# ============================================
def build_executive_summary(actor_summaries, vector_scores, vector_levels, tripwires_global):
    """
    Generate a 2-4 sentence executive summary capturing the headline narrative.
    Calibrated to the 4-vector frame.
    """
    parts = []

    # Identify top vector + level
    sorted_vectors = sorted(
        vector_scores.items(),
        key=lambda x: (-_level_rank(vector_levels.get(x[0], 'low')), -x[1])
    )
    top_vector_id, top_vector_score = sorted_vectors[0] if sorted_vectors else (None, 0)
    top_vector_level = vector_levels.get(top_vector_id, 'low') if top_vector_id else 'low'

    elevated_vectors = [v for v, lv in vector_levels.items() if lv in ESCALATORY_LEVELS]

    # Sentence 1 — top vector framing
    if top_vector_level == 'low':
        parts.append(
            "Chile's rhetoric environment is at baseline across all four analytical vectors "
            "(domestic stability, resource-sector politics, US alignment, China alignment). "
            "No structural pressure events detected this scan."
        )
    elif top_vector_level == 'normal':
        parts.append(
            f"Chile's rhetoric environment is normal-tempo, with {VECTOR_NAMES.get(top_vector_id, top_vector_id)} "
            f"showing the most signal volume but no escalatory pattern."
        )
    else:
        parts.append(
            f"Chile's rhetoric environment is elevated, led by {VECTOR_NAMES.get(top_vector_id, top_vector_id)} "
            f"at {top_vector_level} ({round(top_vector_score, 1)} weighted score)."
        )

    # Sentence 2 — convergence note
    if len(elevated_vectors) >= 2:
        vec_names = [VECTOR_NAMES.get(v, v) for v in elevated_vectors]
        parts.append(
            f"Cross-vector convergence is underway: {' + '.join(vec_names[:3])} "
            f"are simultaneously above baseline, compounding Chile's risk profile."
        )

    # Sentence 3 — tripwire mention
    if tripwires_global:
        unique_tw = list({tw.get('id') for tw in tripwires_global})
        tw_count = len(unique_tw)
        if tw_count == 1:
            parts.append(
                f"One tripwire event detected this scan: {unique_tw[0].replace('_', ' ')}. "
                f"See top signals for context."
            )
        else:
            parts.append(
                f"{tw_count} tripwire events detected this scan: {', '.join(t.replace('_', ' ') for t in unique_tw[:3])}. "
                f"See top signals for context."
            )

    # Sentence 4 — top-actor breadcrumb
    sorted_actors = sorted(
        actor_summaries.items(),
        key=lambda x: (-_level_rank(x[1].get('level', 'low')), -x[1].get('score', 0))
    )
    top_actor_id, top_actor = sorted_actors[0] if sorted_actors else (None, None)
    if top_actor and top_actor.get('level') in ESCALATORY_LEVELS:
        parts.append(
            f"Highest-tempo actor this scan: {ACTOR_PROSE_NAMES.get(top_actor_id, top_actor_id)} "
            f"at {top_actor.get('level')} ({top_actor.get('article_count', 0)} signals)."
        )

    return ' '.join(parts)


# ============================================
# SO WHAT FACTOR BUILDER
# ============================================
def build_so_what_factor(actor_summaries, vector_scores, vector_levels, tripwires_global, commodity_pressure):
    """
    Build the bulleted 'So What' factor — strategic implications calibrated to
    Chile's 4-vector frame. Returns a list of dicts:
      {bullet: str, weight: float}

    The bullets are intended for the rhetoric-chile.html So What card.
    Weight is used to sort (highest first); ~3-7 bullets returned typically.
    """
    bullets = []

    # ── Vector-driven implications ──
    if vector_levels.get('domestic_stability') in ('high', 'surge'):
        bullets.append({
            'bullet': "Domestic-stability vector is at " + vector_levels['domestic_stability'] +
                      " — Chile's institutional cohesion is under stress. Watch for impeachment cycles, " +
                      "cabinet reshuffles, Mapuche-zone SOE renewals, and 2026 election positioning.",
            'weight': 5.0,
        })
    elif vector_levels.get('domestic_stability') == 'elevated':
        bullets.append({
            'bullet': "Domestic-stability vector is elevated — political tempo is rising. " +
                      "Track Boric approval (CADEM, Plaza Pública), opposition Congressional moves, " +
                      "and macrozona sur dynamics for inflection signals.",
            'weight': 3.5,
        })

    if vector_levels.get('resource_sector') in ('high', 'surge'):
        bullets.append({
            'bullet': "Resource-sector vector at " + vector_levels['resource_sector'] +
                      " — mining-sector rhetoric is at elevated supply-disruption tempo. " +
                      "Direct global commodity-pricing implications for copper (Codelco / BHP / Antofagasta) " +
                      "and lithium (SQM / Albemarle).",
            'weight': 4.8,
        })
    elif vector_levels.get('resource_sector') == 'elevated':
        bullets.append({
            'bullet': "Resource-sector vector is elevated — mining-labor and lithium-policy signals " +
                      "above baseline. Watch SUTMIC negotiations, CORFO contract dynamics, and " +
                      "any movement on the national lithium strategy.",
            'weight': 3.2,
        })

    if vector_levels.get('china_alignment') in ('high', 'surge'):
        bullets.append({
            'bullet': "China-alignment vector at " + vector_levels['china_alignment'] +
                      " — Tianqi-SQM, BYD-Maricunga, Ganfeng-Codelco, and FTA channels signaling. " +
                      "Strategic mineral offtake and infrastructure-project milestones converge here.",
            'weight': 4.2,
        })

    if vector_levels.get('us_alignment') in ('high', 'surge'):
        bullets.append({
            'bullet': "US-alignment vector at " + vector_levels['us_alignment'] +
                      " — Embassy Santiago, SOUTHCOM, FTA, and strategic-minerals dialog channels " +
                      "above baseline. Often correlates with critical-minerals milestones or " +
                      "naval-cooperation events.",
            'weight': 4.0,
        })

    # ── Tripwire-specific implications ──
    tripwire_ids = list({tw.get('id') for tw in tripwires_global or []})

    if 'escondida_strike' in tripwire_ids:
        bullets.append({
            'bullet': "Escondida strike tripwire is HOT — global copper supply impact is direct. " +
                      "Watch LME copper futures, BHP (NYSE:BHP / ASX:BHP) earnings revisions, and " +
                      "Chinese-smelter concentrate-import statements in next 7-14 days. Escondida " +
                      "alone is ~5% of global supply.",
            'weight': 5.5,
        })

    if 'codelco_strike' in tripwire_ids:
        bullets.append({
            'bullet': "Codelco strike tripwire is HOT — Chilean state-copper supply impact direct. " +
                      "Watch Cochilco production guidance, Ministry of Mining mediation tempo, and " +
                      "any spillover to El Teniente / Andina divisions.",
            'weight': 5.4,
        })

    if 'lithium_nationalization' in tripwire_ids:
        bullets.append({
            'bullet': "Lithium nationalization tripwire is HOT — global EV battery supply chain " +
                      "implications. Watch Tianqi (HKEX:9696) reaction on its 24% SQM stake, " +
                      "Albemarle (NYSE:ALB) Salar de Atacama operational guidance, and CORFO " +
                      "contract-renegotiation tempo.",
            'weight': 5.3,
        })

    if 'state_of_exception' in tripwire_ids:
        bullets.append({
            'bullet': "State of exception declared in macrozona sur — executive authority expanded " +
                      "over civilian movement and police-military deployment in Araucanía / Biobío. " +
                      "Track geographic scope, renewal cadence, and INDH / IACHR posture.",
            'weight': 4.8,
        })

    if 'impeachment_vote' in tripwire_ids:
        bullets.append({
            'bullet': "Constitutional accusation (impeachment) vote in motion or approved — Chile's " +
                      "narrower-than-US mechanism is real. Watch Senate trial calendar, vote tally, " +
                      "and any cascade to other officials in the same coalition.",
            'weight': 5.2,
        })

    if 'cabinet_minister_ousted' in tripwire_ids:
        bullets.append({
            'bullet': "Cabinet minister formally censured / destituted — opposition Congressional " +
                      "leverage just demonstrated. Watch successor-nomination dynamics and " +
                      "coalition-stability rhetoric.",
            'weight': 4.5,
        })

    if 'mass_arson' in tripwire_ids or 'cam_attack' in tripwire_ids:
        bullets.append({
            'bullet': "Mapuche-conflict-zone violent-incident tripwire is HOT — CAM activity or " +
                      "coordinated arson signaling. Watch carabineros / PDI deployment posture, " +
                      "Ley Antiterrorista invocation, and any escalation toward security forces.",
            'weight': 4.8,
        })

    if 'strategic_minerals_pact' in tripwire_ids:
        bullets.append({
            'bullet': "US-Chile strategic-minerals agreement signal — embeds Chile firmly in " +
                      "post-IRA Western supply chains for lithium / copper / molybdenum. Watch " +
                      "for Beijing pushback signals and any Chilean industry posture statements.",
            'weight': 4.7,
        })

    # ── Commodity coupling implications ──
    for commodity_id, risk in (commodity_pressure or {}).items():
        if risk.get('alert_level') in ('high', 'surge'):
            bullets.append({
                'bullet': f"Commodity-coupling: {commodity_id} supply pressure on Chile is at " +
                          f"{risk.get('alert_level')}. Chile's mining-sector rhetoric is now " +
                          f"coupled to global {commodity_id} pricing — sector signal volume will " +
                          f"lead price-impact by days.",
                'weight': 4.5,
            })

    # ── Default baseline implications when nothing escalatory ──
    if not bullets:
        bullets.append({
            'bullet': "All four analytical vectors are at baseline. Chile's rhetoric environment " +
                      "shows no structural pressure events this scan; baseline tempo is healthy " +
                      "for an active reform-cycle country approaching 2026 generals.",
            'weight': 1.0,
        })
        bullets.append({
            'bullet': "Watch indicators for next phase: macrozona sur SOE renewal cadence, " +
                      "Boric reform-package Congressional progression, Codelco / Escondida " +
                      "labor-relations statements, lithium-strategy CORFO milestones.",
            'weight': 0.8,
        })

    # Sort by weight descending, return top 7
    bullets.sort(key=lambda b: -b['weight'])
    return bullets[:7]


# ============================================
# Convenience entry point for callers
# that want a single canonical interpretation pass.
# ============================================
def interpret_chile_signals(scan_data):
    """
    Convenience wrapper — accepts a complete scan_data dict and returns the
    three derived analytical fields. Mirrors the Peru tracker's contract.
    """
    actor_summaries        = scan_data.get('actor_summaries', {}) or {}
    vector_scores          = scan_data.get('vector_scores', {}) or {}
    vector_levels          = scan_data.get('vector_levels', {}) or {}
    tripwires_global       = scan_data.get('tripwires_global', []) or []
    commodity_pressure     = scan_data.get('commodity_pressure', {}) or {}
    crosstheater_amplifiers = scan_data.get('crosstheater_amplifiers', {}) or {}

    return {
        'top_signals':       build_top_signals(actor_summaries, tripwires_global,
                                                commodity_pressure, crosstheater_amplifiers),
        'executive_summary': build_executive_summary(actor_summaries, vector_scores,
                                                     vector_levels, tripwires_global),
        'so_what':           build_so_what_factor(actor_summaries, vector_scores, vector_levels,
                                                   tripwires_global, commodity_pressure),
    }


print("[Chile Signal Interpreter] Module loaded — v1.0.0")
