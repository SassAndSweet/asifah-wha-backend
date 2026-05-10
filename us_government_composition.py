"""
Asifah Analytics — U.S. Government Composition v1.0.0
May 11, 2026

Single source of truth for U.S. federal government composition + election
cycle awareness. Consumed by:
  - us_stability.py (structural friction baselines)
  - rhetoric_tracker_us.py (actor identification)
  - us-stability.html (display)

ARCHITECTURE (3 data layers, cascading fallback):
  1. Live Congress.gov API     — primary source, 24h cache
  2. Cached data (Upstash)     — last successful live fetch
  3. Static fallback data      — accurate as of May 11, 2026

Each layer is independently functional. If all three fail, an error is
returned but the module never crashes a consumer.

WHY THIS EXISTS:
The U.S. midterm elections occur November 3, 2026. Whatever administration
is in power, the House and Senate composition could shift on January 3, 2027
when the new Congress is sworn in. Hardcoding "Republican majority" anywhere
in the platform would create a silent failure mode. Instead, every consumer
of government-composition data reads from THIS module, so when Congress
changes hands, only ONE place needs to know about it (this module's live
fetcher does the work; consumers see the new state automatically).

ELECTION-CYCLE AWARENESS:
The module also tracks where the country is in the election cycle. This
enables `us_stability.py` to apply different scoring profiles for:
  - Regular legislative period (steady-state baseline)
  - Campaign window (heightened rhetoric expected, partisan signals less stress-relevant)
  - Late campaign (Sept-Nov 2026, election integrity signals more weight)
  - Counting / certification window (Nov 3 - Jan 6, 2027 — extreme stress amplifier)
  - Lame duck (post-election to swearing-in, controversial appointments tracked)
  - Transition / inauguration day (Jan 3 swearing-in for Congress)
  - New Congress (post-Jan 3 — composition refreshed, baselines recalibrated)

APOLITICAL BY DESIGN:
This module describes structural facts (who holds majority, when elections
occur, what powers vest where). It contains no political-coloring data.
Same code serves equally well in 2026 (GOP unified) or hypothetical 2027
(divided government). The 5-band scoring rubric in us_stability.py applies
identically regardless of which party holds power.

STATIC FALLBACK DATA — CURRENT AS OF: May 10, 2026
TO UPDATE AFTER NEXT ELECTION (Nov 3, 2026):
  - Update CONGRESS_119_FALLBACK and add CONGRESS_120_FALLBACK
  - Update HOUSE_LEADERSHIP / SENATE_LEADERSHIP if leadership changes
  - Update CABINET_2025 if cabinet changes
  - Static_data_as_of timestamp will auto-update

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta


# ============================================================
# CONFIGURATION
# ============================================================

print("[US Govt Composition] Module loading...")

CONGRESS_API_KEY = os.environ.get('CONGRESS_API_KEY')
CONGRESS_API_BASE = "https://api.congress.gov/v3"

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL') or
                     os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN') or
                       os.environ.get('UPSTASH_REDIS_REST_TOKEN'))

CACHE_KEY = 'us_govt_composition_cache'
CACHE_TTL_SECONDS = 24 * 3600    # 24h
DEFAULT_TIMEOUT = 12

# Static fallback "as of" date — UPDATE WHEN STATIC DATA IS REFRESHED
STATIC_DATA_AS_OF = '2026-05-10'

if CONGRESS_API_KEY:
    print("[US Govt Composition] ✅ Congress.gov API key configured")
else:
    print("[US Govt Composition] ⚠️  CONGRESS_API_KEY missing — static fallback only")


# ============================================================
# STATIC FALLBACK DATA — Current as of STATIC_DATA_AS_OF
# ============================================================
# UPDATE THIS BLOCK AFTER MIDTERM ELECTION RESULTS ARE CERTIFIED
# (typically late Nov / early Dec 2026 for 2026 election results)
# ============================================================

CONGRESS_119_FALLBACK = {
    'number':           119,
    'started':          '2025-01-03',
    'ends':             '2027-01-03',
    'data_as_of':       STATIC_DATA_AS_OF,

    'house': {
        'total_seats':      435,
        'majority_party':   'Republican',
        'majority_size':    220,
        'minority_size':    213,
        'vacant':           2,
        'speaker':          {'name': 'Mike Johnson', 'state': 'LA', 'party': 'R'},
        'majority_leader':  {'name': 'Steve Scalise', 'state': 'LA', 'party': 'R'},
        'minority_leader':  {'name': 'Hakeem Jeffries', 'state': 'NY', 'party': 'D'},
        'majority_whip':    {'name': 'Tom Emmer', 'state': 'MN', 'party': 'R'},
        'minority_whip':    {'name': 'Katherine Clark', 'state': 'MA', 'party': 'D'},
    },

    'senate': {
        'total_seats':      100,
        'majority_party':   'Republican',
        'majority_size':    53,
        'minority_size':    47,
        'majority_leader':  {'name': 'John Thune', 'state': 'SD', 'party': 'R'},
        'minority_leader':  {'name': 'Chuck Schumer', 'state': 'NY', 'party': 'D'},
        'majority_whip':    {'name': 'John Barrasso', 'state': 'WY', 'party': 'R'},
        'minority_whip':    {'name': 'Dick Durbin', 'state': 'IL', 'party': 'D'},
        'pro_tempore':      {'name': 'Chuck Grassley', 'state': 'IA', 'party': 'R'},
    },

    # Key committee chairs (most stability-relevant — Judiciary/Intel/Foreign/Armed/Approp)
    'house_committees': {
        'judiciary':            {'chair': {'name': 'Jim Jordan', 'party': 'R'}},
        'intelligence':         {'chair': {'name': 'Rick Crawford', 'party': 'R'}},
        'foreign_affairs':      {'chair': {'name': 'Brian Mast', 'party': 'R'}},
        'armed_services':       {'chair': {'name': 'Mike Rogers', 'party': 'R'}},
        'appropriations':       {'chair': {'name': 'Tom Cole', 'party': 'R'}},
        'oversight':            {'chair': {'name': 'James Comer', 'party': 'R'}},
        'ways_and_means':       {'chair': {'name': 'Jason Smith', 'party': 'R'}},
    },
    'senate_committees': {
        'judiciary':            {'chair': {'name': 'Chuck Grassley', 'party': 'R'}},
        'intelligence':         {'chair': {'name': 'Tom Cotton', 'party': 'R'}},
        'foreign_relations':    {'chair': {'name': 'Jim Risch', 'party': 'R'}},
        'armed_services':       {'chair': {'name': 'Roger Wicker', 'party': 'R'}},
        'appropriations':       {'chair': {'name': 'Susan Collins', 'party': 'R'}},
        'finance':              {'chair': {'name': 'Mike Crapo', 'party': 'R'}},
        'banking':              {'chair': {'name': 'Tim Scott', 'party': 'R'}},
    },
}

# Executive branch (47th Presidency, 2025-2029)
EXECUTIVE_2025_FALLBACK = {
    'data_as_of':     STATIC_DATA_AS_OF,
    'president':      {'name': 'Donald J. Trump', 'party': 'R',
                       'inauguration': '2025-01-20',
                       'next_inauguration': '2029-01-20'},
    'vice_president': {'name': 'JD Vance', 'state': 'OH', 'party': 'R'},

    # 15 cabinet secretaries + key cabinet-rank positions
    'cabinet': [
        {'role': 'Secretary of State',           'name': 'Marco Rubio',
         'party': 'R', 'department': 'State'},
        {'role': 'Secretary of the Treasury',    'name': 'Scott Bessent',
         'party': 'R', 'department': 'Treasury'},
        {'role': 'Secretary of Defense',         'name': 'Pete Hegseth',
         'party': 'R', 'department': 'Defense'},
        {'role': 'Attorney General',             'name': 'Pam Bondi',
         'party': 'R', 'department': 'Justice'},
        {'role': 'Secretary of the Interior',    'name': 'Doug Burgum',
         'party': 'R', 'department': 'Interior'},
        {'role': 'Secretary of Agriculture',     'name': 'Brooke Rollins',
         'party': 'R', 'department': 'Agriculture'},
        {'role': 'Secretary of Commerce',        'name': 'Howard Lutnick',
         'party': 'R', 'department': 'Commerce'},
        {'role': 'Secretary of Labor',           'name': 'Lori Chavez-DeRemer',
         'party': 'R', 'department': 'Labor'},
        {'role': 'Secretary of Health and Human Services', 'name': 'Robert F. Kennedy Jr.',
         'party': 'R', 'department': 'HHS'},
        {'role': 'Secretary of Housing and Urban Development', 'name': 'Scott Turner',
         'party': 'R', 'department': 'HUD'},
        {'role': 'Secretary of Transportation',  'name': 'Sean Duffy',
         'party': 'R', 'department': 'Transportation'},
        {'role': 'Secretary of Energy',          'name': 'Chris Wright',
         'party': 'R', 'department': 'Energy'},
        {'role': 'Secretary of Education',       'name': 'Linda McMahon',
         'party': 'R', 'department': 'Education'},
        {'role': 'Secretary of Veterans Affairs', 'name': 'Doug Collins',
         'party': 'R', 'department': 'VA'},
        {'role': 'Secretary of Homeland Security', 'name': 'Kristi Noem',
         'party': 'R', 'department': 'DHS'},

        # Cabinet-rank officials beyond the 15 statutory secretaries
        {'role': 'White House Chief of Staff',   'name': 'Susie Wiles',
         'party': 'R', 'department': 'White House'},
        {'role': 'Director of National Intelligence', 'name': 'Tulsi Gabbard',
         'party': 'R', 'department': 'ODNI'},
        {'role': 'Director of CIA',              'name': 'John Ratcliffe',
         'party': 'R', 'department': 'CIA'},
        {'role': 'EPA Administrator',            'name': 'Lee Zeldin',
         'party': 'R', 'department': 'EPA'},
        {'role': 'OMB Director',                 'name': 'Russell Vought',
         'party': 'R', 'department': 'OMB'},
        {'role': 'US Trade Representative',      'name': 'Jamieson Greer',
         'party': 'R', 'department': 'USTR'},
        {'role': 'Ambassador to the UN',         'name': 'Mike Waltz',
         'party': 'R', 'department': 'UN'},
        {'role': 'SBA Administrator',            'name': 'Kelly Loeffler',
         'party': 'R', 'department': 'SBA'},
    ],

    # Independent agency leaders (not cabinet but stability-relevant)
    'independent_agencies': [
        {'role': 'Federal Reserve Chair',        'name': 'Jerome Powell',
         'party': 'Independent', 'term_ends': '2026-05-15',
         'note': 'Chair term ends mid-2026; reappointment/replacement is major signal'},
        {'role': 'Federal Reserve Vice Chair',   'name': 'Philip Jefferson',
         'party': 'Independent'},
        {'role': 'FBI Director',                 'name': 'Kash Patel',
         'party': 'R', 'term_ends': '2035',
         'note': '10-year term; mid-term removal = major institutional signal'},
        {'role': 'FBI Deputy Director',          'name': 'Dan Bongino',
         'party': 'R'},
        {'role': 'SEC Chair',                    'name': 'Paul Atkins',
         'party': 'R'},
        {'role': 'FTC Chair',                    'name': 'Andrew Ferguson',
         'party': 'R'},
        {'role': 'FCC Chair',                    'name': 'Brendan Carr',
         'party': 'R'},
        {'role': 'Solicitor General',            'name': 'D. John Sauer',
         'party': 'R'},
    ],

    # Supreme Court (lifetime appointments — most structurally stable composition)
    'supreme_court': [
        {'role': 'Chief Justice',                'name': 'John Roberts',
         'appointed_by': 'G.W. Bush (R)', 'year': 2005, 'lean': 'C/R'},
        {'role': 'Associate Justice',            'name': 'Clarence Thomas',
         'appointed_by': 'G.H.W. Bush (R)', 'year': 1991, 'lean': 'R'},
        {'role': 'Associate Justice',            'name': 'Samuel Alito',
         'appointed_by': 'G.W. Bush (R)', 'year': 2006, 'lean': 'R'},
        {'role': 'Associate Justice',            'name': 'Sonia Sotomayor',
         'appointed_by': 'Obama (D)', 'year': 2009, 'lean': 'D'},
        {'role': 'Associate Justice',            'name': 'Elena Kagan',
         'appointed_by': 'Obama (D)', 'year': 2010, 'lean': 'D'},
        {'role': 'Associate Justice',            'name': 'Neil Gorsuch',
         'appointed_by': 'Trump (R)', 'year': 2017, 'lean': 'R'},
        {'role': 'Associate Justice',            'name': 'Brett Kavanaugh',
         'appointed_by': 'Trump (R)', 'year': 2018, 'lean': 'R'},
        {'role': 'Associate Justice',            'name': 'Amy Coney Barrett',
         'appointed_by': 'Trump (R)', 'year': 2020, 'lean': 'R'},
        {'role': 'Associate Justice',            'name': 'Ketanji Brown Jackson',
         'appointed_by': 'Biden (D)', 'year': 2022, 'lean': 'D'},
    ],
}


# ============================================================
# ELECTION CYCLE — KEY DATES
# ============================================================
# Key dates for the 2026 cycle and onward. Used to compute current
# cycle phase, days-until-next-election, transition windows.
# ============================================================

ELECTION_CYCLE_DATES = {
    # 2026 midterm cycle
    'midterm_2026': {
        'cycle_name':                 '2026 U.S. Midterm Elections',
        'iowa_caucuses_d':            None,            # No presidential primaries midterm
        'first_primary_date':         '2026-03-03',    # Texas typically first
        'last_primary_date':          '2026-09-08',    # MA, NH, RI, DE typically last
        'general_election_day':       '2026-11-03',
        'state_certification_window': '2026-11-15',    # most states
        'electoral_count':            None,            # midterm has no electoral count
        'congress_120_starts':        '2027-01-03',
        'lame_duck_window_start':     '2026-11-03',
        'lame_duck_window_end':       '2027-01-03',
    },

    # 2028 presidential cycle (anchored)
    'presidential_2028': {
        'cycle_name':                 '2028 U.S. Presidential Election',
        'iowa_caucuses_d':            '2028-01-15',    # approximate
        'first_primary_date':         '2028-01-15',
        'last_primary_date':          '2028-06-06',
        'general_election_day':       '2028-11-07',
        'state_certification_window': '2028-11-19',
        'electoral_count':            '2029-01-06',
        'inauguration_day':           '2029-01-20',
        'congress_121_starts':        '2029-01-03',
    },

    # 2030 midterm cycle
    'midterm_2030': {
        'cycle_name':                 '2030 U.S. Midterm Elections',
        'general_election_day':       '2030-11-05',
        'congress_122_starts':        '2031-01-03',
    },
}


# ============================================================
# CYCLE PHASE DETERMINATION
# ============================================================

def determine_cycle_phase(today=None):
    """Given today's date, return current election-cycle phase.

    Returns dict:
      {
        'phase': 'regular' | 'pre_primary' | 'primary_season' | 'late_campaign' |
                 'election_day' | 'counting' | 'certification' | 'lame_duck' |
                 'transition' | 'inauguration_window',
        'phase_label': human-readable,
        'days_until_next_election': int,
        'next_election_label': '2026 Midterm' | '2028 Presidential' | etc.,
        'next_election_date': ISO date,
        'current_cycle': cycle dict from ELECTION_CYCLE_DATES,
        'stability_modifier': float — multiplier applied to certain stress signals
      }
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    elif isinstance(today, str):
        today = datetime.fromisoformat(today).date()
    elif isinstance(today, datetime):
        today = today.date()

    # Find next election
    upcoming = []
    for cycle_id, cycle in ELECTION_CYCLE_DATES.items():
        ged = cycle.get('general_election_day')
        if ged:
            ged_date = datetime.fromisoformat(ged).date()
            if ged_date >= today:
                upcoming.append((cycle_id, cycle, ged_date))

    if not upcoming:
        # All known cycles are in the past — return regular phase
        return {
            'phase':                    'regular',
            'phase_label':              'Regular Legislative Period',
            'days_until_next_election': None,
            'next_election_label':      'Unknown — update ELECTION_CYCLE_DATES',
            'next_election_date':       None,
            'current_cycle':            None,
            'stability_modifier':       1.0,
        }

    # Sort by date, take nearest
    upcoming.sort(key=lambda x: x[2])
    next_cycle_id, next_cycle, next_election_date = upcoming[0]
    days_until = (next_election_date - today).days

    # Determine phase based on days_until and key dates
    phase = 'regular'
    phase_label = 'Regular Legislative Period'
    stability_modifier = 1.0

    # Lame duck / transition window — between this election and Congress swearing-in
    last_election_date = None
    last_congress_start = None
    for cycle_id, cycle in ELECTION_CYCLE_DATES.items():
        ged = cycle.get('general_election_day')
        if ged:
            ged_date = datetime.fromisoformat(ged).date()
            if ged_date < today:
                # Find the most recent past election
                if last_election_date is None or ged_date > last_election_date:
                    last_election_date = ged_date
                    cs = (cycle.get('congress_120_starts') or
                          cycle.get('congress_121_starts') or
                          cycle.get('congress_122_starts'))
                    last_congress_start = (datetime.fromisoformat(cs).date()
                                           if cs else None)

    # Are we in lame duck?
    if (last_election_date and last_congress_start and
            last_election_date <= today < last_congress_start):
        phase = 'lame_duck'
        phase_label = 'Lame Duck / Transition Window'
        stability_modifier = 1.4    # appointments + late legislation more stress-relevant
        return {
            'phase':                    phase,
            'phase_label':              phase_label,
            'days_until_next_election': days_until,
            'next_election_label':      next_cycle.get('cycle_name', next_cycle_id),
            'next_election_date':       next_election_date.isoformat(),
            'current_cycle':            next_cycle,
            'stability_modifier':       stability_modifier,
        }

    # Are we close to election day?
    if days_until <= 7:
        phase = 'election_day'
        phase_label = 'Election Day Window'
        stability_modifier = 1.6
    elif days_until <= 60:
        phase = 'late_campaign'
        phase_label = 'Late Campaign'
        stability_modifier = 1.3
    elif days_until <= 240:
        # Roughly mid-March onward in midterm year
        first_primary = next_cycle.get('first_primary_date')
        if first_primary:
            first_primary_date = datetime.fromisoformat(first_primary).date()
            if today >= first_primary_date:
                phase = 'primary_season'
                phase_label = 'Primary Season'
                stability_modifier = 1.15
            else:
                phase = 'pre_primary'
                phase_label = 'Pre-Primary Season'
                stability_modifier = 1.05
        else:
            phase = 'pre_primary'
            phase_label = 'Pre-Primary Season'
            stability_modifier = 1.05
    elif days_until <= 365:
        phase = 'pre_primary'
        phase_label = 'Pre-Primary Season'
        stability_modifier = 1.05
    # else: regular legislative period (default values)

    return {
        'phase':                    phase,
        'phase_label':              phase_label,
        'days_until_next_election': days_until,
        'next_election_label':      next_cycle.get('cycle_name', next_cycle_id),
        'next_election_date':       next_election_date.isoformat(),
        'current_cycle':            next_cycle,
        'stability_modifier':       stability_modifier,
    }


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
            timeout=5,
        )
        body = resp.json()
        if body.get('result'):
            return json.loads(body['result'])
    except Exception as e:
        print(f"[US Govt Composition] Redis get error: {str(e)[:120]}")
    return None


def _redis_set(key, value, ttl_seconds=CACHE_TTL_SECONDS):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl_seconds)}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            data=json.dumps(value, default=str),
            timeout=8,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ============================================================
# CONGRESS.GOV API CLIENT
# ============================================================

def _congress_api_call(endpoint, params=None):
    """Call Congress.gov API. Returns parsed JSON or None on error.

    Endpoint examples:
      'congress/119'                  — current congress info
      'member?chamber=house&congress=119' — house members
    """
    if not CONGRESS_API_KEY:
        return None
    try:
        url = f"{CONGRESS_API_BASE}/{endpoint.lstrip('/')}"
        params = params or {}
        params['api_key'] = CONGRESS_API_KEY
        params['format'] = 'json'
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            print(f"[Congress API] {endpoint}: HTTP {resp.status_code}")
            return None
        return resp.json()
    except Exception as e:
        print(f"[Congress API] {endpoint}: error — {str(e)[:120]}")
        return None


def _fetch_current_congress_number():
    """Determine current Congress number from API.
    119th Congress: Jan 3, 2025 - Jan 3, 2027.
    120th Congress: Jan 3, 2027 - Jan 3, 2029.
    """
    today = datetime.now(timezone.utc).date()

    # Hard-coded fallback computation if API fails
    # Each Congress is 2 years; 119th started Jan 3, 2025
    if today < datetime(2027, 1, 3, tzinfo=timezone.utc).date():
        return 119
    elif today < datetime(2029, 1, 3, tzinfo=timezone.utc).date():
        return 120
    elif today < datetime(2031, 1, 3, tzinfo=timezone.utc).date():
        return 121
    else:
        # Compute generically: starting from 119 in 2025
        years_since_119 = today.year - 2025
        # New Congress every 2 years; account for whether today is past Jan 3
        completed_congresses = years_since_119 // 2
        if today >= datetime(today.year, 1, 3, tzinfo=timezone.utc).date():
            return 119 + completed_congresses
        else:
            return 119 + completed_congresses - 1


def _live_fetch_congress_composition():
    """Attempt to fetch current congress composition from Congress.gov API.

    Returns full composition dict or None if API unavailable/failed.

    NOTE: Congress.gov API does NOT provide an aggregate "majority/minority"
    summary endpoint. We must aggregate from member roll. For initial
    deployment, this attempts the aggregation; if any step fails, the caller
    falls back to static data."""
    if not CONGRESS_API_KEY:
        return None

    congress_num = _fetch_current_congress_number()

    # Step 1: Try to fetch member roll for current congress
    house_members = _congress_api_call(
        f'member/congress/{congress_num}',
        params={'chamber': 'house', 'limit': 500}
    )
    senate_members = _congress_api_call(
        f'member/congress/{congress_num}',
        params={'chamber': 'senate', 'limit': 200}
    )

    if not house_members or not senate_members:
        print(f"[US Govt Composition] Live API fetch failed — falling back to static")
        return None

    # Step 2: Aggregate party counts
    def count_parties(member_payload):
        members = member_payload.get('members', [])
        counts = {}
        for m in members:
            party_history = m.get('partyHistory', [])
            current_party = None
            if party_history:
                # First entry is most recent
                current_party = (party_history[0].get('partyName') or
                                 party_history[0].get('partyAbbreviation'))
            elif m.get('party'):
                current_party = m.get('party')
            if current_party:
                # Normalize
                if current_party.lower().startswith('republican'):
                    current_party = 'Republican'
                elif current_party.lower().startswith('democrat'):
                    current_party = 'Democratic'
                elif current_party.lower().startswith('independent'):
                    current_party = 'Independent'
                counts[current_party] = counts.get(current_party, 0) + 1
        return counts, len(members)

    house_counts, house_total = count_parties(house_members)
    senate_counts, senate_total = count_parties(senate_members)

    if not house_counts or not senate_counts:
        return None

    def majority_party(counts):
        return max(counts.items(), key=lambda x: x[1])[0]

    def minority_party(counts):
        sorted_parties = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_parties[1][0] if len(sorted_parties) > 1 else None

    # Build live composition dict
    # NOTE: Leadership names come from STATIC data — Congress.gov doesn't expose
    # speaker/leader directly via API. This is fine: leadership changes mid-term
    # are rare and warrant manual update of static data. Live API gives us the
    # critical signal: did seat counts change after an election?
    live_comp = {
        'number':           congress_num,
        'started':          CONGRESS_119_FALLBACK['started']
                             if congress_num == 119 else f'{congress_num * 2 + 1787}-01-03',
        'ends':             CONGRESS_119_FALLBACK['ends']
                             if congress_num == 119 else f'{congress_num * 2 + 1789}-01-03',
        'data_as_of':       datetime.now(timezone.utc).isoformat(),

        'house': {
            'total_seats':      house_total,
            'majority_party':   majority_party(house_counts),
            'majority_size':    max(house_counts.values()),
            'minority_size':    sorted(house_counts.values(), reverse=True)[1] if len(house_counts) > 1 else 0,
            'party_counts':     house_counts,
            # Leadership from static (live API doesn't expose this directly)
            'speaker':          CONGRESS_119_FALLBACK['house']['speaker'] if congress_num == 119 else None,
            'majority_leader':  CONGRESS_119_FALLBACK['house']['majority_leader'] if congress_num == 119 else None,
            'minority_leader':  CONGRESS_119_FALLBACK['house']['minority_leader'] if congress_num == 119 else None,
            'majority_whip':    CONGRESS_119_FALLBACK['house']['majority_whip'] if congress_num == 119 else None,
            'minority_whip':    CONGRESS_119_FALLBACK['house']['minority_whip'] if congress_num == 119 else None,
        },

        'senate': {
            'total_seats':      senate_total,
            'majority_party':   majority_party(senate_counts),
            'majority_size':    max(senate_counts.values()),
            'minority_size':    sorted(senate_counts.values(), reverse=True)[1] if len(senate_counts) > 1 else 0,
            'party_counts':     senate_counts,
            'majority_leader':  CONGRESS_119_FALLBACK['senate']['majority_leader'] if congress_num == 119 else None,
            'minority_leader':  CONGRESS_119_FALLBACK['senate']['minority_leader'] if congress_num == 119 else None,
            'majority_whip':    CONGRESS_119_FALLBACK['senate']['majority_whip'] if congress_num == 119 else None,
            'minority_whip':    CONGRESS_119_FALLBACK['senate']['minority_whip'] if congress_num == 119 else None,
            'pro_tempore':      CONGRESS_119_FALLBACK['senate']['pro_tempore'] if congress_num == 119 else None,
        },

        'house_committees':  CONGRESS_119_FALLBACK['house_committees'] if congress_num == 119 else {},
        'senate_committees': CONGRESS_119_FALLBACK['senate_committees'] if congress_num == 119 else {},
    }

    return live_comp


# ============================================================
# STRUCTURAL FRICTION BASELINE
# ============================================================

def compute_structural_baseline(congress_data, executive_data):
    """Determine if we have unified or divided government.

    Unified government: same party holds Presidency + House + Senate.
    Divided government: at least one chamber held by opposite party.

    This affects how us_stability.py weights various signals:
      - Unified: cabinet turnover reads as bigger signal (less normal)
      - Divided: court orders defied reads as bigger signal (more confrontation expected)

    Returns:
      {
        'unified_government': bool,
        'divided_government': bool,
        'governing_party': 'Republican' | 'Democratic' | 'Mixed',
        'opposition_party': str,
        'configuration': 'unified_R' | 'unified_D' | 'divided_split' |
                         'divided_house_opposition' | 'divided_senate_opposition',
        'baseline_modifiers': {
          'cabinet_turnover_weight':       float,
          'court_orders_defied_weight':    float,
          'partisan_deadlock_weight':      float,
          ...
        }
      }
    """
    pres_party = executive_data.get('president', {}).get('party', '?')
    house_party = congress_data.get('house', {}).get('majority_party', '?')
    senate_party = congress_data.get('senate', {}).get('majority_party', '?')

    # Normalize party codes (R/D)
    def norm(p):
        if p in ('R', 'Republican'):
            return 'R'
        if p in ('D', 'Democratic', 'Democrat'):
            return 'D'
        return '?'

    pn, hn, sn = norm(pres_party), norm(house_party), norm(senate_party)

    unified = (pn == hn == sn) and pn != '?'
    divided = not unified

    if unified:
        configuration = f'unified_{pn}'
        governing_party = ('Republican' if pn == 'R' else
                           'Democratic' if pn == 'D' else 'Unknown')
        opposition_party = ('Democratic' if pn == 'R' else
                            'Republican' if pn == 'D' else 'Unknown')
    else:
        # Determine divided configuration
        if pn != hn and pn != sn:
            configuration = 'divided_split'    # exec opposed by both chambers
        elif pn != hn:
            configuration = 'divided_house_opposition'
        elif pn != sn:
            configuration = 'divided_senate_opposition'
        else:
            configuration = 'divided_other'
        governing_party = 'Mixed'
        opposition_party = 'Mixed'

    # Baseline-modifier weights — tuned to scoring rubric in us_stability.py
    if unified:
        # Unified govt expects low inter-branch friction; deviations are bigger signals
        baseline_modifiers = {
            'cabinet_turnover_weight':         1.3,
            'agency_leadership_churn_weight':  1.3,
            'court_orders_defied_weight':      1.4,    # rare, big signal
            'partisan_deadlock_weight':        1.5,    # very surprising under unified
            'inspector_general_dismissal':     1.4,
            'civil_service_purge_weight':      1.3,
        }
    else:
        # Divided govt expects high inter-branch friction; deviations less surprising
        baseline_modifiers = {
            'cabinet_turnover_weight':         1.0,
            'agency_leadership_churn_weight':  1.0,
            'court_orders_defied_weight':      1.6,    # bigger deal under divided
            'partisan_deadlock_weight':        1.0,
            'inspector_general_dismissal':     1.4,
            'civil_service_purge_weight':      1.3,
        }

    return {
        'unified_government':  unified,
        'divided_government':  divided,
        'governing_party':     governing_party,
        'opposition_party':    opposition_party,
        'configuration':       configuration,
        'baseline_modifiers':  baseline_modifiers,
    }


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def get_government_composition(force_refresh=False):
    """Get current U.S. government composition.

    Returns dict with:
      {
        'success':            bool,
        'data_freshness':     'live' | 'cached' | 'static_fallback',
        'staleness_warning':  optional string if data is concerning age,
        'congress':           {...},
        'executive':          {...},
        'election_cycle':     {...},
        'structural_baseline': {...},
        'fetched_at':         ISO timestamp,
        'static_fallback_as_of': STATIC_DATA_AS_OF,
        'version':            '1.0.0',
      }

    Cache: 24-hour Redis cache for live data.
    """
    # ── Cache check ──
    if not force_refresh:
        cached = _redis_get(CACHE_KEY)
        if cached and cached.get('fetched_at'):
            try:
                fetched = datetime.fromisoformat(cached['fetched_at'])
                age = (datetime.now(timezone.utc) - fetched).total_seconds()
                if age < CACHE_TTL_SECONDS:
                    cached['data_freshness'] = 'cached'
                    cached['cache_age_hours'] = round(age / 3600, 2)
                    return cached
            except Exception:
                pass

    # ── Try live fetch ──
    live_congress = _live_fetch_congress_composition()
    data_freshness = 'static_fallback'

    if live_congress:
        congress_data = live_congress
        data_freshness = 'live'
    else:
        congress_data = CONGRESS_119_FALLBACK
        # Use static; flag for staleness if static_data_as_of is old
        try:
            static_age_days = (datetime.now(timezone.utc).date() -
                               datetime.fromisoformat(STATIC_DATA_AS_OF).date()).days
        except Exception:
            static_age_days = 0
        if static_age_days > 90:
            print(f"[US Govt Composition] ⚠️  Static data is {static_age_days} days old "
                  f"— consider updating CONGRESS_119_FALLBACK")

    executive_data = EXECUTIVE_2025_FALLBACK    # exec branch always static for now
    election_cycle = determine_cycle_phase()
    structural_baseline = compute_structural_baseline(congress_data, executive_data)

    # Compute staleness warning
    staleness_warning = None
    if data_freshness == 'static_fallback':
        try:
            static_age_days = (datetime.now(timezone.utc).date() -
                               datetime.fromisoformat(STATIC_DATA_AS_OF).date()).days
            if static_age_days > 30:
                staleness_warning = (f'Composition data is from {STATIC_DATA_AS_OF} '
                                     f'({static_age_days} days old). Live API unavailable '
                                     f'— results may not reflect recent leadership changes.')
        except Exception:
            pass

    # Special warning if we're past an election day but composition hasn't been refreshed
    today = datetime.now(timezone.utc).date()
    for cycle_id, cycle in ELECTION_CYCLE_DATES.items():
        ged = cycle.get('general_election_day')
        if ged:
            ged_date = datetime.fromisoformat(ged).date()
            congress_start = (cycle.get('congress_120_starts') or
                              cycle.get('congress_121_starts') or
                              cycle.get('congress_122_starts'))
            if not congress_start:
                continue
            cs_date = datetime.fromisoformat(congress_start).date()
            if ged_date < today < cs_date and data_freshness == 'static_fallback':
                staleness_warning = (f'⚠️ Election held {ged_date}. New Congress sworn in '
                                     f'{cs_date}. Live API unavailable — composition shown '
                                     f'reflects pre-election state.')
                break

    result = {
        'success':                True,
        'data_freshness':         data_freshness,
        'staleness_warning':      staleness_warning,
        'congress':               congress_data,
        'executive':              executive_data,
        'election_cycle':         election_cycle,
        'structural_baseline':    structural_baseline,
        'fetched_at':             datetime.now(timezone.utc).isoformat(),
        'static_fallback_as_of':  STATIC_DATA_AS_OF,
        'congress_api_configured': bool(CONGRESS_API_KEY),
        'redis_configured':       bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
        'version':                '1.0.0',
    }

    # ── Write to cache (only successful live fetches) ──
    if data_freshness == 'live':
        _redis_set(CACHE_KEY, result)
        print(f"[US Govt Composition] ✅ Live data fetched and cached "
              f"(House: {congress_data['house']['majority_party']} "
              f"{congress_data['house']['majority_size']}-{congress_data['house']['minority_size']}, "
              f"Senate: {congress_data['senate']['majority_party']} "
              f"{congress_data['senate']['majority_size']}-{congress_data['senate']['minority_size']})")
    else:
        print(f"[US Govt Composition] Using static fallback data (as of {STATIC_DATA_AS_OF})")

    return result


# ============================================================
# QUICK-ACCESS HELPERS — convenience for consumers
# ============================================================

def get_house_majority():
    """Quick access: returns the party currently holding House majority."""
    comp = get_government_composition()
    return comp['congress']['house']['majority_party']


def get_senate_majority():
    """Quick access: returns the party currently holding Senate majority."""
    comp = get_government_composition()
    return comp['congress']['senate']['majority_party']


def is_unified_government():
    """Quick access: True if exec/house/senate all same party."""
    comp = get_government_composition()
    return comp['structural_baseline']['unified_government']


def get_election_cycle_phase():
    """Quick access: returns current election-cycle phase string."""
    comp = get_government_composition()
    return comp['election_cycle']['phase']


def get_stability_modifier():
    """Quick access: returns current cycle's stability stress modifier (float)."""
    comp = get_government_composition()
    return comp['election_cycle']['stability_modifier']


# ============================================================
# FLASK ENDPOINT REGISTRATION
# ============================================================

def register_government_composition_endpoints(app):
    """Register the /api/us-government-composition Flask endpoints."""

    @app.route('/api/us-government-composition', methods=['GET', 'OPTIONS'])
    def api_us_government_composition():
        from flask import request as flask_request, jsonify
        if flask_request.method == 'OPTIONS':
            return '', 200
        try:
            force = flask_request.args.get('refresh', 'false').lower() == 'true'
            result = get_government_composition(force_refresh=force)
            return jsonify(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/us-government-composition/debug', methods=['GET'])
    def api_us_government_composition_debug():
        """Diagnostic endpoint — shows config + freshness + cycle state."""
        from flask import jsonify
        cached = _redis_get(CACHE_KEY)
        cycle_now = determine_cycle_phase()
        return jsonify({
            'version':                  '1.0.0',
            'congress_api_configured':  bool(CONGRESS_API_KEY),
            'redis_configured':         bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'static_data_as_of':        STATIC_DATA_AS_OF,
            'cache_ttl_hours':          CACHE_TTL_SECONDS / 3600,
            'cached_data_present':      bool(cached),
            'cached_fetched_at':        (cached or {}).get('fetched_at'),
            'cached_data_freshness':    (cached or {}).get('data_freshness'),
            'current_cycle_phase':      cycle_now,
            'next_election_dates':      {
                k: v.get('general_election_day')
                for k, v in ELECTION_CYCLE_DATES.items()
            },
            'congress_119_static':      {
                'house': f"{CONGRESS_119_FALLBACK['house']['majority_party']} "
                         f"{CONGRESS_119_FALLBACK['house']['majority_size']}-"
                         f"{CONGRESS_119_FALLBACK['house']['minority_size']}",
                'senate': f"{CONGRESS_119_FALLBACK['senate']['majority_party']} "
                          f"{CONGRESS_119_FALLBACK['senate']['majority_size']}-"
                          f"{CONGRESS_119_FALLBACK['senate']['minority_size']}",
            },
        })

    print("[US Govt Composition] ✅ Endpoints registered: "
          "/api/us-government-composition, /api/us-government-composition/debug")


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == '__main__':
    """Self-test."""
    print("\n" + "=" * 60)
    print("US GOVERNMENT COMPOSITION — SELF-TEST")
    print("=" * 60)

    # Test 1: Cycle phase determination
    print("\n=== Test 1: Cycle Phase Determination ===")
    test_dates = [
        ('2026-05-10', 'Today (mid-May 2026)'),
        ('2026-08-15', 'Pre-late-campaign'),
        ('2026-09-15', 'Late campaign starts ~60 days out'),
        ('2026-11-01', 'Election week'),
        ('2026-11-04', 'Day after election'),
        ('2026-12-15', 'Lame duck mid-window'),
        ('2027-01-04', 'Day after new Congress'),
    ]
    for date_str, label in test_dates:
        phase = determine_cycle_phase(date_str)
        print(f"  {date_str} ({label}):")
        print(f"    phase: {phase['phase']} ({phase['phase_label']})")
        print(f"    days_until_election: {phase['days_until_next_election']}")
        print(f"    stability_modifier: {phase['stability_modifier']}")
        print()

    # Test 2: Structural baseline
    print("\n=== Test 2: Structural Baseline ===")
    sb = compute_structural_baseline(CONGRESS_119_FALLBACK, EXECUTIVE_2025_FALLBACK)
    print(f"  Configuration:        {sb['configuration']}")
    print(f"  Unified govt:         {sb['unified_government']}")
    print(f"  Governing party:      {sb['governing_party']}")
    print(f"  Cabinet turnover wt:  {sb['baseline_modifiers']['cabinet_turnover_weight']}")
    print(f"  Court orders wt:      {sb['baseline_modifiers']['court_orders_defied_weight']}")

    # Test 3: Hypothetical divided govt (post-2026 if Dems take House)
    print("\n=== Test 3: Hypothetical Divided Govt ===")
    divided_house = dict(CONGRESS_119_FALLBACK)
    divided_house['house'] = {**divided_house['house'], 'majority_party': 'Democratic',
                                'majority_size': 220, 'minority_size': 213}
    sb2 = compute_structural_baseline(divided_house, EXECUTIVE_2025_FALLBACK)
    print(f"  Configuration:        {sb2['configuration']}")
    print(f"  Divided govt:         {sb2['divided_government']}")
    print(f"  Cabinet turnover wt:  {sb2['baseline_modifiers']['cabinet_turnover_weight']}")
    print(f"  Court orders wt:      {sb2['baseline_modifiers']['court_orders_defied_weight']}")

    # Test 4: Full composition fetch
    print("\n=== Test 4: Full Composition Fetch ===")
    comp = get_government_composition(force_refresh=True)
    print(f"  Success:           {comp['success']}")
    print(f"  Data freshness:    {comp['data_freshness']}")
    print(f"  Static as of:      {comp['static_fallback_as_of']}")
    print(f"  House:             {comp['congress']['house']['majority_party']} "
          f"{comp['congress']['house']['majority_size']}-{comp['congress']['house']['minority_size']}")
    print(f"  Senate:            {comp['congress']['senate']['majority_party']} "
          f"{comp['congress']['senate']['majority_size']}-{comp['congress']['senate']['minority_size']}")
    print(f"  President:         {comp['executive']['president']['name']} "
          f"({comp['executive']['president']['party']})")
    print(f"  Cabinet members:   {len(comp['executive']['cabinet'])}")
    print(f"  SCOTUS justices:   {len(comp['executive']['supreme_court'])}")
    print(f"  Election phase:    {comp['election_cycle']['phase_label']}")
    print(f"  Configuration:     {comp['structural_baseline']['configuration']}")
    if comp.get('staleness_warning'):
        print(f"  ⚠️  Staleness:      {comp['staleness_warning']}")

    print("\n✅ SELF-TEST COMPLETE")
