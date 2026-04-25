"""
========================================
BLUESKY — Western Hemisphere Signal Monitor (v1.0.0)
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
    cuba, mexico, venezuela, colombia, brazil, panama, haiti, united_states
    Use ['*'] for accounts that are global (USG executive, all-WHA scope).
"""

import requests
import time
from datetime import datetime, timezone, timedelta

# Public AppView — no auth required for read-only
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
# weight:  1.2 = head of state direct (Trump, Diaz-Canel, Maduro)
#          1.1 = senior cabinet (Rubio = Cuban-American, primary signal)
#          1.0 = institutional / military command (SOUTHCOM, State Dept)
#          0.9 = analytical / OSINT / regional specialist
#          0.85 = partner/allied accounts
#
# targets: list of WHA backend target keys this account is relevant to.
#          WHA targets: cuba, mexico, venezuela, colombia, brazil,
#                       panama, haiti, united_states
#          Use ['*'] for all WHA targets (global USG scope).
# ────────────────────────────────────────────────────────────────
BLUESKY_ACCOUNTS_WHA = [
    # ── US Government — native Bluesky (global scope) ───────────
    ('state-department.bsky.social',    1.0, ['*'],
        'US State Department (official) — travel advisories, WHA policy'),

    # ── US Government — govmirrors.com (X / Truth Social sourced) ──
    # Trump Truth Social mirroring is the headline capability here.
    # POTUS account also mirrors significant WH executive content.
    ('potus.govmirrors.com',            1.2, ['*'],
        'POTUS (X mirror) — White House executive statements'),
    ('realdonaldtrump.govmirrors.com',  1.2, ['cuba', 'venezuela', 'mexico', 'panama', 'haiti', '*'],
        'Trump Truth Social (X mirror) — Cuba/Venezuela/Mexico/Panama statements; PRIMARY US signal source for Cuba'),
    ('secdef.govmirrors.com',           1.1, ['*'],
        'US SecDef (X mirror) — SOUTHCOM posture, deployment signals'),
    ('secrubio.govmirrors.com',         1.15, ['cuba', 'venezuela', 'colombia', '*'],
        'SecState Rubio (X mirror) — Cuban-American, PRIMARY signal for Cuba/Venezuela'),
    ('statedept.govmirrors.com',        0.9, ['*'],
        'StateDept (X mirror) — redundant with native, kept as backup'),

    # ── Regional Combatant Commands ─────────────────────────────
    ('southcom.govmirrors.com',         1.0, ['cuba', 'venezuela', 'colombia', 'panama', 'haiti'],
        'US SOUTHCOM (X mirror) — Caribbean/LatAm military posture'),
    ('northcom.govmirrors.com',         0.95, ['mexico', 'cuba'],
        'US NORTHCOM (X mirror) — border, Mexico, GTMO'),

    # ── US legislative / Cuba-specific senate ───────────────────
    ('marcorubio.govmirrors.com',       1.1, ['cuba', 'venezuela'],
        'Sen. Rubio (X mirror) — Cuba/Venezuela hawkish line, before SecState'),

    # ── Cuban regime accounts (if mirrored) ─────────────────────
    # Cuban gov is mostly NOT on Bluesky natively. Listed handles are
    # speculative — comment out if 404s appear in logs.
    ('diazcanelb.govmirrors.com',       1.2, ['cuba'],
        'Diaz-Canel (X mirror) — Cuban head of state'),
    ('cubaminrex.govmirrors.com',       1.0, ['cuba'],
        'Cuba MINREX (X mirror) — Cuban foreign ministry'),

    # ── Cuban dissident / independent media ─────────────────────
    # 14ymedio and CubaNet have native Bluesky presence
    ('14ymedio.bsky.social',            0.95, ['cuba'],
        '14ymedio (Yoani Sánchez) — leading Cuban dissident outlet'),
    ('cubanet.bsky.social',             0.9, ['cuba'],
        'CubaNet — dissident reporting, prisoner tracking'),
    ('diariodecuba.bsky.social',        0.9, ['cuba'],
        'Diario de Cuba — dissident outlet, arrest tracking'),

    # ── Venezuelan opposition / Latin America analysts ──────────
    ('mariacorinaya.govmirrors.com',    1.0, ['venezuela'],
        'María Corina Machado (X mirror) — Venezuelan opposition leader'),

    # ── Mexican government ──────────────────────────────────────
    ('claudiashein.govmirrors.com',     1.1, ['mexico'],
        'Claudia Sheinbaum (X mirror) — Mexican president'),
    ('sre-mexico.govmirrors.com',       0.9, ['mexico'],
        'Mexico SRE (X mirror) — foreign ministry'),

    # ── OSINT aggregators (global, high signal) ─────────────────
    ('osintdefender.bsky.social',       0.9, ['*'],
        'OSINT Defender — global conflict monitoring'),
    ('wartranslated.bsky.social',       0.8, ['*'],
        'WarTranslated — global military translation'),

    # ── WHA / LatAm analytical accounts ─────────────────────────
    ('americasquarterly.bsky.social',   0.85, ['cuba', 'venezuela', 'mexico', 'brazil', 'colombia'],
        'Americas Quarterly — WHA policy analysis'),
    ('hxiccg.bsky.social',              0.85, ['cuba', 'venezuela'],
        'Cuba/Venezuela analyst (if native)'),
]


def fetch_bluesky_account(handle, weight=1.0, limit=20, timeout=BLUESKY_TIMEOUT):
    """
    Fetch recent posts from a single Bluesky account.

    Uses the public AppView API — no authentication required.
    Returns list of article dicts matching the WHA backend schema.

    On 404 (handle doesn't exist) → logs and returns []
    On 429 (rate limit) → logs and returns []
    On network/parse error → logs and returns []
    """
    headers = {
        'User-Agent': 'AsifahAnalytics-WHA/1.0 (+https://asifahanalytics.com)',
        'Accept': 'application/json',
    }
    params = {'actor': handle, 'limit': limit}

    try:
        resp = requests.get(BLUESKY_API, headers=headers, params=params, timeout=timeout)

        if resp.status_code == 404:
            # 404 means handle doesn't exist. Log once — we won't retry.
            print(f'[Bluesky WHA] @{handle}: handle not found (404) — consider removing from list')
            return []
        if resp.status_code == 429:
            print(f'[Bluesky WHA] @{handle}: rate-limited (429) — backing off')
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

        # Light politeness delay — Bluesky public API is fast but we
        # don't want to look abusive
        time.sleep(0.2)

    print(f'[Bluesky WHA] {target}: {len(all_posts)} posts from {accounts_queried} accounts queried')
    return all_posts
