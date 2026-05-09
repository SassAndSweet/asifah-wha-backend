"""
peru_signal_interpreter.py
=========================================================
Peru Rhetoric Signal Interpreter v1.0.0 — Asifah Analytics
Built: May 9, 2026

Generates analytical prose for the Peru rhetoric tracker:
  • build_top_signals()       — canonical short_text/long_text top signals
  • build_executive_summary() — 2-4 sentence headline narrative
  • build_so_what_factor()    — bulleted strategic implications

Reads from scan results produced by rhetoric_tracker_peru.scan_peru_rhetoric()
and emits prose calibrated to Peru's 4-vector framework:
  Domestic Stability / Resource-Sector / US Alignment / China Alignment

Architecture notes:
  • Same canonical signal schema as Japan/Cuba/Greenland trackers:
      {short_text, long_text, level, type, actor, sources}
  • Convergence detection: when ≥2 vectors hit elevated+, surfaces as
    a top signal of type='convergence'
  • Commodity coupling: when commodity_pressure is present (copper/silver
    supply risk), surfaces as a top signal of type='commodity_coupling'
  • Diplomatic / off-ramp logic: detects de-escalatory rhetoric (consulta
    previa dialogue, Las Bambas mesa de diálogo) and applies softening
  • USAID is referenced ONLY as historical context (defunct 2025); no
    current-implications language

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
    'presidency':     'the Presidency',
    'cancilleria':    'Cancillería',
    'ffaa':           'the Armed Forces',
    'mining_sector':  'the mining sector',
    'las_bambas':     'Las Bambas',
    'vraem_sendero':  'VRAEM / Sendero',
    'us_peru':        'US-Peru bilateral channels',
    'china_peru':     'China-Peru / BRI channels',
}

# Off-ramp / de-escalation patterns (lowered urgency when present)
DEESCALATION_PATTERNS = [
    'mesa de diálogo', 'mesa de dialogo', 'dialogue table',
    'consulta previa', 'prior consultation',
    'agreement reached', 'acuerdo alcanzado',
    'tregua', 'truce', 'cese de hostilidades',
    'reanuda operaciones', 'resumes operations',
    'lifts blockade', 'levanta el bloqueo',
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


def _format_source_pill(source_name, feed_type=''):
    """Return a tagged source string for citation."""
    feed_type = (feed_type or '').lower()
    if feed_type:
        return f"{source_name} ({feed_type})"
    return source_name


# ============================================
# TOP SIGNALS BUILDER
# ============================================
def build_top_signals(actor_summaries, tripwires_global, commodity_pressure, crosstheater_amplifiers):
    """
    Build the canonical top_signals[] array for the Peru rhetoric tracker.

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
        'state_of_emergency': (
            "🚨 Peru state of emergency declared",
            "A state of emergency has been declared in Peru — a domestic-stability rupture event. "
            "Historically these declarations expand executive authority over civilian movement and "
            "police-military deployment. Watch for renewal cycles and geographic expansion (e.g., "
            "Apurímac corridor, Lima metropolitan area, VRAEM region)."
        ),
        'las_bambas_full_closure': (
            "🔥 Las Bambas operational closure — global copper supply risk",
            "Las Bambas mine has entered indefinite operational closure. Las Bambas alone "
            "represents ~2% of global copper supply; sustained closure pressures LME copper "
            "pricing and reroutes Chinese smelter inputs. Watch for community-MMG dialogue "
            "frequency, transport-corridor blockade duration, and government mediation posture."
        ),
        'chancay_disruption': (
            "🚢 Chancay megaport disruption signal",
            "The Chancay megaport (COSCO 60% stake, opened Nov 2024) is reporting disruption. "
            "Chancay is the central physical infrastructure of China's Belt and Road footprint "
            "in South America; any closure or strike redirects significant Pacific trade flow. "
            "Watch for COSCO operational statements and Peruvian-government posture."
        ),
        'presidential_vacancy': (
            "🏛️ Presidential vacancy / impeachment vote in motion",
            "An impeachment or vacancy motion has been advanced against the sitting executive. "
            "Peru has experienced six presidents since 2018; a successful vote would trigger "
            "constitutional succession and likely accelerate the 2026 election timeline. Watch "
            "Congressional vote tallies and FFAA institutional posture."
        ),
        'ffaa_intervention': (
            "🪖 Military intervention / institutional rupture signal",
            "Reporting indicates Armed Forces involvement in executive-political affairs beyond "
            "constitutional norms. This is a low-base-rate, high-impact signal; verify against "
            "multiple independent sources before treating as confirmed. Watch Comando Conjunto "
            "FFAA statements and OAS / inter-American responses."
        ),
        'mass_casualty_protest': (
            "⚠️ Mass-casualty protest event reported",
            "Reporting indicates protest fatalities — a domestic-stability rupture event. "
            "Peru has prior precedent (Dec 2022–Jan 2023 southern Peru deaths). Watch human-rights "
            "responses, IACHR statements, and government de-escalation posture."
        ),
        'sendero_attack': (
            "💥 Sendero / narco-insurgent attack reported",
            "An attack attributed to Sendero Luminoso remnants or narco-aligned actors has been "
            "reported, likely in the VRAEM corridor. While Sendero is a residual threat (not "
            "the 1990s organization), VRAEM operations remain a measurable security perimeter. "
            "Watch FFAA and DEVIDA response posture."
        ),
        'extremist_network_signal': (
            "🛑 External extremist-network signal detected in Peru",
            "Reporting suggests Hezbollah / Iran-proxy / Tri-Border Area network activity with "
            "a Peru nexus. South America has seen TBA financing networks (Argentina-Brazil-Paraguay) "
            "but Peru is not a primary stomping ground; treat as out-of-pattern. Verify against "
            "multiple independent sources."
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
        "Peru's risk profile compounds across normally-independent dimensions."
    )
    long_text = ' '.join(long_parts) if False else '\n'.join(long_parts)
    return {
        'short_text': short,
        'long_text':  long_text,
        'level':      max_level,
        'type':       'convergence',
        'actor':      None,
        'sources':    [],
    }


def _actor_signal(actor_id, actor):
    """Build a per-actor signal at elevated+."""
    name = ACTOR_PROSE_NAMES.get(actor_id, actor.get('name', actor_id))
    level = actor.get('level', 'normal')
    score = actor.get('score', 0)
    article_count = actor.get('article_count', 0)
    icon = actor.get('icon', '📊')

    # Detect de-escalation
    deescalation = _has_deescalation(actor)

    # Build short_text
    if deescalation and level in ('elevated', 'high'):
        short = f"{icon} {name} — {level} but with de-escalatory rhetoric (dialogue / consulta previa)"
    elif level == 'surge':
        short = f"{icon} {name} — SURGE-level rhetoric ({article_count} signals)"
    elif level == 'high':
        short = f"{icon} {name} — high-level rhetoric tempo ({article_count} signals)"
    else:
        short = f"{icon} {name} — elevated rhetoric tempo ({article_count} signals)"

    # Build long_text — actor-specific framing
    long_text = _actor_specific_long_text(actor_id, actor, deescalation)

    # Sources
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
    score = actor.get('score', 0)
    articles = actor.get('article_count', 0)

    base_map = {
        'presidency': (
            f"Presidential rhetoric tempo at {level} ({articles} signals). "
            f"Peru's executive has cycled through six presidents since 2018; rhetoric volume here "
            f"correlates with both inter-branch friction (Congress impeachment cycle) and "
            f"electoral-cycle positioning ahead of 2026 generals."
        ),
        'cancilleria': (
            f"Foreign-ministry rhetoric tempo at {level} ({articles} signals). "
            f"Cancillería signals typically track regional disputes (Chile, Bolivia, Ecuador), "
            f"OAS positioning, and bilateral statements with US/China — elevated tempo often "
            f"precedes a multilateral inflection."
        ),
        'ffaa': (
            f"Armed Forces rhetoric tempo at {level} ({articles} signals). "
            f"FFAA institutional voice is normally low-volume; elevated tempo correlates with "
            f"state-of-emergency renewals, VRAEM operations, or — at the high end — civil-military "
            f"friction. Watch for Comando Conjunto formal statements."
        ),
        'mining_sector': (
            f"Mining-sector rhetoric tempo at {level} ({articles} signals). "
            f"Peru is the world's #1 silver producer and a top-3 copper producer; sector rhetoric "
            f"tracks labor-strike cycles, royalty/contract disputes, and environmental rulings. "
            f"Industry tempo typically leads price-impact by days."
        ),
        'las_bambas': (
            f"Las Bambas conflict rhetoric at {level} ({articles} signals). "
            f"Las Bambas alone affects ~2% of global copper supply. Community-MMG conflict cycles "
            f"through blockade → dialogue → temporary resumption phases. Watch the Apurímac corridor "
            f"and indigenous-consultation statements."
        ),
        'vraem_sendero': (
            f"VRAEM / Sendero-residual rhetoric tempo at {level} ({articles} signals). "
            f"Peru's southern coca-corridor remains a measurable security perimeter. Signal tempo "
            f"here tracks DEVIDA operations, FFAA-police joint operations, and narco-trafficking "
            f"interdiction announcements."
        ),
        'us_peru': (
            f"US-Peru bilateral rhetoric tempo at {level} ({articles} signals). "
            f"Channel includes Embassy Lima, INL drug-enforcement cooperation, SOUTHCOM military "
            f"cooperation, and US-Peru FTA dynamics. (Note: USAID was dissolved in 2025; security "
            f"and counter-narcotics cooperation is now routed through State INL and DoD.)"
        ),
        'china_peru': (
            f"China-Peru / Belt-and-Road rhetoric tempo at {level} ({articles} signals). "
            f"Anchored by Chancay megaport (COSCO 60% stake, opened Nov 2024), the BRI footprint, "
            f"and Chinese mining-sector investment (Chinalco, Shougang, Jinzhao). Elevated tempo "
            f"often precedes formal state-visit announcements or contract milestones."
        ),
    }
    base = base_map.get(actor_id, f"{ACTOR_PROSE_NAMES.get(actor_id, actor_id)} rhetoric at {level}.")
    if deescalation:
        base += " Notably, current articles include de-escalatory language (dialogue / consulta previa / agreement) — softens the elevated reading."
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
    long_text = (
        f"The commodity tracker is reporting {alert}-level pressure on Peru's {commodity_id} "
        f"sector (Peru is a {role}{rank_str}). {sig_count} cross-tracker signals flagged. "
        f"This is a coupling event — what the rhetoric tracker observes in mining_sector / "
        f"las_bambas channels has a direct supply-side implication for global {commodity_id} "
        f"markets. Watch for sector-rhetoric and price-impact alignment."
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
        'china_lac_active':   ('China-LAC posture active', 'China rhetoric tracker is reporting elevated Latin America-focused activity. Peru is a primary BRI anchor in South America; amplifies any Peru-side China-alignment vector signals.'),
        'china_bri_latam':    ('China BRI-LatAm posture active', 'BRI-LatAm-specific posture is active per the China rhetoric tracker. Direct amplification for Chancay megaport and Chinese mining-investment signals.'),
        'iran_latam_active':  ('Iran LatAm posture active', 'Iran rhetoric tracker is reporting elevated Latin America activity. Peru is not a primary Iranian theater, but amplification triggers extra vigilance on the extremist-network tripwire.'),
        'iran_hezbollah_tba': ('Hezbollah Tri-Border Area active', 'Iran tracker is reporting Hezbollah TBA-network activity. Peru is geographically distant from the TBA but supply-chain/financing routes can reach Lima; quiet tripwire stays armed.'),
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
            "Peru's rhetoric environment is at baseline across all four analytical vectors "
            "(domestic stability, resource-sector politics, US alignment, China alignment). "
            "No structural pressure events detected this scan."
        )
    elif top_vector_level == 'normal':
        parts.append(
            f"Peru's rhetoric environment is normal-tempo, with {VECTOR_NAMES.get(top_vector_id, top_vector_id)} "
            f"showing the most signal volume but no escalatory pattern."
        )
    else:
        parts.append(
            f"Peru's rhetoric environment is elevated, led by {VECTOR_NAMES.get(top_vector_id, top_vector_id)} "
            f"at {top_vector_level} ({round(top_vector_score, 1)} weighted score)."
        )

    # Sentence 2 — convergence note
    if len(elevated_vectors) >= 2:
        vec_names = [VECTOR_NAMES.get(v, v) for v in elevated_vectors]
        parts.append(
            f"Cross-vector convergence is underway: {' + '.join(vec_names[:3])} "
            f"are simultaneously above baseline, compounding Peru's risk profile."
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
    Peru's 4-vector frame. Returns a list of dicts:
      {bullet: str, weight: float}

    The bullets are intended for the rhetoric-peru.html So What card.
    Weight is used to sort (highest first); ~3-7 bullets returned typically.
    """
    bullets = []

    # ── Vector-driven implications ──
    if vector_levels.get('domestic_stability') in ('high', 'surge'):
        bullets.append({
            'bullet': "Domestic-stability vector is at " + vector_levels['domestic_stability'] +
                      " — Peru's institutional cohesion is under stress. Watch for impeachment cycles, " +
                      "cabinet reshuffles, and electoral-calendar acceleration toward 2026 generals.",
            'weight': 5.0,
        })
    elif vector_levels.get('domestic_stability') == 'elevated':
        bullets.append({
            'bullet': "Domestic-stability vector is elevated — political tempo is rising but below " +
                      "historical rupture thresholds. Track presidency, FFAA, and Congressional " +
                      "rhetoric for inflection signals.",
            'weight': 3.5,
        })

    if vector_levels.get('resource_sector') in ('high', 'surge'):
        bullets.append({
            'bullet': "Resource-sector vector at " + vector_levels['resource_sector'] +
                      " — mining-sector and Las Bambas rhetoric is at elevated supply-disruption tempo. " +
                      "Direct global commodity-pricing implications for copper and silver.",
            'weight': 4.8,
        })
    elif vector_levels.get('resource_sector') == 'elevated':
        bullets.append({
            'bullet': "Resource-sector vector is elevated — mining-community friction is signaling " +
                      "above-baseline activity. Watch for blockade duration in the Apurímac corridor " +
                      "and mesa-de-diálogo announcements.",
            'weight': 3.2,
        })

    if vector_levels.get('china_alignment') in ('high', 'surge'):
        bullets.append({
            'bullet': "China-alignment vector at " + vector_levels['china_alignment'] +
                      " — BRI / Chancay channel activity is elevated. Strategic mineral offtake, " +
                      "infrastructure-project milestones, and Lima-Beijing diplomatic tempo all signaling.",
            'weight': 4.2,
        })

    if vector_levels.get('us_alignment') in ('high', 'surge'):
        bullets.append({
            'bullet': "US-alignment vector at " + vector_levels['us_alignment'] +
                      " — Embassy Lima, INL, SOUTHCOM and FTA channels are signaling above " +
                      "baseline. Often correlates with security-cooperation milestones or trade-friction events.",
            'weight': 4.0,
        })

    # ── Tripwire-specific implications ──
    tripwire_ids = list({tw.get('id') for tw in tripwires_global or []})

    if 'las_bambas_full_closure' in tripwire_ids:
        bullets.append({
            'bullet': "Las Bambas closure tripwire is HOT — global copper supply impact is direct. " +
                      "Watch LME copper futures, MMG (TSE:1208) earnings, and Chinese-smelter " +
                      "concentrate-import statements in next 7-14 days.",
            'weight': 5.5,
        })

    if 'chancay_disruption' in tripwire_ids:
        bullets.append({
            'bullet': "Chancay megaport disruption tripwire is HOT — China-LatAm BRI flagship " +
                      "infrastructure under stress. Watch COSCO operational statements, Peruvian-government " +
                      "posture, and any U.S. Senate Foreign Relations response.",
            'weight': 5.2,
        })

    if 'state_of_emergency' in tripwire_ids:
        bullets.append({
            'bullet': "State of emergency declared — executive authority expanded over civilian " +
                      "movement and police deployment. Track geographic scope, duration, and civil-society " +
                      "/ IACHR response posture.",
            'weight': 5.0,
        })

    if 'presidential_vacancy' in tripwire_ids:
        bullets.append({
            'bullet': "Presidential vacancy / impeachment vote in motion — successful vote would " +
                      "trigger constitutional succession. Watch Congressional vote tally, FFAA institutional " +
                      "posture, and OAS regional-democracy response.",
            'weight': 5.3,
        })

    if 'extremist_network_signal' in tripwire_ids:
        bullets.append({
            'bullet': "External extremist-network signal in Peru territory — this is out-of-pattern " +
                      "for Peru (unlike the Tri-Border Area). Verify against multiple independent sources " +
                      "before treating as confirmed; this tripwire stays armed by design.",
            'weight': 5.4,
        })

    # ── Commodity coupling implications ──
    for commodity_id, risk in (commodity_pressure or {}).items():
        if risk.get('alert_level') in ('high', 'surge'):
            bullets.append({
                'bullet': f"Commodity-coupling: {commodity_id} supply pressure on Peru is at " +
                          f"{risk.get('alert_level')}. Peru's mining-sector rhetoric is now coupled " +
                          f"to global {commodity_id} pricing — sector signal volume will lead price-impact " +
                          f"by days.",
                'weight': 4.5,
            })

    # ── Default baseline implications when nothing escalatory ──
    if not bullets:
        bullets.append({
            'bullet': "All four analytical vectors are at baseline. Peru's rhetoric environment " +
                      "shows no structural pressure events this scan; baseline tempo is healthy " +
                      "for an active presidential-cycle country.",
            'weight': 1.0,
        })
        bullets.append({
            'bullet': "Watch indicators for next phase: Apurímac corridor blockade frequency, " +
                      "Boluarte-vs-Congress motion volume, Chancay throughput statements, US-Peru " +
                      "FTA review milestones.",
            'weight': 0.8,
        })

    # Sort by weight descending, return top 7
    bullets.sort(key=lambda b: -b['weight'])
    return bullets[:7]


# ============================================
# (Optional) Convenience entry point for callers
# that want a single canonical interpretation pass.
# ============================================
def interpret_peru_signals(scan_data):
    """
    Convenience wrapper — accepts a complete scan_data dict and returns the
    three derived analytical fields. Mirrors the Japan tracker's contract.
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


print("[Peru Signal Interpreter] Module loaded — v1.0.0")
