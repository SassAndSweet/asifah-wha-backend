"""
cuba_signal_interpreter.py
Asifah Analytics -- WHA Backend Module
v1.0.0 -- April 2026

Signal interpretation engine for the Cuba Rhetoric Tracker.

Cuba's analytical frame is fundamentally THREE questions answered simultaneously:

  1. Is the U.S. escalating from rhetoric to coercion to unilateral action?
     How far is Washington actually willing to go -- and what's the trigger?

  2. Is the Cuban regime stabilizing or fracturing under that pressure?
     Is G2 suppression holding? Are dissident signals rising? Is economic
     collapse accelerating regime brittleness?

  3. Are Russia / China / Iran exploiting the friction to gain access?
     (Lourdes SIGINT, Mariel port visits, Iranian tankers, IRGC delegations)

Key contextual factors baked in:
  - Lourdes SIGINT station (closed 2001) reactivation rumors recurrent since 2023
  - Mariel Port positioned for PLAN deep-water access -- Chinese strategic interest
  - Migration: Cuba's pressure-release valve AND US policy crisis trigger
    (1980 Mariel, 1994 Balsero pattern)
  - Regime transition: Diaz-Canel weakest post-Castro leader; succession opaque
  - US policy oscillation: Obama opening --> Trump rollback --> Biden status quo
    --> Trump II re-escalation. Chronic policy whiplash amplifies fracture risk.
  - Havana Syndrome: unresolved, possible Russian SIGINT ties

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone


# ============================================================
# RED LINE DEFINITIONS
# ============================================================
RED_LINES = [

    # ── Category A: US escalation triggers ─────────────────
    {
        'id':       'us_direct_military_action',
        'label':    'U.S. Direct Military Action Against Cuba',
        'detail':   'US conducts blockade, strike, or military interdiction inside Cuban territorial '
                    'waters or airspace without Cuban consent',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '⚓',
        'category': 'us_escalation',
        'source':   'Kinetic US action against Cuba would be the first since 1962 and would trigger '
                    'Russia/China response calculations across the Caribbean.',
    },
    {
        'id':       'us_unilateral_coercion',
        'label':    'U.S. Unilateral Coercion Beyond OAS Norms',
        'detail':   'US imposes extraordinary measures (total blockade escalation, secondary sanctions '
                    'against OAS member states trading with Cuba) outside multilateral consensus',
        'severity': 2,
        'color':    '#ef4444',
        'icon':     '🦅',
        'category': 'us_escalation',
        'source':   'Secondary sanctions against OAS members fracture hemispheric consensus and '
                    'push Latin American states toward Russia/China alignment.',
    },

    # ── Category B: Regime fracture ─────────────────────────
    {
        'id':       'mass_migration_event',
        'label':    'Mass Migration Event (>5k arrivals in 30 days)',
        'detail':   'Large-scale Cuban migration surge to US waters, overwhelming Coast Guard '
                    'interdiction capacity',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🚤',
        'category': 'regime_fracture',
        'source':   'Mariel (1980) and Balsero (1994) patterns -- mass migration is both a regime '
                    'pressure-release valve and a US policy crisis trigger.',
    },
    {
        'id':       'regime_succession',
        'label':    'Regime Succession / Diaz-Canel Departure',
        'detail':   'Diaz-Canel removed, resigns, or dies; leadership transition triggers succession '
                    'crisis',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '👑',
        'category': 'regime_fracture',
        'source':   'Cuba has no modern precedent for non-Castro succession. Any transition is '
                    'a potential hard-landing scenario.',
    },
    {
        'id':       'military_protest_suppression',
        'label':    'Cuban Military Mobilization Against Protests',
        'detail':   'FAR (army) deployed against civilian protesters, not just MININT/G2 -- signals '
                    'regime fears loss of control',
        'severity': 2,
        'color':    '#ef4444',
        'icon':     '🪖',
        'category': 'regime_fracture',
        'source':   'Cuban military deployed against civilians would be a first since 1958. '
                    'Crosses civil-military red line.',
    },

    # ── Category C: Adversary access ────────────────────────
    {
        'id':       'lourdes_reactivation',
        'label':    'Lourdes SIGINT Station Reactivation Confirmed',
        'detail':   'Russian signals intelligence station at Lourdes (closed 2001) formally '
                    'reactivated for US East Coast collection',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '📡',
        'category': 'adversary_access',
        'source':   'Lourdes reactivation = strategic-level intelligence threat to US East Coast '
                    'military, political, and economic targets. Recurrent rumor since 2014.',
    },
    {
        'id':       'plan_warship_mariel',
        'label':    'PLAN Warship Visit to Mariel',
        'detail':   'Chinese PLA Navy warship docks at Mariel Special Development Zone -- marks '
                    'formal Chinese naval access in the Caribbean',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🚢',
        'category': 'adversary_access',
        'source':   'First-of-kind PLAN Caribbean port visit would be strategic signal comparable to '
                    'Russian warship 2014 visits. Mariel is positioned for submarine/carrier access.',
    },
    {
        'id':       'iran_tanker_cuba',
        'label':    'Iran Tanker Docking at Cuban Port',
        'detail':   'Iran-flagged oil tanker (under US sanctions) docks at Cuban port, delivering '
                    'petroleum in violation of US sanctions architecture',
        'severity': 2,
        'color':    '#ef4444',
        'icon':     '🛢️',
        'category': 'adversary_access',
        'source':   'Iran-Cuba oil trade has occurred episodically since 2020; increased frequency '
                    'signals coordinated sanctions evasion with Russia backing.',
    },
]


# ============================================================
# RED LINE SCORING
# ============================================================
def _scan_actor_articles(actor_results, actor_keys, keywords):
    """
    Scan top_articles across the given actor(s) for any of the given keywords.
    Returns True if any keyword matches any article title.
    """
    for aid in actor_keys:
        actor_data = actor_results.get(aid, {})
        for art in actor_data.get('top_articles', []):
            title = (art.get('title') or '').lower()
            desc  = (art.get('description') or '').lower()
            text  = f"{title} {desc}"
            if any(kw.lower() in text for kw in keywords):
                return True
    return False


def _rl(rl_id):
    """Helper to fetch a red-line template by id."""
    for r in RED_LINES:
        if r['id'] == rl_id:
            return r
    return None


def check_red_lines(articles, actor_results):
    """
    Evaluate all 8 Cuba red lines against scan data.
    Returns list of triggered red lines with 'status' = BREACHED or APPROACHING.
    """
    triggered = []

    # Extract escalation levels for readability
    def lvl(key):
        return actor_results.get(key, {}).get('escalation_level', 0)

    us_gov  = lvl('us_government')
    us_sanc = lvl('us_sanctions_regulatory')
    us_mil  = lvl('us_military_posture')
    cu_gov  = lvl('cuban_government')
    cu_mil  = lvl('cuban_military_security')
    cu_diss = lvl('cuban_dissidents')
    ru_axis = lvl('russia_cuba_axis')
    cn_axis = lvl('china_cuba_axis')
    ir_axis = lvl('iran_cuba_axis')

    us_pressure = max(us_gov, us_sanc, us_mil)

    # ── US DIRECT MILITARY ACTION ────────────────────────────
    us_military_action = _scan_actor_articles(
        actor_results,
        ['us_military_posture', 'us_government'],
        ['us naval blockade cuba', 'us strike cuba', 'us interdiction cuban waters',
         'us forces enter cuba', 'us military action cuba', 'us warship cuba',
         'us airstrike cuba', 'us invasion cuba'],
    )
    if us_military_action or us_mil >= 5:
        triggered.append({
            **_rl('us_direct_military_action'),
            'status':  'BREACHED' if (us_military_action and us_mil >= 4) else 'APPROACHING',
            'trigger': f'US military posture L{us_mil} -- '
                       f'{"kinetic action language detected" if us_military_action else "approaching threshold"}',
        })

    # ── US UNILATERAL COERCION ──────────────────────────────
    secondary_sanctions = _scan_actor_articles(
        actor_results,
        ['us_sanctions_regulatory', 'us_government'],
        ['secondary sanctions cuba', 'us total blockade cuba', 'us sanctions mexico cuba',
         'helms burton title iii activated', 'title iii lawsuits cuba',
         'secondary sanctions against cuba partners'],
    )
    if secondary_sanctions or us_sanc >= 4:
        triggered.append({
            **_rl('us_unilateral_coercion'),
            'status':  'BREACHED' if (secondary_sanctions and us_sanc >= 3) else 'APPROACHING',
            'trigger': f'US sanctions L{us_sanc} -- '
                       f'{"secondary-sanctions or extraordinary-measure language detected" if secondary_sanctions else "approaching coercion threshold"}',
        })

    # ── MASS MIGRATION EVENT ────────────────────────────────
    migration_signal = _scan_actor_articles(
        actor_results,
        ['cuban_dissidents', 'us_military_posture'],
        ['cuba migration surge', 'cuba mariel style', 'balsero crisis',
         'cuba mass exodus', 'coast guard overwhelmed cuba', 'cuban rafters surge',
         'mass cuban arrivals florida', 'cuba exodus 2026', 'cuba exodus wave'],
    )
    if migration_signal or (cu_diss >= 3 and us_mil >= 3):
        triggered.append({
            **_rl('mass_migration_event'),
            'status':  'BREACHED' if migration_signal else 'APPROACHING',
            'trigger': f'Dissident L{cu_diss}, US mil posture L{us_mil} -- '
                       f'{"migration surge language detected" if migration_signal else "pressure cooker conditions"}',
        })

    # ── REGIME SUCCESSION ──────────────────────────────────
    succession_signal = _scan_actor_articles(
        actor_results,
        ['cuban_government', 'cuban_dissidents'],
        ['diaz-canel resigns', 'diaz-canel removed', 'diaz-canel steps down',
         'cuba new leader', 'cuba leadership transition', 'diaz-canel health',
         'cuba succession crisis', 'cuba emergency powers', 'cuba martial law'],
    )
    if succession_signal:
        triggered.append({
            **_rl('regime_succession'),
            'status':  'BREACHED',
            'trigger': 'Succession / leadership transition language detected',
        })

    # ── CUBAN MILITARY PROTEST SUPPRESSION ─────────────────
    far_deployment = _scan_actor_articles(
        actor_results,
        ['cuban_military_security'],
        ['cuban army protesters', 'far deployed cuba protest', 'cuba military fires protesters',
         'cuba soldiers shoot', 'cuban army streets', 'far vs civilians cuba'],
    )
    if far_deployment or (cu_mil >= 4 and cu_diss >= 3):
        triggered.append({
            **_rl('military_protest_suppression'),
            'status':  'BREACHED' if far_deployment else 'APPROACHING',
            'trigger': f'Cuban military L{cu_mil}, dissident L{cu_diss} -- '
                       f'{"FAR deployment vs civilians detected" if far_deployment else "escalating suppression pattern"}',
        })

    # ── LOURDES REACTIVATION ───────────────────────────────
    lourdes_signal = _scan_actor_articles(
        actor_results,
        ['russia_cuba_axis'],
        ['lourdes reactivated', 'lourdes reopened', 'lourdes sigint confirmed',
         'russia cuba signals intelligence operational', 'lourdes station active',
         'lourdes back online', 'lourdes russia confirmed'],
    )
    if lourdes_signal or ru_axis >= 4:
        triggered.append({
            **_rl('lourdes_reactivation'),
            'status':  'BREACHED' if lourdes_signal else 'APPROACHING',
            'trigger': f'Russia-Cuba axis L{ru_axis} -- '
                       f'{"Lourdes confirmed operational" if lourdes_signal else "approaching SIGINT reactivation threshold"}',
        })

    # ── PLAN WARSHIP MARIEL ────────────────────────────────
    plan_signal = _scan_actor_articles(
        actor_results,
        ['china_cuba_axis'],
        ['plan warship mariel', 'chinese navy mariel', 'china warship cuba port',
         'plan caribbean deployment', 'chinese warship havana', 'china naval base cuba',
         'plan dock cuba', 'chinese fleet mariel'],
    )
    if plan_signal or cn_axis >= 4:
        triggered.append({
            **_rl('plan_warship_mariel'),
            'status':  'BREACHED' if plan_signal else 'APPROACHING',
            'trigger': f'China-Cuba axis L{cn_axis} -- '
                       f'{"PLAN warship Mariel language detected" if plan_signal else "approaching Chinese naval access"}',
        })

    # ── IRAN TANKER CUBA ───────────────────────────────────
    iran_tanker = _scan_actor_articles(
        actor_results,
        ['iran_cuba_axis'],
        ['iran tanker cuba', 'iran oil cuba shipment', 'iranian tanker havana',
         'iran petroleum cuba docked', 'iran crude cuba', 'iran tanker caribbean'],
    )
    if iran_tanker or ir_axis >= 3:
        triggered.append({
            **_rl('iran_tanker_cuba'),
            'status':  'BREACHED' if iran_tanker else 'APPROACHING',
            'trigger': f'Iran-Cuba axis L{ir_axis} -- '
                       f'{"Iran tanker docking detected" if iran_tanker else "approaching Iran-Cuba oil threshold"}',
        })

    return triggered


# ============================================================
# HISTORICAL MATCHES (placeholder for Session B tuning)
# ============================================================
def build_historical_matches(actor_results, vectors):
    """
    Match current Cuba signal state to historical analogs.
    Returns list of dicts with analog name, year, similarity notes.
    TODO: refine with Redis-cached historical pattern matching in Session B.
    """
    matches = []

    us_pressure       = vectors.get('us_pressure', 0)
    regime_fracture   = vectors.get('regime_fracture', 0)
    adversary_access  = vectors.get('adversary_access', 0)

    # 1980 Mariel analog
    if us_pressure >= 3 and regime_fracture >= 2:
        matches.append({
            'label':      'Mariel Boatlift (1980)',
            'year':       1980,
            'similarity': 'US pressure + regime fracture + migration pressure cooker. '
                          'Castro opened Mariel to release 125,000 to US as pressure valve.',
            'score':      75,
        })

    # 1994 Balsero analog
    if us_pressure >= 2 and regime_fracture >= 3:
        matches.append({
            'label':      'Balsero Crisis (1994)',
            'year':       1994,
            'similarity': 'Economic collapse + unrest + US pressure. Mass rafter exodus after '
                          'Maleconazo protests.',
            'score':      70,
        })

    # 2021 July 11 analog
    if regime_fracture >= 3:
        matches.append({
            'label':      '11J Protests (July 2021)',
            'year':       2021,
            'similarity': 'Largest protests in decades, driven by economic collapse, blackouts, '
                          'COVID mishandling. Pattern: dissident surge + G2 crackdown wave.',
            'score':      68,
        })

    # Russia 2014-era analog (Caribbean cooperation signals)
    if adversary_access >= 3:
        matches.append({
            'label':      'Russia Caribbean Revival (2014)',
            'year':       2014,
            'similarity': 'Russian warship visits resumed, Lourdes reactivation rumors, Lavrov '
                          'Cuba visit. Pattern of Moscow leveraging Havana during US-Russia friction.',
            'score':      65,
        })

    # China 2023 WSJ spy-base analog
    if adversary_access >= 2 and actor_results.get('china_cuba_axis', {}).get('escalation_level', 0) >= 2:
        matches.append({
            'label':      'WSJ China Spy Base Revelation (June 2023)',
            'year':       2023,
            'similarity': 'Public surfacing of Chinese SIGINT operation at Bejucal. '
                          'Beijing pattern: covert infrastructure surfaced by US press.',
            'score':      60,
        })

    matches.sort(key=lambda m: -m.get('score', 0))
    return matches[:3]  # Top 3 only


# ============================================================
# SO WHAT FACTOR
# ============================================================
def build_so_what(scan_data, red_lines_triggered, historical_matches):
    """
    Generate Cuba command-node assessment.
    Five-level scenario ladder tuned for Cuba's three-question frame.
    """
    actors = scan_data.get('actors', {})

    def lvl(key):
        return actors.get(key, {}).get('escalation_level', 0)

    us_gov   = lvl('us_government')
    us_sanc  = lvl('us_sanctions_regulatory')
    us_mil   = lvl('us_military_posture')
    cu_gov   = lvl('cuban_government')
    cu_mil   = lvl('cuban_military_security')
    cu_diss  = lvl('cuban_dissidents')
    ru_axis  = lvl('russia_cuba_axis')
    cn_axis  = lvl('china_cuba_axis')
    ir_axis  = lvl('iran_cuba_axis')

    # Three composite vectors (map to the three analytical questions)
    us_pressure      = scan_data.get('us_pressure',      max(us_gov, us_sanc, us_mil))
    regime_fracture  = scan_data.get('regime_fracture',  max(cu_diss - cu_mil, 0))
    adversary_access = scan_data.get('adversary_access', max(ru_axis, cn_axis, ir_axis))

    breached_count    = sum(1 for r in red_lines_triggered if r.get('status') == 'BREACHED')
    approaching_count = sum(1 for r in red_lines_triggered if r.get('status') == 'APPROACHING')

    # ── Scenario label ──
    if breached_count >= 2 or us_mil >= 5:
        scenario       = 'CRITICAL -- Multiple Red Lines Breached or US Military Action Active'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif breached_count >= 1 or us_pressure >= 4:
        scenario       = 'ELEVATED -- Red Line Breached or US Pressure at Coercion Level'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif us_pressure >= 3 or regime_fracture >= 3 or adversary_access >= 3:
        scenario       = 'WARNING -- One Vector Above Confrontation Threshold'
        scenario_color = '#f59e0b'
        scenario_icon  = '🟡'
    elif us_pressure >= 2 or regime_fracture >= 2 or adversary_access >= 2:
        scenario       = 'MONITORING -- Baseline Elevated, No Confrontation Signals'
        scenario_color = '#3b82f6'
        scenario_icon  = '🔵'
    else:
        scenario       = 'BASELINE -- Routine Rhetoric, No Convergence'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'

    # ── Situation (three paragraphs, one per analytical question) ──
    situation_parts = []

    # Q1: US pressure
    if us_pressure >= 2:
        situation_parts.append(
            f'U.S. pressure vector at L{us_pressure}: '
            f'{"executive rhetoric + sanctions + military posture all elevated" if us_pressure >= 4 else "elevated but below confrontation threshold"}. '
            f'Government L{us_gov}, sanctions L{us_sanc}, military L{us_mil}.'
        )

    # Q2: Regime fracture
    if regime_fracture >= 1 or cu_diss >= 2:
        situation_parts.append(
            f'Regime fracture vector at L{regime_fracture}: '
            f'dissident activity L{cu_diss}, security apparatus L{cu_mil}. '
            f'{"Dissident signal significantly exceeds suppression capacity -- pre-crisis pattern." if regime_fracture >= 3 else "Regime appears to be containing pressure."}'
        )

    # Q3: Adversary exploitation
    if adversary_access >= 2:
        active = []
        if ru_axis >= 3: active.append(f'Russia (L{ru_axis})')
        if cn_axis >= 3: active.append(f'China (L{cn_axis})')
        if ir_axis >= 3: active.append(f'Iran (L{ir_axis})')
        situation_parts.append(
            f'Adversary exploitation at L{adversary_access}: '
            f'{"multi-power access signals -- " + ", ".join(active) if active else "single-power access signal"}. '
            f'Watch for cross-reinforcement across Russia-China-Iran axis fingerprints.'
        )

    # ── Indicators (red lines status, historical matches) ──
    indicators = []
    for rl in red_lines_triggered:
        if rl.get('status') == 'BREACHED':
            indicators.append({'icon': '🔴', 'text': f"RED LINE BREACHED: {rl.get('label', '')}"})
        elif rl.get('status') == 'APPROACHING':
            indicators.append({'icon': '🟠', 'text': f"Approaching: {rl.get('label', '')}"})

    for hm in (historical_matches or [])[:2]:
        indicators.append({
            'icon': '🕰️',
            'text': f"Historical analog: {hm.get('label', '')} ({hm.get('score', 0)}% pattern match)",
        })

    # ── Assessment (analytical summary) ──
    if breached_count >= 2:
        assessment = (
            'Cuba is in a multi-breach scenario. Rapid escalation is possible. '
            'Monitor WHA backend for migration surge signal propagation and US policy '
            'response window. Cross-theater spillover (Mexico, Venezuela, Colombia) '
            'warrants elevated watch.'
        )
    elif breached_count >= 1:
        assessment = (
            'One red line breached. Cuba has crossed a single-category threshold. '
            'Adjacent categories warrant elevated monitoring for convergence.'
        )
    elif us_pressure >= 3 and regime_fracture >= 2:
        assessment = (
            'US pressure and regime fracture rising in tandem. Classic pre-crisis pattern -- '
            'historically preceded 1980 Mariel and 1994 Balsero episodes.'
        )
    elif adversary_access >= 3 and us_pressure >= 2:
        assessment = (
            'Adversary access rising under US pressure. Classic compensation pattern -- '
            'Havana turns to Moscow/Beijing/Tehran when Washington squeezes. '
            'Watch for Lourdes / Mariel / Iranian tanker convergence.'
        )
    elif regime_fracture >= 3:
        assessment = (
            'Regime fracture signal leading. Dissident activity exceeds suppression capacity. '
            '11J (July 2021) pattern warrants close watch -- spontaneous nationwide '
            'mobilization is plausible.'
        )
    elif us_pressure >= 3:
        assessment = (
            'US pressure leading but Cuban regime not yet visibly cracking. '
            'Monitor for lagging regime response signals in next 2-4 weeks.'
        )
    else:
        assessment = 'Cuba below convergence threshold. Routine monitoring mode.'

    # ── Watch list (next 7-14 days) ──
    watch_list = []
    if regime_fracture >= 2:
        watch_list.append('Protest activity in Havana / Santiago -- dissident momentum signals')
    if us_mil >= 2:
        watch_list.append('SOUTHCOM exercise schedule -- Caribbean posture tempo')
    if us_sanc >= 2:
        watch_list.append('OFAC Recent Actions page -- new designations or SDN list adds')
    if ru_axis >= 2:
        watch_list.append('Russian tanker / warship movements toward Caribbean')
    if cn_axis >= 2:
        watch_list.append('Mariel port traffic -- PLAN vessel tracking')
    if ir_axis >= 2:
        watch_list.append('Iranian sanctioned tanker destinations -- AIS transponder data')
    if us_pressure >= 2:
        watch_list.append('White House Latin America policy announcements')
    if cu_diss >= 2:
        watch_list.append('14ymedio / Diario de Cuba reporting tempo -- dissident arrest tracking')

    if not watch_list:
        watch_list.append('Routine monitoring -- no elevated-attention signals')

    return {
        'scenario':         scenario,
        'scenario_color':   scenario_color,
        'scenario_icon':    scenario_icon,
        'situation':        ' '.join(situation_parts) if situation_parts else 'All three vectors below monitoring threshold. Cuba in baseline rhetorical posture.',
        'indicators':       indicators,
        'assessment':       assessment,
        'watch_list':       watch_list,
        # Vector readout for frontend card
        'us_pressure':      us_pressure,
        'regime_fracture':  regime_fracture,
        'adversary_access': adversary_access,
        # Historical context
        'historical_matches': historical_matches or [],
        'confidence_note':  'Analysis based on OSINT signal aggregation. Does not reflect classified '
                            'intelligence. Three-question analytical frame is Asifah-specific '
                            'methodology and should not be cited as official assessment.',
    }


# ============================================================
# TOP-LEVEL INTERPRETER
# ============================================================
def interpret_signals(scan_data):
    """
    Convenience wrapper: given scan_data, returns {'red_lines': [...], 'so_what': {...}}.
    Used directly when signal_interpreter is called from outside the tracker.
    """
    actor_results = scan_data.get('actors', {})
    articles = scan_data.get('articles', [])

    red_lines_triggered = check_red_lines(articles, actor_results)
    vectors = {
        'us_pressure':      scan_data.get('us_pressure', 0),
        'regime_fracture':  scan_data.get('regime_fracture', 0),
        'adversary_access': scan_data.get('adversary_access', 0),
    }
    historical_matches = build_historical_matches(actor_results, vectors)
    so_what = build_so_what(scan_data, red_lines_triggered, historical_matches)

    return {
        'red_lines':          red_lines_triggered,
        'so_what':            so_what,
        'historical_matches': historical_matches,
    }


# ============================================================
# v2.0+ — TOP SIGNALS (BLUF / GPI consumable)
# ============================================================
# Emits a pre-prioritized list of signal dicts that the WHA Regional BLUF
# (and ultimately the Global Pressure Index) consume directly.
#
# Cuba-specific categories:
#   red_line_breached, theatre_high, us_pressure_high, regime_fracture,
#   adversary_access, migration_surge, dissident_anomaly, off_ramp_active

CUBA_FLAG = '\U0001f1e8\U0001f1fa'  # 🇨🇺

def build_top_signals(scan_data):
    """
    Build Cuba's top_signals[] for BLUF/GPI consumption.
    Reads from scan_data dict (post-interpret_signals output).
    Returns sorted list (descending priority).
    """
    signals = []

    actor_results = scan_data.get('actors', {}) or {}
    so_what       = scan_data.get('so_what', {}) or {}
    red_lines     = scan_data.get('red_lines', []) or []

    overall_level = scan_data.get('overall_level',
                    scan_data.get('theatre_level', 0)) or 0
    overall_score = scan_data.get('theatre_score',
                    scan_data.get('overall_score', 0)) or 0

    # Cuba's three vectors from so_what
    us_pressure      = so_what.get('us_pressure', 0) or 0
    regime_fracture  = so_what.get('regime_fracture', 0) or 0
    adversary_access = so_what.get('adversary_access', 0) or 0

    # Actor-specific levels (9 actors in Cuba)
    us_gov_lvl       = actor_results.get('us_government',          {}).get('escalation_level', 0) or 0
    us_sanc_lvl      = actor_results.get('us_sanctions_regulatory', {}).get('escalation_level', 0) or 0
    us_mil_lvl       = actor_results.get('us_military_posture',    {}).get('escalation_level', 0) or 0
    cuban_gov_lvl    = actor_results.get('cuban_government',       {}).get('escalation_level', 0) or 0
    cuban_mil_lvl    = actor_results.get('cuban_military_security', {}).get('escalation_level', 0) or 0
    dissident_lvl    = actor_results.get('cuban_dissidents',       {}).get('escalation_level', 0) or 0
    russia_axis_lvl  = actor_results.get('russia_cuba_axis',       {}).get('escalation_level', 0) or 0
    china_axis_lvl   = actor_results.get('china_cuba_axis',        {}).get('escalation_level', 0) or 0
    iran_axis_lvl    = actor_results.get('iran_cuba_axis',         {}).get('escalation_level', 0) or 0

    # ============================================
    # 1. RED LINES BREACHED
    # ============================================
    for rl in red_lines:
        if not isinstance(rl, dict): continue
        status = rl.get('status', '')
        label  = rl.get('label', 'Red line')
        if status == 'BREACHED':
            signals.append({
                'priority':   12,
                'category':   'red_line_breached',
                'theatre':    'cuba',
                'level':      overall_level,
                'icon':       rl.get('icon', '🚨'),
                'color':      '#dc2626',
                'short_text': f'{CUBA_FLAG} CUBA: BREACH — {label[:55]}',
                'long_text':  f'CUBA red line breached at L{overall_level}: {label}.',
            })
        elif status == 'APPROACHING':
            signals.append({
                'priority':   8,
                'category':   'red_line_approaching',
                'theatre':    'cuba',
                'level':      overall_level,
                'icon':       '🟠',
                'color':      '#f97316',
                'short_text': f'{CUBA_FLAG} CUBA: Approaching — {label[:50]}',
                'long_text':  f'CUBA approaching red line: {label}.',
            })

    # ============================================
    # 2. THEATRE-HIGH (overall L4+)
    # ============================================
    if overall_level >= 4:
        signals.append({
            'priority':   9 + overall_level,
            'category':   'theatre_high',
            'theatre':    'cuba',
            'level':      overall_level,
            'icon':       '🔴',
            'color':      '#dc2626' if overall_level >= 5 else '#ef4444',
            'short_text': f'{CUBA_FLAG} CUBA L{overall_level} — Pressure cascade',
            'long_text':  f'CUBA at L{overall_level} composite pressure (score {overall_score}/100). '
                          f'US-Cuba friction with regime/adversary cross-cutting signals.',
        })

    # ============================================
    # 3. U.S. PRESSURE VECTOR (Q1 in Cuba's three-question frame)
    # ============================================
    if us_pressure >= 4:
        signals.append({
            'priority':   10,
            'category':   'us_pressure_high',
            'theatre':    'cuba',
            'level':      us_pressure,
            'icon':       '🦅',
            'color':      '#dc2626',
            'short_text': f'{CUBA_FLAG} CUBA: US pressure L{us_pressure}',
            'long_text':  f'CUBA U.S. pressure vector L{us_pressure} — coercion-to-action transition. '
                          f'Gov L{us_gov_lvl}, sanctions L{us_sanc_lvl}, military L{us_mil_lvl}.',
        })
    elif us_pressure >= 3:
        signals.append({
            'priority':   7,
            'category':   'us_pressure_high',
            'theatre':    'cuba',
            'level':      us_pressure,
            'icon':       '🦅',
            'color':      '#f97316',
            'short_text': f'{CUBA_FLAG} CUBA: US pressure L{us_pressure}',
            'long_text':  f'CUBA U.S. pressure L{us_pressure} — direct threat language; named action signals.',
        })

    # ============================================
    # 4. REGIME FRACTURE VECTOR (Q2)
    # ============================================
    if regime_fracture >= 4:
        signals.append({
            'priority':   10,
            'category':   'regime_fracture',
            'theatre':    'cuba',
            'level':      regime_fracture,
            'icon':       '✊',
            'color':      '#dc2626',
            'short_text': f'{CUBA_FLAG} CUBA: Regime fracture L{regime_fracture}',
            'long_text':  f'CUBA regime fracture L{regime_fracture} — dissident L{dissident_lvl}, '
                          f'security L{cuban_mil_lvl}; G2 suppression breaking down.',
        })
    elif regime_fracture >= 3:
        signals.append({
            'priority':   7,
            'category':   'regime_fracture',
            'theatre':    'cuba',
            'level':      regime_fracture,
            'icon':       '✊',
            'color':      '#f97316',
            'short_text': f'{CUBA_FLAG} CUBA: Regime fracture L{regime_fracture}',
            'long_text':  f'CUBA regime fracture signals L{regime_fracture} — dissident activity rising vs. baseline.',
        })

    # ============================================
    # 5. ADVERSARY ACCESS VECTOR (Q3 — RU/CN/IR)
    # ============================================
    if adversary_access >= 4:
        signals.append({
            'priority':   11,
            'category':   'adversary_access',
            'theatre':    'cuba',
            'level':      adversary_access,
            'icon':       '🤝',
            'color':      '#dc2626',
            'short_text': f'{CUBA_FLAG} CUBA: Adversary access L{adversary_access}',
            'long_text':  f'CUBA adversary access L{adversary_access} — RU L{russia_axis_lvl}, '
                          f'CN L{china_axis_lvl}, IR L{iran_axis_lvl}; SIGINT/port/oil channels active.',
        })
    elif adversary_access >= 3:
        signals.append({
            'priority':   8,
            'category':   'adversary_access',
            'theatre':    'cuba',
            'level':      adversary_access,
            'icon':       '🤝',
            'color':      '#f97316',
            'short_text': f'{CUBA_FLAG} CUBA: Adversary access L{adversary_access}',
            'long_text':  f'CUBA adversary access L{adversary_access} — multiple axis activity detected.',
        })

    # ============================================
    # 6. AXIS-SPECIFIC HIGH (RU / CN / IR individually)
    # ============================================
    if russia_axis_lvl >= 4:
        signals.append({
            'priority':   9,
            'category':   'russia_axis_high',
            'theatre':    'cuba',
            'level':      russia_axis_lvl,
            'icon':       '🇷🇺',
            'color':      '#7c3aed',
            'short_text': f'{CUBA_FLAG} CUBA: Russia-Cuba axis L{russia_axis_lvl}',
            'long_text':  f'CUBA: Russia-Cuba axis L{russia_axis_lvl} — port visits, SIGINT, or strategic delegation activity.',
        })
    if china_axis_lvl >= 4:
        signals.append({
            'priority':   9,
            'category':   'china_axis_high',
            'theatre':    'cuba',
            'level':      china_axis_lvl,
            'icon':       '🇨🇳',
            'color':      '#7c3aed',
            'short_text': f'{CUBA_FLAG} CUBA: China-Cuba axis L{china_axis_lvl}',
            'long_text':  f'CUBA: China-Cuba axis L{china_axis_lvl} — SIGINT facility activity or PLA Navy port visits.',
        })
    if iran_axis_lvl >= 4:
        signals.append({
            'priority':   9,
            'category':   'iran_axis_high',
            'theatre':    'cuba',
            'level':      iran_axis_lvl,
            'icon':       '🇮🇷',
            'color':      '#7c3aed',
            'short_text': f'{CUBA_FLAG} CUBA: Iran-Cuba axis L{iran_axis_lvl}',
            'long_text':  f'CUBA: Iran-Cuba axis L{iran_axis_lvl} — IRGC delegation or oil tanker activity.',
        })

    # ============================================
    # 7. MIGRATION SURGE (cross-theater fingerprint Cuba writes)
    # ============================================
    migration_surge = scan_data.get('migration_surge', 0) or 0
    if migration_surge >= 3 or (dissident_lvl >= 3 and us_mil_lvl >= 2):
        effective_level = max(migration_surge, 3)
        signals.append({
            'priority':   8,
            'category':   'migration_surge',
            'theatre':    'cuba',
            'level':      effective_level,
            'icon':       '🌊',
            'color':      '#0ea5e9',
            'short_text': f'{CUBA_FLAG} CUBA: Migration surge signal L{effective_level}',
            'long_text':  f'CUBA migration surge indicators L{effective_level} — dissident pressure plus '
                          f'US military posture suggests outflow risk; WHA cascade fingerprint active.',
        })

    # ============================================
    # 8. OFF-RAMP / DE-ESCALATION (positive)
    # ============================================
    off_ramp_active = so_what.get('off_ramp_active', False)
    if off_ramp_active:
        signals.append({
            'priority':   6,
            'category':   'off_ramp_active',
            'theatre':    'cuba',
            'level':      max(0, overall_level - 1),
            'icon':       '🕊️',
            'color':      '#10b981',
            'short_text': f'{CUBA_FLAG} CUBA: Off-ramp signals',
            'long_text':  f'CUBA off-ramp / de-escalation language detected — diplomatic backchannel or sanctions relief signaling.',
        })

    # Sort descending; BLUF will dedupe + globally rank
    signals.sort(key=lambda s: s['priority'], reverse=True)
    return signals
