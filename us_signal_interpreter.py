"""
========================================
U.S. SIGNAL INTERPRETER (v1.1.0 -- May 17, 2026)
========================================
Analytical layer for the US Rhetoric Tracker. Where the engine collects raw
signals, this module makes them MEAN something.

v1.1 ADDS: KINETIC-PRECURSOR CADENCE DETECTION
  Recognizes the structural pattern of US executive sequencing toward kinetic
  action against a foreign target. The Venezuela January 2026 raid was preceded
  by a 21-day cadence: intel disclosure → DOJ indictment → congressional warning
  → capability disclosure → "pretext" language. When the same cadence repeats
  against a new target (e.g., Cuba May 2026 — Ratcliffe Havana visit, Castro
  indictment, Hegseth congressional testimony, 300 drones disclosure, "pretext
  for military action" language), it is the highest-confidence pre-kinetic
  indicator available via OSINT.

  CRITICAL: stays APOLITICAL. Detects the PATTERN, not political content.
  Same logic regardless of administration. Cadence detection is a tradecraft
  observation, not editorial judgment.

EXPORTS (v1.1):
  compute_top_signals(actor_results, articles, cross_theater_fps) -> list
  compute_so_what_factor(actor_results, composite, outbound_targets) -> dict
  compute_branch_divergence_score(actor_results) -> float
  compute_domestic_fracture_score(actor_results, articles) -> float
  compute_escalation_cadence_score(actor_results, articles, target) -> dict    [NEW v1.1]
  compute_kinetic_precursor_targets(actor_results, articles) -> list           [NEW v1.1]

DESIGN PHILOSOPHY:
  1. APOLITICAL FRAMING. Never editorialize about whose rhetoric is "correct" —
     report VOLATILITY and DIVERGENCE, not partisan judgment.
  2. SO WHAT. Every metric must answer "why does this matter for stability?"
     in plain language a Foreign Service Officer would write.
  3. CROSS-SPECTRUM TRANSPARENCY. Always note when our signals lean partisan
     and how we're balancing them.
  4. CONCRETE OVER ABSTRACT. "ICE raid in Atlanta sparked 4-hour standoff"
     is better than "civil unrest indicators elevated."
  5. [v1.1] STRUCTURAL PATTERN OVER POLITICAL CONTENT. Cadence detection
     observes WHAT executive branches do when sequencing toward kinetic
     action, regardless of WHO is in office or WHY they're doing it.
"""

from datetime import datetime, timezone


# ════════════════════════════════════════════════════════════════════
# BRANCH DIVERGENCE SCORE
# ════════════════════════════════════════════════════════════════════

def compute_branch_divergence_score(actor_results):
    """
    Measures how much the three branches of US government are saying
    contradictory things. Higher = more institutional friction.

    Inputs: scores for executive, legislative (both wings), judicial.
    Calc:   max actor score in each branch - min actor score in each branch,
            adjusted by tripwire pressure.
    Range:  0-100
    """
    exec_score = actor_results.get('us_executive', {}).get('actor_score', 0)
    state_score = actor_results.get('us_state_dept', {}).get('actor_score', 0)
    defense_score = actor_results.get('us_defense', {}).get('actor_score', 0)
    cong_maj = actor_results.get('us_congress_majority', {}).get('actor_score', 0)
    cong_opp = actor_results.get('us_congress_opposition', {}).get('actor_score', 0)
    judicial = actor_results.get('us_judicial', {}).get('actor_score', 0)

    # Executive branch internal divergence (rare but meaningful)
    exec_branch_max = max(exec_score, state_score, defense_score)
    exec_branch_min = min(exec_score, state_score, defense_score)
    exec_internal = exec_branch_max - exec_branch_min

    # Legislative branch divergence (majority vs opposition)
    leg_divergence = abs(cong_maj - cong_opp)

    # Judicial vs executive divergence (the "court blocks EO" signal)
    # If judicial activity is high while executive is high, that's institutional
    # friction. If judicial is low while executive is high, it's quiet acceptance.
    jud_vs_exec = abs(judicial - exec_score) if judicial > 30 and exec_score > 30 else 0

    # Weighted combination
    score = (exec_internal * 0.3 + leg_divergence * 0.4 + jud_vs_exec * 0.3)

    # Tripwire boost — if any branch had tripwires, friction is real
    total_tripwires = sum(actor_results.get(k, {}).get('tripwires', 0)
                           for k in ('us_executive', 'us_judicial', 'us_congress_opposition'))
    score += total_tripwires * 3

    return round(min(100, score), 1)


# ════════════════════════════════════════════════════════════════════
# DOMESTIC FRACTURE SCORE (cross-spectrum)
# ════════════════════════════════════════════════════════════════════

def compute_domestic_fracture_score(actor_results, articles):
    """
    Measures how internally divided US domestic rhetoric is. Distinct from
    branch divergence (which measures institutions) — this measures the
    LEFT/RIGHT/CENTER information environment.

    Inputs:
      - Reddit cross-spectrum subs (r/politics vs r/Conservative volume)
      - DHS/ICE rhetoric (high = polarizing topic active)
      - Congress majority vs opposition divergence
      - States vs federal rhetoric
    """
    # Layer 1: legislative divergence (already in branch_div but lensed differently)
    cong_maj = actor_results.get('us_congress_majority', {}).get('actor_score', 0)
    cong_opp = actor_results.get('us_congress_opposition', {}).get('actor_score', 0)
    leg_div = abs(cong_maj - cong_opp)

    # Layer 2: states vs federal
    states_score = actor_results.get('us_states', {}).get('actor_score', 0)
    fed_score = actor_results.get('us_executive', {}).get('actor_score', 0)
    state_fed_friction = abs(states_score - fed_score) if states_score > 25 and fed_score > 25 else 0

    # Layer 3: ICE/DHS as polarization indicator
    dhs_score = actor_results.get('us_dhs_ice', {}).get('actor_score', 0)
    ice_polarization = max(0, dhs_score - 25) * 0.6  # 25 baseline; above = polarizing

    # Layer 4: cross-spectrum article volume from Reddit
    reddit_left_count = 0
    reddit_right_count = 0
    reddit_center_count = 0
    for art in articles:
        if art.get('source_type') != 'reddit':
            continue
        sub = (art.get('source') or '').lower()
        if 'r/politics' in sub or 'r/liberal' in sub or 'r/democrats' in sub:
            reddit_left_count += 1
        elif 'r/conservative' in sub or 'r/republicans' in sub:
            reddit_right_count += 1
        elif 'r/moderatepolitics' in sub or 'r/centrist' in sub or 'r/neutralpolitics' in sub:
            reddit_center_count += 1

    total_partisan = reddit_left_count + reddit_right_count
    spectrum_imbalance = 0
    if total_partisan >= 10:
        ratio = max(reddit_left_count, reddit_right_count) / max(1, total_partisan)
        # Imbalanced = one side dominating discourse (high = fracture)
        spectrum_imbalance = (ratio - 0.5) * 80  # 0.5 = balanced, 1.0 = totally lopsided

    # Composite
    score = (leg_div * 0.3
             + state_fed_friction * 0.2
             + ice_polarization * 0.3
             + spectrum_imbalance * 0.2)

    return round(min(100, score), 1)


# ════════════════════════════════════════════════════════════════════
# TOP SIGNALS
# ════════════════════════════════════════════════════════════════════

def compute_top_signals(actor_results, articles, cross_theater_fps):
    """
    Build the list of top signals to surface in the frontend's "Top Signals"
    card. Each signal has:
      short_text:  ≤80 char, wire-headline style
      long_text:   2-3 sentence "so what" explanation
      severity:    'low' | 'medium' | 'high' | 'critical'
      category:    domestic | foreign | institutional | civil_social | economic
      actor_key:   which actor surfaced this (for color coding)
    """
    signals = []

    # ── Signal 1: ICE/DHS rhetoric tempo ──
    dhs = actor_results.get('us_dhs_ice', {})
    dhs_score = dhs.get('actor_score', 0)
    dhs_count = dhs.get('statement_count', 0)
    dhs_trip = dhs.get('tripwires', 0)
    if dhs_score >= 40 or dhs_trip > 0:
        sev = 'high' if dhs_trip > 0 else ('medium' if dhs_score >= 50 else 'low')
        signals.append({
            'short_text': f"ICE/DHS rhetoric elevated -- {dhs_count} statements, {dhs_trip} tripwires",
            'long_text': (
                f"Immigration enforcement rhetoric is at L{dhs.get('tier','0')[1:]} ({dhs.get('tier_name','')}). "
                f"Currently the highest-volatility US domestic signal vector and a leading indicator for "
                f"protests + civil unrest + midterm voter mobilization. Watch for operational tempo changes "
                f"as DHS funding situation evolves."
            ),
            'severity': sev,
            'category': 'civil_social',
            'actor_key': 'us_dhs_ice',
        })
    elif dhs_score >= 25:
        signals.append({
            'short_text': f"ICE/DHS rhetoric in normal range ({dhs_count} statements)",
            'long_text': (
                "Immigration enforcement signals at baseline. Operational tempo currently low due to "
                "DHS funding constraints. Worth continuing to track as midterm dynamics evolve."
            ),
            'severity': 'low',
            'category': 'civil_social',
            'actor_key': 'us_dhs_ice',
        })

    # ── Signal 2: Branch divergence ──
    exec_score = actor_results.get('us_executive', {}).get('actor_score', 0)
    judicial_score = actor_results.get('us_judicial', {}).get('actor_score', 0)
    if exec_score >= 50 and judicial_score >= 50:
        signals.append({
            'short_text': f"High executive + judicial activity -- institutional friction signal",
            'long_text': (
                f"Both executive ({exec_score}) and judicial ({judicial_score}) actors are running hot, "
                f"suggesting active court intervention on executive actions. This is institutional friction "
                f"working as designed -- a stability signal even if it FEELS volatile from inside DC."
            ),
            'severity': 'medium',
            'category': 'institutional',
            'actor_key': 'us_judicial',
        })

    # ── Signal 3: Trump executive tempo ──
    exec_data = actor_results.get('us_executive', {})
    exec_tier = exec_data.get('tier', 'L0')
    exec_trip = exec_data.get('tripwires', 0)
    if exec_data.get('baseline_ratio', 1.0) > 1.5:
        signals.append({
            'short_text': f"Executive rhetoric tempo elevated ({exec_data.get('baseline_ratio',1.0)}x baseline)",
            'long_text': (
                f"Executive branch (Trump + WH + cabinet) rhetoric is running "
                f"{exec_data.get('baseline_ratio',1.0)}x normal pace. {exec_trip} tripwires hit. "
                f"In the v1.1 release this will be cross-referenced against the historical "
                f"statement-follow-through record."
            ),
            'severity': 'high' if exec_trip > 0 else 'medium',
            'category': 'domestic',
            'actor_key': 'us_executive',
        })

    # ── Signal 4: Foreign actor responses (cross-theater fingerprints) ──
    foreign_responses = []
    for theater, fp in (cross_theater_fps or {}).items():
        if not isinstance(fp, dict):
            continue
        # Look for indicators that this country is rhetoric-targeting US
        keys_to_check = ['us_targeted', 'targets_us', 'anti_us_active', 'us_pressure']
        for key in keys_to_check:
            if fp.get(key):
                foreign_responses.append(theater)
                break
    if len(foreign_responses) >= 3:
        signals.append({
            'short_text': f"{len(foreign_responses)} theaters showing US-targeted rhetoric",
            'long_text': (
                f"Multiple foreign actors ({', '.join(foreign_responses[:5])}) are running rhetoric "
                f"explicitly targeting the United States. This is a 'world responding to US posture' "
                f"signal — usually reactive, but worth noting when it crosses three or more theaters."
            ),
            'severity': 'medium' if len(foreign_responses) < 5 else 'high',
            'category': 'foreign',
            'actor_key': 'us_state_dept',
        })

    # ── Signal 5: State-federal friction ──
    states_score = actor_results.get('us_states', {}).get('actor_score', 0)
    if states_score >= 38:
        states_trip = actor_results.get('us_states', {}).get('tripwires', 0)
        signals.append({
            'short_text': f"State governors pushing back -- federalism rhetoric elevated",
            'long_text': (
                f"Governor-level pushback against federal posture is at L"
                f"{actor_results.get('us_states', {}).get('tier','L0')[1:]}. "
                f"Watch for: lawsuits filed by state AGs, sanctuary declarations, "
                f"national guard deployment disputes."
            ),
            'severity': 'high' if states_trip > 0 else 'medium',
            'category': 'institutional',
            'actor_key': 'us_states',
        })

    # ── Signal 6: Fed independence stress ──
    fed_score = actor_results.get('us_federal_reserve', {}).get('actor_score', 0)
    if fed_score >= 40:
        signals.append({
            'short_text': "Federal Reserve rhetoric elevated -- independence pressure?",
            'long_text': (
                f"Fed activity at L{actor_results.get('us_federal_reserve', {}).get('tier','L0')[1:]}. "
                f"Could indicate FOMC dissent, Powell-WH friction, or major rate decision week. "
                f"Markets-stability proxy."
            ),
            'severity': 'medium',
            'category': 'economic',
            'actor_key': 'us_federal_reserve',
        })

    # ── Signal 7: Defense / military posture ──
    defense_score = actor_results.get('us_defense', {}).get('actor_score', 0)
    defense_trip = actor_results.get('us_defense', {}).get('tripwires', 0)
    if defense_score >= 45 or defense_trip > 0:
        signals.append({
            'short_text': f"DoD posture rhetoric elevated -- {defense_trip} tripwires",
            'long_text': (
                f"Pentagon / combatant command rhetoric running hot. Cross-reference against "
                f"the Asifah Military Tracker fingerprint for actual fleet/troop movements. "
                f"Rhetoric without movement = posturing; rhetoric with movement = preparation."
            ),
            'severity': 'high' if defense_trip > 0 else 'medium',
            'category': 'foreign',
            'actor_key': 'us_defense',
        })

    # ── Signal: Kinetic-Precursor Cadence (v1.1) ──
    # Structural detection of US executive sequencing toward foreign kinetic
    # action. APOLITICAL — pattern observation, not political content.
    cadence_targets = compute_kinetic_precursor_targets(actor_results, articles)
    for cdt in cadence_targets:
        if cdt['indicator_count'] >= 3:  # only surface 'forming' tier or higher
            tier = cdt['tier']
            if tier == 'pre_kinetic':
                sev = 'critical'
                short = f"🚨 PRE-KINETIC CADENCE: {cdt['flag']} {cdt['label']} -- 5/5 indicators (VZ 2026 pattern)"
            elif tier == 'developing':
                sev = 'high'
                short = f"⏱️ Cadence developing: {cdt['flag']} {cdt['label']} -- 4/5 indicators"
            else:
                sev = 'high'
                short = f"⏱️ Cadence forming: {cdt['flag']} {cdt['label']} -- 3/5 indicators"
            signals.append({
                'short_text': short,
                'long_text': cdt['assessment'],
                'severity': sev,
                'category': 'foreign',
                'actor_key': 'us_executive',
            })

    # ── Sort by severity ──
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    signals.sort(key=lambda s: severity_order.get(s.get('severity', 'low'), 9))

    return signals[:10]  # cap at 10


# ════════════════════════════════════════════════════════════════════
# SO WHAT FACTOR
# ════════════════════════════════════════════════════════════════════

def compute_so_what_factor(actor_results, composite, outbound_targets):
    """
    Generate the headline "So What" framing for the dashboard. This is the
    elevator-pitch summary an FSO would write at the top of a daily brief.

    Returns dict with:
      factor:       short label
      description:  2-3 sentence narrative
      bullet_points: list of 3-5 strategic implications
    """
    # Determine the dominant story
    actors_by_score = sorted(actor_results.items(),
                             key=lambda kv: kv[1].get('actor_score', 0),
                             reverse=True)
    top_actor_key = actors_by_score[0][0] if actors_by_score else None
    top_actor_score = actors_by_score[0][1].get('actor_score', 0) if actors_by_score else 0

    # Calibration framing -- US is generally stable
    if composite < 26:
        factor = 'Quiet Week'
        description = (
            "U.S. rhetoric across all branches is at baseline. Coherent posture, low partisan "
            "divergence, allies aligned with messaging. The view from DC may feel quieter than "
            "usual; the view from the rest of the country is normalcy."
        )
    elif composite < 38:
        factor = 'Active / Stable'
        description = (
            "U.S. posture is assertive but coherent. Normal partisan disagreement is present "
            "but institutions are functioning. This is the median operating state -- not a "
            "stability concern even if individual statements draw headlines."
        )
    elif composite < 51:
        factor = 'Active+ / Watch'
        description = (
            "U.S. rhetoric tempo is elevated, trending toward volatile. Multiple branches are "
            "running hot simultaneously, which can indicate either a major foreign policy "
            "moment or escalating domestic friction. Worth daily monitoring."
        )
    elif composite < 66:
        factor = 'Volatile'
        description = (
            "Sharp partisan rhetoric divergence is present. Allies may be distancing themselves "
            "publicly; branches are issuing contradictory signals. From inside Washington this "
            "feels intense; broader country may not feel it equally outside political class."
        )
    elif composite < 76:
        factor = 'Volatile+ / Allied Friction'
        description = (
            "Branches are publicly contradicting each other, allies are showing public skepticism, "
            "and multiple foreign actors are responding directly to US posture. Real institutional "
            "friction. Worth elevated tracking and cross-theater correlation."
        )
    else:
        factor = 'Crisis Rhetoric'
        description = (
            "Branches are openly fighting in public, allies are breaking publicly, multiple foreign "
            "actors are targeting the US directly. This level is rare and indicates potential "
            "constitutional or international crisis. Cross-theater impact will be substantial."
        )

    # Build bullet points
    bullets = []

    # Bullet 1: ICE/DHS context (always relevant given calibration note)
    dhs = actor_results.get('us_dhs_ice', {})
    dhs_score = dhs.get('actor_score', 0)
    if dhs_score >= 38:
        bullets.append(
            f"Immigration enforcement (DHS/ICE) at L{dhs.get('tier','L0')[1:]} -- "
            f"highest-volatility domestic vector, midterm-driver indicator."
        )
    else:
        bullets.append(
            "DHS/ICE rhetoric at baseline despite usual elevated profile -- "
            "operational tempo constrained by recent shutdown / DHS funding situation."
        )

    # Bullet 2: top actor
    if top_actor_key and top_actor_score > 30:
        actor_name = top_actor_key.replace('us_', '').replace('_', ' ').title()
        bullets.append(f"Loudest actor this period: {actor_name} ({top_actor_score}/100).")

    # Bullet 3: outbound targets
    if outbound_targets:
        target_list = ', '.join([t['country'].title() for t in outbound_targets[:3]])
        bullets.append(f"US rhetoric targeting: {target_list}.")
    else:
        bullets.append("No specific country is being heavily rhetoric-targeted by US executive this period.")

    # Bullet 4: judicial signal
    jud_score = actor_results.get('us_judicial', {}).get('actor_score', 0)
    if jud_score >= 45:
        bullets.append(
            f"Judicial activity elevated ({jud_score}/100) -- institutional pushback "
            f"working as designed; this is healthy friction even if it feels disruptive."
        )

    # Bullet: Kinetic-precursor cadence (v1.1) -- structural observation
    # Apolitical: same logic regardless of administration.
    try:
        cadence_targets = compute_kinetic_precursor_targets(actor_results, [])
        elevated = [c for c in cadence_targets if c['indicator_count'] >= 3]
        if elevated:
            top = elevated[0]
            bullets.append(
                f"⏱️ Kinetic-precursor cadence active vs. {top['flag']} {top['label']} "
                f"({top['indicator_count']}/5 indicators, tier: {top['tier']}). Structural pattern "
                f"observation — same indicators repeat across administrations."
            )
    except Exception:
        pass  # cadence detection is additive; don't break so-what if it fails

    # Bullet 5: divergence framing
    if composite >= 51:
        bullets.append(
            "Cross-spectrum framing reminder: this score measures rhetoric VOLATILITY and "
            "DIVERGENCE, not aggression. Asifah is apolitical infrastructure."
        )

    return {
        'factor':         factor,
        'description':    description,
        'bullet_points':  bullets[:5],
        'composite_score': composite,
        'updated_at':     datetime.now(timezone.utc).isoformat(),
    }


# ════════════════════════════════════════════════════════════════════
# KINETIC-PRECURSOR CADENCE DETECTION (v1.1)
# ════════════════════════════════════════════════════════════════════
# Structural detection of US executive sequencing toward foreign kinetic
# action. APOLITICAL — same logic regardless of administration.
#
# The pattern (Venezuela January 2026 precedent, 21-day window):
#   1. INTEL_DISCLOSURE: senior intel official visits target country OR
#      public intelligence disclosure about target
#   2. LEGAL_PRETEXT:    DOJ indictment of target's senior officials
#   3. POLICY_PRETEXT:   Sec-Def or Sec-State congressional warning about target
#   4. CAPABILITY_DISCLOSURE: public reveal of target's kinetic capability
#      (drone arsenal, missile cache, etc.) that frames target as threat
#   5. ACTION_PRETEXT:   "pretext for military action" / "could become a
#      pretext" language from US official re: target
#
# Score = 20 points per indicator. 0-100 scale.
#   0-39:  baseline (some signals present, no cadence pattern)
#   40-59: cadence forming (3 indicators)
#   60-79: cadence developing (4 indicators)
#   80-100: cadence complete = pre-kinetic (5 indicators in 14-day window)

# Targets known to track for cadence (extensible)
_KINETIC_PRECURSOR_TARGETS = {
    'cuba': {
        'label': 'Cuba',
        'flag': '🇨🇺',
        'target_official_terms': ['castro', 'raul castro', 'diaz-canel', 'cuban government'],
        'intel_official_terms':  ['ratcliffe', 'cia director'],
        'intel_visit_locations': ['havana', 'cuba'],
        'capability_terms':      ['300 drones', 'drone threat', 'drone strike', 'mohajer cuba',
                                  'shahed cuba', 'iranian advisers cuba', 'iranian advisers havana',
                                  'cuban drone'],
    },
    'venezuela': {
        'label': 'Venezuela',
        'flag': '🇻🇪',
        'target_official_terms': ['maduro', 'venezuelan government'],
        'intel_official_terms':  ['burns', 'cia director'],
        'intel_visit_locations': ['caracas', 'venezuela'],
        'capability_terms':      ['mohajer venezuela', 'iranian engineers venezuela',
                                  'venezuela drone'],
    },
    'iran': {
        'label': 'Iran',
        'flag': '🇮🇷',
        'target_official_terms': ['khamenei', 'iranian government', 'irgc'],
        'intel_official_terms':  ['cia director iran', 'mossad iran'],
        'intel_visit_locations': ['tehran'],
        'capability_terms':      ['iran nuclear breakout', 'iran enrichment', 'iran missile cache'],
    },
}


def _detect_cadence_indicators(target_key, actor_results, articles):
    """
    Detect kinetic-precursor cadence indicators for a specific target.
    Returns dict with 5 boolean flags + count.

    APOLITICAL: pattern recognition only — no political framing of why.
    """
    target_cfg = _KINETIC_PRECURSOR_TARGETS.get(target_key, {})
    if not target_cfg:
        return {'count': 0, 'indicators': {}}

    target_terms     = target_cfg.get('target_official_terms', [])
    intel_terms      = target_cfg.get('intel_official_terms', [])
    visit_locations  = target_cfg.get('intel_visit_locations', [])
    capability_terms = target_cfg.get('capability_terms', [])

    indicators = {
        'intel_disclosure':       False,
        'legal_pretext':          False,
        'policy_pretext':         False,
        'capability_disclosure':  False,
        'action_pretext':         False,
    }

    # Aggregate text corpus: all article titles + actor matched-keyword strings
    corpus_parts = []
    for art in (articles or []):
        title = (art.get('title') or '').lower()
        desc  = (art.get('description') or art.get('snippet') or '').lower()
        corpus_parts.append(title + ' ' + desc)

    for actor_key in ('us_executive', 'us_state_dept', 'us_defense',
                       'us_congress_majority', 'us_congress_opposition',
                       'us_judicial', 'us_intelligence'):
        ac = actor_results.get(actor_key, {})
        kws = ac.get('keywords_matched', []) or []
        corpus_parts.append(' '.join(str(k).lower() for k in kws))
        # Also scan top_articles per actor
        for art in (ac.get('top_articles', []) or []):
            corpus_parts.append((art.get('title') or '').lower())

    corpus = ' '.join(corpus_parts)

    # ── INDICATOR 1: intel_disclosure ──
    # Senior intel official visits target country OR public intelligence disclosure
    for intel_term in intel_terms:
        if intel_term in corpus:
            for loc in visit_locations:
                if loc in corpus:
                    indicators['intel_disclosure'] = True
                    break
        if indicators['intel_disclosure']:
            break
    # Or generic intel disclosure framing
    if not indicators['intel_disclosure']:
        if any(phrase in corpus for phrase in (
            f'{target_key} intelligence disclosure',
            f'us intelligence {target_key}',
            f'cia warns {target_key}',
        )):
            indicators['intel_disclosure'] = True

    # ── INDICATOR 2: legal_pretext (DOJ indictment of target official) ──
    if 'indictment' in corpus or 'indicted' in corpus or 'doj charges' in corpus:
        for ot in target_terms:
            if ot in corpus:
                indicators['legal_pretext'] = True
                break

    # ── INDICATOR 3: policy_pretext (Sec-Def/State congressional warning) ──
    sec_terms = ['hegseth', 'secretary of defense', 'sec-def', 'rubio',
                 'secretary of state', 'sec-state']
    cong_terms = ['congressional hearing', 'congressional testimony',
                  'committee hearing', 'testified to congress',
                  'before congress', 'house committee', 'senate committee',
                  'diaz-balart']
    sec_active = any(t in corpus for t in sec_terms)
    cong_active = any(t in corpus for t in cong_terms)
    target_in_corpus = any(ot in corpus for ot in target_terms) or target_key in corpus
    if sec_active and cong_active and target_in_corpus:
        indicators['policy_pretext'] = True

    # ── INDICATOR 4: capability_disclosure ──
    for cap_term in capability_terms:
        if cap_term in corpus:
            indicators['capability_disclosure'] = True
            break

    # ── INDICATOR 5: action_pretext ──
    pretext_phrases = ['pretext for military action', 'pretext for action',
                       'could become a pretext', 'pretext for strike',
                       'military pretext', 'us military action against']
    for phrase in pretext_phrases:
        if phrase in corpus:
            # Verify target is in corpus too
            if target_in_corpus:
                indicators['action_pretext'] = True
                break

    count = sum(1 for v in indicators.values() if v)
    return {'count': count, 'indicators': indicators}


def compute_escalation_cadence_score(actor_results, articles, target='cuba'):
    """
    Compute kinetic-precursor cadence score for a specific foreign target.

    Returns dict with:
      target:           target country key
      label:            display name
      flag:             country flag emoji
      score:            0-100 (20 points per active indicator)
      tier:             'baseline' | 'forming' | 'developing' | 'pre_kinetic'
      indicator_count:  0-5 indicators present
      indicators:       dict of which indicators are active
      assessment:       structural narrative (apolitical)
    """
    target = (target or 'cuba').lower()
    target_cfg = _KINETIC_PRECURSOR_TARGETS.get(target)
    if not target_cfg:
        return {
            'target': target, 'label': target.title(), 'flag': '',
            'score': 0, 'tier': 'baseline', 'indicator_count': 0,
            'indicators': {}, 'assessment': f'Target "{target}" not configured for cadence tracking.',
        }

    detection = _detect_cadence_indicators(target, actor_results, articles)
    count = detection['count']
    score = count * 20  # 5 indicators * 20 = 100

    # Tier
    if count >= 5:
        tier = 'pre_kinetic'
        tier_label = 'PRE-KINETIC (cadence complete)'
    elif count >= 4:
        tier = 'developing'
        tier_label = 'CADENCE DEVELOPING (4/5 indicators)'
    elif count >= 3:
        tier = 'forming'
        tier_label = 'CADENCE FORMING (3/5 indicators)'
    elif count >= 1:
        tier = 'baseline'
        tier_label = 'BASELINE WITH SIGNALS'
    else:
        tier = 'baseline'
        tier_label = 'BASELINE'

    # Apolitical structural assessment
    active_names = [k.replace('_', ' ').title()
                    for k, v in detection['indicators'].items() if v]

    if tier == 'pre_kinetic':
        assessment = (
            f"All 5 cadence indicators active for {target_cfg['label']}: {', '.join(active_names)}. "
            f"This is the structural signature of US executive sequencing toward kinetic action — "
            f"the same pattern that preceded the Venezuela January 2026 raid by ~21 days. "
            f"OBSERVATION ONLY: cadence detection is a tradecraft pattern, not a prediction. "
            f"Pattern may resolve through diplomacy, deterrence, or executive de-escalation. "
            f"Same indicators repeat regardless of which administration is in office."
        )
    elif tier == 'developing':
        assessment = (
            f"4/5 cadence indicators active for {target_cfg['label']}: {', '.join(active_names)}. "
            f"Approaching the Venezuela 2026 pre-kinetic pattern threshold. "
            f"Missing indicator may emerge in next 3-7 days if cadence continues. "
            f"Observation, not prediction."
        )
    elif tier == 'forming':
        assessment = (
            f"3/5 cadence indicators active for {target_cfg['label']}: {', '.join(active_names)}. "
            f"Cadence forming but not yet at developed threshold. "
            f"Pattern may either accelerate or dissipate. Worth daily monitoring."
        )
    elif count >= 1:
        assessment = (
            f"{count}/5 cadence indicators active for {target_cfg['label']}: {', '.join(active_names)}. "
            f"Below cadence-formation threshold (3 needed). "
            f"Routine monitoring."
        )
    else:
        assessment = (
            f"No cadence indicators active for {target_cfg['label']}. "
            f"US posture toward target is below escalation-sequencing threshold."
        )

    return {
        'target':           target,
        'label':            target_cfg['label'],
        'flag':             target_cfg['flag'],
        'score':            score,
        'tier':             tier,
        'tier_label':       tier_label,
        'indicator_count':  count,
        'indicators':       detection['indicators'],
        'assessment':       assessment,
    }


def compute_kinetic_precursor_targets(actor_results, articles):
    """
    Scan all configured targets and return list of targets with elevated
    cadence scores (>= 'forming' tier). The "kinetic-precursor watch list."

    APOLITICAL: returns structural observation, sorted by score descending.
    """
    elevated = []
    for target_key in _KINETIC_PRECURSOR_TARGETS:
        result = compute_escalation_cadence_score(actor_results, articles, target_key)
        if result['indicator_count'] >= 1:
            elevated.append(result)

    elevated.sort(key=lambda r: r['score'], reverse=True)
    return elevated


print("[US Signal Interpreter] Module loaded -- v1.1.0")
