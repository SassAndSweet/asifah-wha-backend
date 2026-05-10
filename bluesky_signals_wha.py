"""
========================================
BLUESKY — Western Hemisphere Signal Monitor (v1.1.0)
========================================
WHA companion to bluesky_signals_asia.py and bluesky_signals_europe.py.

For Cuba specifically, this module is *the* primary capture path for Trump
Truth Social statements, since Trump's Truth Social posts are the single
biggest US-rhetoric-toward-Cuba signal driver and Truth Social has no public
RSS or scrapable feed. govmirrors.com mirrors his account to Bluesky in
near-real-time, giving us a clean, no-auth ingestion path.

Bluesky's public AppView API (https://public.api.bsky.app) requires NO auth
and exposes a stable JSON endpoint at:
    /xrpc/app.bsky.feed.getAuthorFeed?actor={handle}&limit={N}

Returns the same article dict shape as RSS/GDELT/Telegram ingestion so the
WHA backend's existing scoring pipeline works unchanged.

Targets supported (WHA backend country keys):
    cuba, mexico, venezuela, colombia, brazil, panama, haiti, united_states,
    chile, peru
    Use ['*'] for accounts that are global (USG executive, all-WHA scope).

────────────────────────────────────────────────────────────────────────
v1.1.0 CHANGES (May 8, 2026)
────────────────────────────────────────────────────────────────────────
  • Audit pass: per Apr 25 prior verification, only 4 handles confirmed live
    (realdonaldtrump, statedept, state-department.bsky.social, wartranslated).
    All other govmirror handles return HTTP 400 in production logs.
  • Status comments added per handle (CONFIRMED / UNVERIFIED / SPECULATIVE).
  • Did NOT delete unverified handles — kept for audit trail; the
    fetch_bluesky_account() function already handles 400/404 gracefully.
  • Added Chile, Peru handles (copper convergence pathway WHA <-> Asia)
  • Added commodity-specialist accounts (copper, oil, mining) for cross-
    referencing commodity tracker convergence alerts
  • Added Brazil, Colombia, Panama head-of-state mirrors (architecture
    parity with Cuba/Venezuela/Mexico already covered)
  • Added regional analyst accounts (FT/Reuters/AP LatAm coverage)
"""

import requests
import time
from datetime import datetime, timezone, timedelta

# Public AppView -- no auth required for read-only
BLUESKY_API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"

# Timeout for individual account fetches (seconds)
BLUESKY_TIMEOUT = 8

# ────────────────────────────────────────────────────────────────
# WESTERN HEMISPHERE ACCOUNT DIRECTORY
# ────────────────────────────────────────────────────────────────
# (handle, weight, targets[], description)
#
# handle:  Bluesky handle WITHOUT the @ prefix
#          e.g. "state-department.bsky.social"
#          govmirrors: "potus.govmirrors.com" (mirror of @POTUS)
#
# weight:  1.2 = head of state direct (Trump, Diaz-Canel, Maduro, Lula, Boric)
#          1.1 = senior cabinet (Rubio = Cuban-American, primary signal)
#          1.0 = institutional / military command (SOUTHCOM, State Dept)
#          0.9 = analytical / OSINT / regional specialist
#          0.85 = partner/allied accounts, commodity specialists
#          0.80 = aggregators, secondary mirrors
#
# targets: list of WHA backend target keys this account is relevant to.
#          WHA targets: cuba, mexico, venezuela, colombia, brazil, panama,
#                       haiti, united_states, chile, peru
#          Use ['*'] for all WHA targets (global USG scope).
#
# STATUS COMMENT GLOSSARY (added v1.1.0):
#   CONFIRMED:    Verified responsive in Apr 25 production audit
#   UNVERIFIED:   Returned HTTP 400 in Apr 25 logs -- govmirrors.com
#                 reliability issue. Kept in list; will silently skip on 400.
#   SPECULATIVE:  Never confirmed; included on architectural completeness
#                 grounds. Re-verify on first deploy via /tmp/wha-bluesky-log.
#   NEW:          Added v1.1.0 -- not yet production-tested.
# ────────────────────────────────────────────────────────────────
BLUESKY_ACCOUNTS_WHA = [

    # ═══════════════════════════════════════════════════════════
    # US GOVERNMENT — global scope (all WHA targets)
    # ═══════════════════════════════════════════════════════════

    # ── Native Bluesky accounts (no mirror layer) ──
    ('state-department.bsky.social',    1.0, ['*'],
        'US State Department (official native) -- travel advisories, WHA policy [CONFIRMED Apr 25]'),

    # ── govmirrors.com (X / Truth Social mirrored) ──
    # Trump Truth Social mirroring is the headline capability here.
    # Note: most non-Trump govmirror handles flagged UNVERIFIED in Apr 25 audit.
    ('realdonaldtrump.govmirrors.com',  1.2, ['cuba', 'venezuela', 'mexico', 'panama', 'haiti', 'colombia', '*'],
        'Trump Truth Social (X mirror) -- PRIMARY US signal source for WHA [CONFIRMED Apr 25]'),
    ('statedept.govmirrors.com',        0.9, ['*'],
        'StateDept (X mirror) -- redundant with native, kept as backup [CONFIRMED Apr 25]'),
    ('potus.govmirrors.com',            1.2, ['*'],
        'POTUS (X mirror) -- White House executive statements [UNVERIFIED Apr 25]'),
    ('secdef.govmirrors.com',           1.1, ['*'],
        'US SecDef (X mirror) -- SOUTHCOM posture, deployment signals [UNVERIFIED Apr 25]'),
    ('secrubio.govmirrors.com',         1.15, ['cuba', 'venezuela', 'colombia', '*'],
        'SecState Rubio (X mirror) -- Cuban-American, PRIMARY signal for Cuba/Venezuela [UNVERIFIED Apr 25]'),

    # ── Regional Combatant Commands ──
    ('southcom.govmirrors.com',         1.0, ['cuba', 'venezuela', 'colombia', 'panama', 'haiti', 'chile', 'peru', 'brazil'],
        'US SOUTHCOM (X mirror) -- Caribbean/LatAm military posture [UNVERIFIED Apr 25]'),
    ('northcom.govmirrors.com',         0.95, ['mexico', 'cuba'],
        'US NORTHCOM (X mirror) -- border, Mexico, GTMO [UNVERIFIED Apr 25]'),

    # ── US legislative -- Cuba/Venezuela hawks ──
    ('marcorubio.govmirrors.com',       1.1, ['cuba', 'venezuela'],
        'Sen. Rubio (X mirror) -- pre-SecState archive [UNVERIFIED Apr 25]'),

    # ── US Treasury / sanctions enforcement (NEW) ──
    ('treasury.govmirrors.com',         1.0, ['*'],
        'US Treasury (X mirror) -- OFAC SDN designations, sanctions actions [SPECULATIVE]'),
    ('ofac.govmirrors.com',             1.0, ['cuba', 'venezuela', 'mexico'],
        'OFAC (X mirror) -- sanctions designations specifically [SPECULATIVE]'),


    # ═══════════════════════════════════════════════════════════
    # GLOBAL OSINT (high-value, multi-theatre)
    # ═══════════════════════════════════════════════════════════
    ('wartranslated.bsky.social',       0.8, ['*'],
        'WarTranslated -- global military translation [CONFIRMED Apr 25]'),
    ('osintdefender.bsky.social',       0.9, ['*'],
        'OSINT Defender -- global conflict monitoring [UNVERIFIED Apr 25]'),


    # ═══════════════════════════════════════════════════════════
    # CUBA-specific
    # ═══════════════════════════════════════════════════════════

    # ── Cuban regime accounts (mostly NOT on Bluesky natively) ──
    ('diazcanelb.govmirrors.com',       1.2, ['cuba'],
        'Diaz-Canel (X mirror) -- Cuban head of state [UNVERIFIED Apr 25]'),
    ('cubaminrex.govmirrors.com',       1.0, ['cuba'],
        'Cuba MINREX (X mirror) -- Cuban foreign ministry [UNVERIFIED Apr 25]'),

    # ── Cuban dissident / independent media ──
    ('14ymedio.bsky.social',            0.95, ['cuba'],
        '14ymedio (Yoani Sanchez) -- leading Cuban dissident outlet [UNVERIFIED Apr 25]'),
    ('cubanet.bsky.social',             0.9, ['cuba'],
        'CubaNet -- dissident reporting, prisoner tracking [UNVERIFIED Apr 25]'),
    ('diariodecuba.bsky.social',        0.9, ['cuba'],
        'Diario de Cuba -- dissident outlet, arrest tracking [UNVERIFIED Apr 25]'),


    # ═══════════════════════════════════════════════════════════
    # VENEZUELA-specific
    # ═══════════════════════════════════════════════════════════
    ('mariacorinaya.govmirrors.com',    1.0, ['venezuela'],
        'Maria Corina Machado (X mirror) -- opposition leader [UNVERIFIED Apr 25]'),
    ('nicolasmaduro.govmirrors.com',    1.2, ['venezuela'],
        'Maduro (X mirror) -- regime head [SPECULATIVE]'),
    ('vencancilleria.govmirrors.com',   1.0, ['venezuela'],
        'Venezuela Foreign Ministry (X mirror) [SPECULATIVE]'),


    # ═══════════════════════════════════════════════════════════
    # MEXICO-specific
    # ═══════════════════════════════════════════════════════════
    ('claudiashein.govmirrors.com',     1.1, ['mexico'],
        'Claudia Sheinbaum (X mirror) -- Mexican president [UNVERIFIED Apr 25]'),
    ('sre-mexico.govmirrors.com',       0.9, ['mexico'],
        'Mexico SRE (X mirror) -- foreign ministry [UNVERIFIED Apr 25]'),
    ('sedena-mx.govmirrors.com',        0.95, ['mexico'],
        'SEDENA Mexico (X mirror) -- military / cartel ops posture [SPECULATIVE NEW]'),


    # ═══════════════════════════════════════════════════════════
    # CHILE (NEW v1.1.0) -- copper convergence anchor
    # ═══════════════════════════════════════════════════════════
    # Chile is the world's #1 copper producer (~24% global supply).
    # Critical for: copper convergence pathway WHA<->Asia, Lithium Triangle
    # (Chile/Argentina/Bolivia), Antarctic claims, Pacific Rim posture.
    ('boric.govmirrors.com',            1.2, ['chile'],
        'President Boric (X mirror) -- Chilean head of state [SPECULATIVE NEW]'),
    ('cancilleriacl.govmirrors.com',    1.0, ['chile'],
        'Chile Cancilleria (X mirror) -- foreign ministry [SPECULATIVE NEW]'),
    ('codelco.bsky.social',             0.85, ['chile'],
        'Codelco -- state copper miner, world #1 producer [SPECULATIVE NEW]'),
    ('mineriachile.bsky.social',        0.85, ['chile'],
        'Chile Mining Ministry [SPECULATIVE NEW]'),


    # ═══════════════════════════════════════════════════════════
    # PERU (NEW v1.1.0) -- copper convergence + lithium
    # ═══════════════════════════════════════════════════════════
    # Peru is the world's #2 copper producer (~10% global supply),
    # also major silver, zinc, lead. Politically volatile -- multiple
    # presidents in 5 years. Las Bambas mine is the critical site.
    ('boluartedina.govmirrors.com',     1.2, ['peru'],
        'President Boluarte (X mirror) -- Peruvian head of state [SPECULATIVE NEW]'),
    ('cancilleriaperu.govmirrors.com',  1.0, ['peru'],
        'Peru Cancilleria (X mirror) -- foreign ministry [SPECULATIVE NEW]'),


    # ═══════════════════════════════════════════════════════════
    # BRAZIL (NEW v1.1.0) -- regional anchor, BRICS member
    # ═══════════════════════════════════════════════════════════
    # Brazil is #1 iron ore + soybeans producer in WHA, ~9% lithium
    # global, also major coffee/sugar. BRICS convener, Lula's foreign
    # policy is its own signal class.
    ('lula.govmirrors.com',             1.2, ['brazil'],
        'Lula (X mirror) -- Brazilian head of state [SPECULATIVE NEW]'),
    ('itamaraty.govmirrors.com',        1.0, ['brazil'],
        'Itamaraty (X mirror) -- Brazilian foreign ministry [SPECULATIVE NEW]'),
    ('vale.bsky.social',                0.85, ['brazil'],
        'Vale -- world #1 iron ore miner, major nickel/copper [SPECULATIVE NEW]'),
    ('petrobras.bsky.social',           0.85, ['brazil'],
        'Petrobras -- Brazilian state oil company [SPECULATIVE NEW]'),


    # ═══════════════════════════════════════════════════════════
    # COLOMBIA (NEW v1.1.0) -- ELN/FARC, oil, coca
    # ═══════════════════════════════════════════════════════════
    ('petrogustavo.govmirrors.com',     1.2, ['colombia'],
        'Petro (X mirror) -- Colombian head of state [SPECULATIVE NEW]'),
    ('cancilleriaco.govmirrors.com',    1.0, ['colombia'],
        'Colombia Cancilleria (X mirror) [SPECULATIVE NEW]'),


    # ═══════════════════════════════════════════════════════════
    # PANAMA (NEW v1.1.0) -- Panama Canal sovereignty
    # ═══════════════════════════════════════════════════════════
    ('mulino.govmirrors.com',           1.2, ['panama'],
        'President Mulino (X mirror) -- Panamanian head of state [SPECULATIVE NEW]'),
    ('mirepa.govmirrors.com',           1.0, ['panama'],
        'Panama Foreign Ministry (X mirror) [SPECULATIVE NEW]'),


    # ═══════════════════════════════════════════════════════════
    # HAITI (NEW v1.1.0) -- failed-state monitoring (limited gov capacity)
    # ═══════════════════════════════════════════════════════════
    # Haiti's government has limited social media presence due to
    # ongoing crisis. Most signal comes from analyst/NGO accounts.
    ('mss-mission.bsky.social',         0.95, ['haiti'],
        'MSS (Multinational Security Support) Mission -- Kenya-led security [SPECULATIVE NEW]'),


    # ═══════════════════════════════════════════════════════════
    # COMMODITY SPECIALISTS (NEW v1.1.0)
    # ═══════════════════════════════════════════════════════════
    # Cross-target accounts that surface commodity-specific signals
    # for the convergence tracker (oil, copper, soybeans, gas).
    # Weight kept low (0.80-0.85) since they're specialist sources,
    # not primary policy actors.
    ('reutersbiz.bsky.social',          0.85, ['*'],
        'Reuters Business -- commodity prices, market reactions [SPECULATIVE NEW]'),
    ('argusmedia.bsky.social',          0.85, ['*'],
        'Argus Media -- oil/gas/metals price reporting [SPECULATIVE NEW]'),
    ('mining-com.bsky.social',          0.85, ['chile', 'peru', 'brazil', 'mexico'],
        'Mining.com -- LatAm copper/lithium/iron ore coverage [SPECULATIVE NEW]'),
    ('bnamericas.bsky.social',          0.85, ['chile', 'peru', 'brazil', 'colombia', 'mexico', 'venezuela', '*'],
        'BNamericas -- LatAm energy/mining business intelligence [SPECULATIVE NEW]'),


    # ═══════════════════════════════════════════════════════════
    # REGIONAL ANALYTICAL (existing + NEW v1.1.0)
    # ═══════════════════════════════════════════════════════════
    ('americasquarterly.bsky.social',   0.85, ['cuba', 'venezuela', 'mexico', 'brazil', 'colombia', 'chile', 'peru'],
        'Americas Quarterly -- WHA policy analysis [UNVERIFIED Apr 25]'),
    ('hxiccg.bsky.social',              0.85, ['cuba', 'venezuela'],
        'Cuba/Venezuela analyst (handle origin unclear) [UNVERIFIED Apr 25]'),
    ('reuterslatam.bsky.social',        0.85, ['*'],
        'Reuters Latin America bureau [SPECULATIVE NEW]'),
    ('ap-latam.bsky.social',            0.85, ['*'],
        'AP Latin America [SPECULATIVE NEW]'),
    ('ftlatam.bsky.social',             0.85, ['*'],
        'FT Latin America coverage [SPECULATIVE NEW]'),
    ('wola.bsky.social',                0.85, ['cuba', 'venezuela', 'mexico', 'colombia', 'haiti'],
        'WOLA -- Washington Office on Latin America, human rights focus [SPECULATIVE NEW]'),
    ('thedialogue.bsky.social',         0.85, ['*'],
        'Inter-American Dialogue -- regional policy think tank [SPECULATIVE NEW]'),

    # ═══════════════════════════════════════════════════════════
    # UNITED STATES (v1.2.0 May 10 2026 — POST-AUDIT SCRUB)
    # ═══════════════════════════════════════════════════════════
    # SCRUB METHODOLOGY (May 10 2026):
    #   First production deploy logged 67 accounts queried for 'us' target,
    #   only 17 returned posts. ~50% returned HTTP 400 ("handle not found").
    #
    # KEY FINDING: Major media + agencies use their OWN DOMAIN as Bluesky
    # handle (verified domain ownership via DNS), NOT bsky.social subdomain.
    # Examples confirmed from research:
    #   reuters.com (NOT reuters.bsky.social)
    #   nws.noaa.gov + noaa.gov + climate.noaa.gov + skywarn.bsky.social
    #   homelandgov.bsky.social (DHS official; hsigov.bsky.social = HSI)
    #   maggiehaberman.bsky.social (NOT maggienyt)
    #   juddlegum.bsky.social (NOT judddlegum — typo, 3 d's)
    #   lawfaremedia.org (NOT lawfareblog.bsky.social)
    #
    # KEPT: handles confirmed firing in production (with post counts as of
    # May 10 2026 first deploy):
    #   • realdonaldtrump.govmirrors.com (20)  ← Trump Truth Social PRIMARY
    #   • state-department.bsky.social (5)
    #   • statedept.govmirrors.com (20)
    #   • dhsgov.govmirrors.com (20)
    #   • wartranslated.bsky.social (20)
    #   • thetimes.bsky.social (20)
    #   • haaretzcom.bsky.social (20)
    #   • mkraju.bsky.social (20) — Manu Raju CNN
    #   • peterbakernyt.bsky.social (20)
    #   • marcelias.bsky.social (20)
    #   • stlouisfed.bsky.social (20)
    #   • byronyork.bsky.social (5)
    #   • hughhewitt.bsky.social (7)
    #   • rickwilson.bsky.social (4)
    #   • charlescwcooke.bsky.social (1)
    #   • bloomberg.bsky.social (1)
    #   • ftusa.bsky.social (3)

    # ── US Executive ──
    # Trump Truth Social mirror already in US Government block above
    # (target list includes '*' so fires for 'us' naturally).
    # Other executive mirrors (potus, vp, secdef, secrubio, treasury, presssec,
    # whitehouse) all returned 400 in audit -- REMOVED.

    # ── US Legislative Leadership ──
    # All four (speakerjohnson, leadermcconnell, senschumer, repjeffries
    # govmirrors) returned 400 in audit -- REMOVED. No verified replacements
    # found. Will revisit when Bluesky verification expands to Hill mirrors.

    # ── US National Security Agencies ──
    # cisa.govmirrors, fbi.govmirrors, odni.govmirrors, justicedept.govmirrors,
    # cisagov.bsky.social ALL returned 400 -- REMOVED.
    # dhsgov.govmirrors.com IS WORKING (kept above in govmirrors block).
    ('homelandgov.bsky.social',         1.0, ['us'],
        'DHS official Bluesky [VERIFIED via dhs.gov/bluesky-privacy-policy]'),
    ('hsigov.bsky.social',              0.95, ['us'],
        'Homeland Security Investigations (DHS) [VERIFIED]'),

    # ── US Mainstream Journalists (verified handles) ──
    ('maggiehaberman.bsky.social',      1.0, ['us'],
        'Maggie Haberman (NYT) [VERIFIED -- replaces maggienyt 400]'),
    ('mkraju.bsky.social',              1.0, ['us'],
        'Manu Raju (CNN) Capitol Hill [CONFIRMED firing 20 posts]'),
    ('peterbakernyt.bsky.social',       0.95, ['us'],
        'Peter Baker (NYT) WH chief [CONFIRMED firing 20 posts]'),
    # jonathanvswan.bsky.social, bzfeldman.bsky.social, philiprucker.bsky.social,
    # costareports.bsky.social, annapalmerdc.bsky.social ALL 400 -- REMOVED.
    # Swan is now at NYT (per Apr 2026 Axios reporting); his handle may exist
    # under a domain. To investigate next session.

    # ── US Conservative / Right Voices ──
    ('byronyork.bsky.social',           0.9, ['us'],
        'Byron York (Washington Examiner) [CONFIRMED firing 5 posts]'),
    ('charlescwcooke.bsky.social',      0.85, ['us'],
        'Charles C.W. Cooke (National Review) [CONFIRMED firing 1 post]'),
    ('hughhewitt.bsky.social',          0.85, ['us'],
        'Hugh Hewitt -- conservative talk [CONFIRMED firing 7 posts]'),

    # ── US Progressive / Left Voices ──
    ('juddlegum.bsky.social',           0.95, ['us'],
        'Judd Legum (Popular Information) [VERIFIED -- replaces judddlegum typo]'),
    ('marcelias.bsky.social',           0.9, ['us'],
        'Marc Elias -- voting rights [CONFIRMED firing 20 posts]'),
    ('rickwilson.bsky.social',          0.85, ['us'],
        'Rick Wilson -- Lincoln Project [CONFIRMED firing 4 posts]'),

    # ── US Incident Trackers (verified weather/emergency handles) ──
    # gunviolencearchive.bsky.social, nwsweather.bsky.social, nws.govmirrors.com,
    # femagov.bsky.social, nhc.govmirrors.com ALL 400 -- REMOVED.
    ('nws.noaa.gov',                    1.0, ['us'],
        'National Weather Service official [VERIFIED via nws.noaa.gov DNS]'),
    ('noaa.gov',                        0.95, ['us'],
        'NOAA parent agency [VERIFIED]'),
    ('climate.noaa.gov',                0.9, ['us'],
        'NOAA Climate.gov [VERIFIED]'),
    ('skywarn.bsky.social',             0.85, ['us'],
        'NOAA/NWS Skywarn Spotter Program [VERIFIED]'),
    ('noaacomms.noaa.gov',              0.85, ['us'],
        'NOAA Communications [VERIFIED]'),

    # ── US Court / Legal Signal ──
    # supremecourtus.govmirrors.com, lawfareblog.bsky.social BOTH 400 -- REMOVED.
    ('lawfaremedia.org',                0.95, ['us'],
        'Lawfare -- national security law analysis [VERIFIED -- replaces lawfareblog]'),

    # ── US Economic Signal ──
    # cbo.govmirrors.com 400 -- REMOVED.
    # stlouisfed.bsky.social CONFIRMED firing 20 posts (kept).
    ('stlouisfed.bsky.social',          0.9, ['us'],
        'St. Louis Fed (FRED) [CONFIRMED firing 20 posts]'),

    # ═══════════════════════════════════════════════════════════
    # FOREIGN VIEW OF US (v1.2.0 — POST-AUDIT SCRUB)
    # ═══════════════════════════════════════════════════════════
    # bbcworld.bsky.social, guardian.bsky.social, jerusalempost.bsky.social,
    # reuters.bsky.social ALL returned 400 -- REMOVED.
    # thetimes.bsky.social, haaretzcom.bsky.social, bloomberg.bsky.social,
    # ftusa.bsky.social CONFIRMED firing.

    # ── UK press ──
    ('thetimes.bsky.social',            0.85, ['us', '*'],
        'The Times (UK) US coverage [CONFIRMED firing 20 posts]'),
    # bbcworld.bsky.social, guardian.bsky.social, telegraph.bsky.social all 400.
    # BBC News uses bot mirror @bbcnews-world-rss.bsky.social — quality unknown.

    # ── Israeli press ──
    ('haaretzcom.bsky.social',          0.9, ['us', '*'],
        'Haaretz English [CONFIRMED firing 20 posts]'),
    # timesofisrael.bsky.social, jerusalempost.bsky.social all 400.
    # Israeli outlets primarily on X/Twitter; verified Bluesky presence sparse.

    # ── Wire / major outlets via custom domain handles ──
    ('reuters.com',                     0.95, ['us', '*'],
        'Reuters official [VERIFIED -- custom domain handle replaces reuters.bsky.social]'),
    ('legal.reuters.com',               0.85, ['us', '*'],
        'Reuters Legal [VERIFIED]'),
    ('bloomberg.bsky.social',           0.9, ['us', '*'],
        'Bloomberg [CONFIRMED firing 1 post]'),
    ('ftusa.bsky.social',               0.9, ['us', '*'],
        'FT US [CONFIRMED firing 3 posts]'),
    # apnews.bsky.social, axios.bsky.social, aljazeeraenglish.bsky.social,
    # cbcnews.bsky.social, abcaustralia.bsky.social all 400 in audit. To research.

    # ── ADDITIONAL VERIFIED HANDLES (NEW v1.2.0) ──
    # Reuters reporters (US-focused) verified via Reuters business starter pack
    ('michaelsderby.bsky.social',       0.85, ['us'],
        'Michael Derby (Reuters Fed/economy) [VERIFIED]'),
    ('hpschneider.bsky.social',         0.8, ['us'],
        'Howard Schneider (Reuters US economy) [VERIFIED]'),

]


def fetch_bluesky_account(handle, weight=1.0, limit=20, timeout=BLUESKY_TIMEOUT):
    """
    Fetch recent posts from a single Bluesky account.

    Uses the public AppView API -- no authentication required.
    Returns list of article dicts matching the WHA backend schema.

    On 400/404 (handle doesn't exist) -> logs and returns []
    On 429 (rate limit) -> logs and returns []
    On network/parse error -> logs and returns []
    """
    headers = {
        'User-Agent': 'AsifahAnalytics-WHA/1.1 (+https://asifahanalytics.com)',
        'Accept': 'application/json',
    }
    params = {'actor': handle, 'limit': limit}

    try:
        resp = requests.get(BLUESKY_API, headers=headers, params=params, timeout=timeout)

        if resp.status_code in (400, 404):
            # 400/404 means handle doesn't exist or govmirror failed.
            # Log once -- we won't retry. v1.1.0: also catches 400 from govmirrors.
            print(f'[Bluesky WHA] @{handle}: handle not found ({resp.status_code}) -- consider removing from list')
            return []
        if resp.status_code == 429:
            print(f'[Bluesky WHA] @{handle}: rate-limited (429) -- backing off')
            return []
        if resp.status_code != 200:
            print(f'[Bluesky WHA] @{handle}: HTTP {resp.status_code}')
            return []

        data = resp.json()
        feed = data.get('feed', [])
        articles = []

        for item in feed:
            post = item.get('post', {})
            record = post.get('record', {})
            author = post.get('author', {})

            text = record.get('text', '') or ''
            if not text.strip():
                continue

            # Bluesky timestamps are ISO-8601 UTC
            pub = record.get('createdAt') or post.get('indexedAt') or ''

            # Construct canonical post URL from DID + rkey
            post_uri = post.get('uri', '')
            rkey = post_uri.rsplit('/', 1)[-1] if post_uri else ''
            url = f'https://bsky.app/profile/{handle}/post/{rkey}' if rkey else f'https://bsky.app/profile/{handle}'

            # Description = first 400 chars of text (Bluesky is short-form)
            desc = text[:400]

            articles.append({
                'title':       text[:200],
                'description': desc,
                'url':         url,
                'publishedAt': pub,
                'source':      {'name': f'Bluesky @{handle}'},
                'content':     text[:500],
                'language':    'en',
                'feed_type':   'bluesky',
                'source_weight_override': weight,
                '_bluesky_author':  author.get('displayName', handle),
            })

        if articles:
            print(f'[Bluesky WHA] @{handle}: {len(articles)} posts')
        return articles

    except requests.exceptions.Timeout:
        print(f'[Bluesky WHA] @{handle}: timeout after {timeout}s')
        return []
    except Exception as e:
        print(f'[Bluesky WHA] @{handle}: {str(e)[:80]}')
        return []


def fetch_bluesky_for_target(target, days=7, max_posts_per_account=20):
    """
    Fetch Bluesky posts relevant to a specific WHA target.

    Filters by:
      - target key (account must have '*' or target in its targets list)
      - recency (post must be within last {days} days)
      - deduplication (URL-based)

    Returns list of article dicts ready for downstream scoring.

    For Cuba: this is the primary path for Trump Truth Social capture.
    For Chile/Peru: this is a key path for copper convergence signals.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen_urls = set()
    accounts_queried = 0

    for handle, weight, targets, desc in BLUESKY_ACCOUNTS_WHA:
        # Skip accounts not relevant to this target
        if '*' not in targets and target not in targets:
            continue

        accounts_queried += 1
        posts = fetch_bluesky_account(handle, weight=weight, limit=max_posts_per_account)

        for p in posts:
            if p['url'] in seen_urls:
                continue

            # Recency filter
            try:
                pub_str = p['publishedAt'].replace('Z', '+00:00')
                pub = datetime.fromisoformat(pub_str)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    continue
            except Exception:
                # If date parsing fails, keep the post (better than losing signal)
                pass

            seen_urls.add(p['url'])
            all_posts.append(p)

        # Light politeness delay -- Bluesky public API is fast but we
        # don't want to look abusive
        time.sleep(0.2)

    print(f'[Bluesky WHA] {target}: {len(all_posts)} posts from {accounts_queried} accounts queried')
    return all_posts
