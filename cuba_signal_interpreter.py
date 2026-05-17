"""
cuba_signal_interpreter.py
Asifah Analytics -- WHA Backend Module
v1.1.0 -- May 17, 2026

Signal interpretation engine for the Cuba Rhetoric Tracker.

v1.1 adds the COALITION THREAT FRAMEWORK — recognizing when Russia + Iran +
China are forward-staging asymmetric strike capability into Cuba as a coalition,
explicitly naming the October 1962 missile crisis as the historical doctrinal
analog.

Cuba's analytical frame is now FOUR questions answered simultaneously:

  1. Is the U.S. escalating from rhetoric to coercion to unilateral action?
     How far is Washington actually willing to go -- and what's the trigger?

  2. Is the Cuban regime stabilizing or fracturing under that pressure?
     Is G2 suppression holding? Are dissident signals rising? Is economic
     collapse accelerating regime brittleness?

  3. Are Russia / China / Iran exploiting the friction to gain access?
     (Lourdes SIGINT, Mariel port visits, Iranian tankers, IRGC delegations)

  4. [v1.1] Are Russia + Iran + China operating as a COALITION to forward-stage
     asymmetric strike capability 90 miles from US territory?
     This is the 1962 Cuban Missile Crisis pattern in 21st-century form —
     drones instead of MRBMs, multilateral instead of bilateral, but
     structurally identical: hostile-state-coalition kinetic-capability
     staging in the Western Hemisphere.

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

    # ── Category D [v1.1]: COALITION KINETIC THREAT ────────────
    # The 1962 Cuban Missile Crisis pattern in 21st-century form.
    # When 2+ adversaries forward-stage weapons in Cuba, the threat is
    # qualitatively different from individual access signals.
    {
        'id':       'adversary_weapons_staging_cuba',
        'label':    'Adversary Coalition Weapons Staging in Cuba (1962 Pattern)',
        'detail':   'Two or more of {Russia, Iran, China} transferring kinetic-strike weapons '
                    '(drones, missiles, advanced systems) to Cuba within a 30-day window -- '
                    'consistent with hostile-state-coalition forward-deployment doctrine. '
                    'Historically analogous to October 1962 Cuban Missile Crisis structure.',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🚀',
        'category': 'coalition_threat',
        'source':   'Forward-staged adversary strike capability 90 miles from US territory '
                    'is the canonical Western Hemisphere security trigger. The 1962 precedent '
                    'culminated in 13 days of confrontation that nearly produced nuclear war. '
                    'Multilateral staging (RU+IR) increases ambiguity and reduces deterrence '
                    'clarity vs the bilateral 1962 case.',
    },
    {
        'id':       'kinetic_precursor_cadence_cuba',
        'label':    'Coordinated US Escalation Cadence Against Cuba (Venezuela 2026 Pattern)',
        'detail':   'Three or more of {senior US intelligence official Havana visit, DOJ '
                    'indictment of senior Cuban official, Sec-Def/State congressional warning, '
                    'public disclosure of Cuban kinetic capability, "pretext for military '
                    'action" language by US officials} within a 14-day window. Cadence '
                    'consistent with executive-branch sequencing toward kinetic action.',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '⏱️',
        'category': 'us_escalation',
        'source':   'The Venezuela January 2026 raid was preceded by a 21-day escalation '
                    'cadence with this signature: intel-disclosure, DOJ indictment, '
                    'congressional posture-setting, then unilateral action. When the same '
                    'cadence repeats against another Western Hemisphere target, it is the '
                    'highest-confidence pre-kinetic indicator available via OSINT.',
    },
    {
        'id':       'iran_advisor_presence_cuba',
        'label':    'Iranian Military Advisers Deployed in Cuba',
        'detail':   'IRGC, Quds Force, or Iranian military trainers detected in Cuba; or '
                    'Cuban officials publicly stating they are "learning Iranian tactics" '
                    'for asymmetric resistance to US pressure.',
        'severity': 2,
        'color':    '#ef4444',
        'icon':     '🎓',
        'category': 'coalition_threat',
        'source':   'Iranian asymmetric warfare doctrine transfer to Western Hemisphere is a '
                    'qualitatively new development -- Iran has historically projected via proxy '
                    '(Hezbollah, Houthis) rather than direct military advisers. Adviser '
                    'presence indicates state-to-state coordination, not proxy improvisation.',
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


def _check_coalition_weapons_staging(articles, actor_results):
    """
    v1.1 — Detect multi-adversary weapons-staging pattern (1962 analog).

    Returns True if 2+ adversaries show weapons-transfer signals to Cuba
    within the current scan window.
    """
    # Russia → Cuba weapons signals
    ru_axis = actor_results.get('russia_cuba_axis', {})
    ru_keywords_matched = ru_axis.get('keywords_matched', []) or []
    russia_weapons = any(
        any(term in str(kw).lower() for term in (
            'drone transfer', 'drone shipment', 'drone supply',
            'weapons transfer', 'military equipment', 'geran',
            'drone pipeline', 'drones to cuba', 'drone agreement'
        ))
        for kw in ru_keywords_matched
    )

    # Iran → Cuba weapons signals
    ir_axis = actor_results.get('iran_cuba_axis', {})
    ir_keywords_matched = ir_axis.get('keywords_matched', []) or []
    iran_weapons = any(
        any(term in str(kw).lower() for term in (
            'shahed cuba', 'mohajer cuba', 'drone transfer', 'drone shipment',
            'drones to cuba', 'weapons transfer', 'military equipment',
            'drone pipeline'
        ))
        for kw in ir_keywords_matched
    )

    # China → Cuba weapons signals (less likely, but track)
    cn_axis = actor_results.get('china_cuba_axis', {})
    cn_keywords_matched = cn_axis.get('keywords_matched', []) or []
    china_weapons = any(
        any(term in str(kw).lower() for term in (
            'weapons transfer', 'military equipment', 'arms cuba',
            'china military cuba'
        ))
        for kw in cn_keywords_matched
    )

    # Article-level fallback (in case keywords_matched isn't populated)
    if not (russia_weapons or iran_weapons or china_weapons):
        for art in (articles or []):
            text = (art.get('title', '') + ' ' + art.get('snippet', '')).lower()
            if 'cuba' in text and ('300 drones' in text or 'drones from russia' in text or 'drones from iran' in text):
                # If article mentions Cuba + drones from RU/IR, count as both
                if 'russia' in text:
                    russia_weapons = True
                if 'iran' in text:
                    iran_weapons = True

    adversary_count = int(russia_weapons) + int(iran_weapons) + int(china_weapons)
    return {
        'triggered':        adversary_count >= 2,
        'adversary_count':  adversary_count,
        'russia':           russia_weapons,
        'iran':             iran_weapons,
        'china':            china_weapons,
    }


def _check_kinetic_precursor_cadence(articles, actor_results):
    """
    v1.1 — Detect Venezuela-2026-pattern US escalation cadence against Cuba.

    Returns True if 3+ of the precursor indicators are present in the scan.
    """
    us_mil = actor_results.get('us_military_posture', {})
    us_gov = actor_results.get('us_government', {})
    us_sanc = actor_results.get('us_sanctions_regulatory', {})

    # Aggregate keywords from US actors
    all_us_kw = []
    for a in (us_mil, us_gov, us_sanc):
        all_us_kw.extend(a.get('keywords_matched', []) or [])
    all_us_kw_str = ' '.join(str(k).lower() for k in all_us_kw)

    indicators = {
        'cia_havana_visit':       'ratcliffe' in all_us_kw_str or 'cia director' in all_us_kw_str,
        'doj_indictment':         'castro indictment' in all_us_kw_str or 'brothers to the rescue' in all_us_kw_str or 'doj indictment castro' in all_us_kw_str,
        'congressional_warning':  'hegseth cuba' in all_us_kw_str or 'diaz-balart cuba' in all_us_kw_str,
        'capability_disclosure':  'cuba 300 drones' in all_us_kw_str or 'cuba drone threat' in all_us_kw_str or 'cuba military drones' in all_us_kw_str,
        'pretext_language':       'pretext for military action' in all_us_kw_str or 'pretext military action' in all_us_kw_str,
    }

    # Article-level fallback
    if sum(indicators.values()) < 3:
        for art in (articles or []):
            text = (art.get('title', '') + ' ' + art.get('snippet', '')).lower()
            if 'cuba' not in text:
                continue
            if 'ratcliffe' in text or 'cia director' in text and 'havana' in text:
                indicators['cia_havana_visit'] = True
            if 'castro' in text and 'indictment' in text:
                indicators['doj_indictment'] = True
            if 'hegseth' in text or 'diaz-balart' in text:
                indicators['congressional_warning'] = True
            if '300 drones' in text or 'drone threat' in text:
                indicators['capability_disclosure'] = True
            if 'pretext' in text and ('military action' in text or 'strike' in text):
                indicators['pretext_language'] = True

    indicator_count = sum(indicators.values())
    return {
        'triggered':        indicator_count >= 3,
        'indicator_count':  indicator_count,
        'indicators':       indicators,
    }


def _check_iran_advisor_presence(articles, actor_results):
    """v1.1 — Detect Iranian military adviser presence in Cuba."""
    ir_axis = actor_results.get('iran_cuba_axis', {})
    ir_kw = ir_axis.get('keywords_matched', []) or []
    ir_kw_str = ' '.join(str(k).lower() for k in ir_kw)

    advisor_signal = (
        'iranian military advisers cuba' in ir_kw_str or
        'iranian advisers havana' in ir_kw_str or
        'irgc advisers cuba' in ir_kw_str or
        'iran drone trainers cuba' in ir_kw_str or
        'cuba learning iran tactics' in ir_kw_str
    )

    if not advisor_signal:
        for art in (articles or []):
            text = (art.get('title', '') + ' ' + art.get('snippet', '')).lower()
            if 'cuba' in text and 'iranian' in text and ('advis' in text or 'trainer' in text or 'engineer' in text):
                advisor_signal = True
                break

    return advisor_signal


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

    # ─── v1.1 COALITION THREAT EVALUATIONS ──────────────────
    # adversary_weapons_staging_cuba (the 1962 pattern)
    staging_check = _check_coalition_weapons_staging(articles, actor_results)
    if staging_check['triggered']:
        rl = _rl('adversary_weapons_staging_cuba')
        if rl:
            adversaries = []
            if staging_check['russia']: adversaries.append('Russia')
            if staging_check['iran']:   adversaries.append('Iran')
            if staging_check['china']:  adversaries.append('China')
            triggered.append({
                **rl,
                'status':   'BREACHED',
                'evidence': f"Weapons-transfer signals detected from {' + '.join(adversaries)} ({staging_check['adversary_count']} adversaries). 1962 Cuban Missile Crisis structural analog -- multilateral hostile-state coalition forward-staging strike capability 90 miles from US territory.",
            })

    # kinetic_precursor_cadence_cuba (the VZ 2026 pattern)
    cadence_check = _check_kinetic_precursor_cadence(articles, actor_results)
    if cadence_check['triggered']:
        rl = _rl('kinetic_precursor_cadence_cuba')
        if rl:
            active_indicators = [k.replace('_', ' ').title() for k, v in cadence_check['indicators'].items() if v]
            triggered.append({
                **rl,
                'status':   'BREACHED',
                'evidence': f"{cadence_check['indicator_count']} kinetic-precursor indicators active: {', '.join(active_indicators)}. Venezuela January 2026 precedent -- this cadence preceded the US raid by 21 days.",
            })
    elif cadence_check['indicator_count'] >= 2:
        rl = _rl('kinetic_precursor_cadence_cuba')
        if rl:
            active_indicators = [k.replace('_', ' ').title() for k, v in cadence_check['indicators'].items() if v]
            triggered.append({
                **rl,
                'status':   'APPROACHING',
                'evidence': f"{cadence_check['indicator_count']} of 3 required indicators active: {', '.join(active_indicators)}. Approaching VZ 2026 escalation-cadence threshold.",
            })

    # iran_advisor_presence_cuba
    if _check_iran_advisor_presence(articles, actor_results):
        rl = _rl('iran_advisor_presence_cuba')
        if rl:
            triggered.append({
                **rl,
                'status':   'BREACHED',
                'evidence': 'Iranian military adviser/trainer presence in Cuba detected. Direct state-to-state military doctrine transfer (not proxy improvisation) -- qualitatively new pattern for Iran in Western Hemisphere.',
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

    # ── v1.1 FOURTH VECTOR: coalition_threat ─────────────────────
    # Triggered when red-line evaluation has fired one or more Cat-D coalition
    # threat red lines. This vector explicitly recognizes the cross-platform
    # adversary-coalition pattern that individual axis vectors miss.
    coalition_red_lines = [r for r in red_lines_triggered
                            if r.get('category') == 'coalition_threat'
                            and r.get('status') == 'BREACHED']
    cadence_breached = any(r.get('id') == 'kinetic_precursor_cadence_cuba'
                           and r.get('status') == 'BREACHED' for r in red_lines_triggered)
    staging_breached = any(r.get('id') == 'adversary_weapons_staging_cuba'
                           and r.get('status') == 'BREACHED' for r in red_lines_triggered)

    if staging_breached and cadence_breached:
        coalition_threat = 5  # 1962-pattern + VZ 2026 cadence = pre-kinetic
    elif staging_breached:
        coalition_threat = 4  # weapons staged but escalation cadence not yet
    elif cadence_breached:
        coalition_threat = 4  # cadence firing but weapons not yet confirmed
    elif len(coalition_red_lines) >= 1:
        coalition_threat = 3  # Iran advisers or partial coalition signal
    elif (ru_axis >= 3 and ir_axis >= 3) or (ru_axis >= 3 and cn_axis >= 3) or (ir_axis >= 3 and cn_axis >= 3):
        coalition_threat = 2  # multi-axis activity even without red-line breach
    else:
        coalition_threat = 0

    breached_count    = sum(1 for r in red_lines_triggered if r.get('status') == 'BREACHED')
    approaching_count = sum(1 for r in red_lines_triggered if r.get('status') == 'APPROACHING')

    # ── Scenario label (v1.1: coalition_threat = 5 overrides everything) ──
    if coalition_threat >= 5:
        scenario       = 'PRE-KINETIC -- 1962 Pattern + VZ 2026 Cadence Both Active'
        scenario_color = '#7c0a02'  # deeper red
        scenario_icon  = '🚨'
    elif coalition_threat >= 4 or breached_count >= 2 or us_mil >= 5:
        scenario       = 'CRITICAL -- Coalition Weapons Staging OR Multiple Red Lines Breached'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif coalition_threat >= 3 or breached_count >= 1 or us_pressure >= 4:
        scenario       = 'ELEVATED -- Coalition Threat Forming OR Red Line Breached'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif us_pressure >= 3 or regime_fracture >= 3 or adversary_access >= 3 or coalition_threat >= 2:
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

    # Q4 [v1.1]: COALITION THREAT — the 1962 doctrinal frame
    if coalition_threat >= 3:
        if staging_breached and cadence_breached:
            situation_parts.append(
                f'COALITION THREAT at L{coalition_threat} (PRE-KINETIC): Russia + Iran weapons '
                f'staging in Cuba CONFIRMED concurrent with US executive escalation cadence '
                f'matching Venezuela January 2026 pattern. Doctrinal analog is October 1962 '
                f'Cuban Missile Crisis -- hostile state coalition forward-deploying asymmetric '
                f'strike capability 90 miles from US territory during a moment of regime '
                f'brittleness, with US executive sequencing toward kinetic response. The 1962 '
                f'precedent culminated in 13 days that nearly produced nuclear war.'
            )
        elif staging_breached:
            situation_parts.append(
                f'COALITION THREAT at L{coalition_threat}: Adversary weapons staging detected '
                f'(1962 pattern). Russia and/or Iran transferring kinetic-strike capability '
                f'to Cuba. US response cadence not yet at VZ 2026 threshold but watch for '
                f'rapid sequencing: intel disclosure, DOJ action, Sec-Def posturing.'
            )
        elif cadence_breached:
            situation_parts.append(
                f'COALITION THREAT at L{coalition_threat}: US executive escalation cadence '
                f'against Cuba matches Venezuela January 2026 pre-kinetic pattern. Multiple '
                f'sequencing indicators active (intel, DOJ, congressional). Watch for '
                f'public threshold-crossing language from White House or Defense.'
            )
        else:
            situation_parts.append(
                f'COALITION THREAT at L{coalition_threat}: Cross-platform coordination signals '
                f'(Iranian advisers, multi-axis activity) below 1962-pattern threshold but '
                f'warrant elevated watch for weapons-transfer or US-cadence escalation.'
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

    # ── v1.1 add coalition_threat watch items ───────────────────
    if coalition_threat >= 4:
        watch_list.append('🚨 COALITION THREAT WATCH: Mariel/Cienfuegos port activity (weapons cargo)')
        watch_list.append('🚨 COALITION THREAT WATCH: GTMO reinforcement signals / SOUTHCOM exercise tempo surge')
        watch_list.append('🚨 COALITION THREAT WATCH: White House press cycle on Cuba (1962 culminated in primetime address)')
    elif coalition_threat >= 3:
        watch_list.append('Coalition watch: Russian + Iranian cargo aircraft routing toward Caribbean')
        watch_list.append('Coalition watch: Cuban defense reorganization announcements')

    if not watch_list:
        watch_list.append('Routine monitoring -- no elevated-attention signals')

    # ── v1.1 doctrine assessment (override base assessment if coalition_threat severe) ──
    if coalition_threat >= 5:
        doctrine_assessment = (
            'DOCTRINAL ASSESSMENT: This pattern matches the October 1962 Cuban Missile Crisis '
            'structurally. The differences are MULTILATERAL (RU+IR vs sole USSR), TACTICAL '
            '(drones vs MRBMs), and AMBIGUOUS (denial-capable rather than public). The '
            'similarities are GEOGRAPHIC (90 miles from US territory), DEPLOYMENT-PATTERN '
            '(forward-staged kinetic capability), and CADENCE (US executive sequencing toward '
            'kinetic response). The 1962 precedent reached 13 days of confrontation and risked '
            'nuclear war. The 2026 case adds Venezuela 2026 as the just-occurred regime-change '
            'precedent demonstrating US willingness to use unilateral force in the hemisphere. '
            'Analytical recommendation: treat as PRE-KINETIC. Monitor White House / DoD for '
            'public threshold-crossing statements within 7-14 days.'
        )
        assessment = doctrine_assessment + ' ' + assessment
    elif coalition_threat >= 4:
        doctrine_assessment = (
            'DOCTRINAL ASSESSMENT: Coalition weapons-staging pattern detected (1962 structural '
            'analog) OR US executive cadence matching Venezuela January 2026 pre-kinetic '
            'sequencing. Either condition warrants treatment as ELEVATED Western Hemisphere '
            'security trigger. When both fire simultaneously, scenario upgrades to PRE-KINETIC.'
        )
        assessment = doctrine_assessment + ' ' + assessment

    return {
        'scenario':         scenario,
        'scenario_color':   scenario_color,
        'scenario_icon':    scenario_icon,
        'situation':        ' '.join(situation_parts) if situation_parts else 'All four vectors below monitoring threshold. Cuba in baseline rhetorical posture.',
        'indicators':       indicators,
        'assessment':       assessment,
        'watch_list':       watch_list,
        # Vector readout for frontend card (v1.1: 4 vectors now)
        'us_pressure':      us_pressure,
        'regime_fracture':  regime_fracture,
        'adversary_access': adversary_access,
        'coalition_threat': coalition_threat,  # NEW v1.1
        # v1.1 doctrine flags for frontend
        'doctrine_1962_pattern':       staging_breached,
        'doctrine_vz2026_cadence':     cadence_breached,
        'doctrine_pre_kinetic':        staging_breached and cadence_breached,
        # Historical context
        'historical_matches': historical_matches or [],
        'confidence_note':  'Analysis based on OSINT signal aggregation. Does not reflect classified '
                            'intelligence. Four-question analytical frame (v1.1) is Asifah-specific '
                            'methodology and should not be cited as official assessment. The 1962 '
                            'historical analog is structural pattern recognition, not prediction.',
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
        # v1.1 coalition_threat computed inside build_so_what; surfaced in return
    }
    historical_matches = build_historical_matches(actor_results, vectors)
    so_what = build_so_what(scan_data, red_lines_triggered, historical_matches)

    return {
        'red_lines':          red_lines_triggered,
        'so_what':            so_what,
        'historical_matches': historical_matches,
    }
