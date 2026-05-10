"""
========================================
REDDIT — United States Signal Monitor (v1.0.0)
========================================
US stability signal collection from Reddit. Reddit is among the highest-value
US-domestic OSINT signal vectors because:

  1. Real-time crowdsourced incident reporting (active shooters, severe weather,
     local civil unrest) often reaches r/news + r/politics within minutes
  2. Cross-spectrum political voices (r/politics, r/Conservative, r/Liberal,
     r/centrist, r/moderatepolitics) enable balanced rhetoric capture
  3. Specialist subs surface signals mainstream press misses (r/CredibleDefense,
     r/cybersecurity, r/ReadyMadeOSINT, r/economy, r/MassShootings)
  4. Reddit's public JSON API is auth-free for read-only access — no bot
     account, no OAuth dance, no rate-limit ceiling for reasonable use

API ENDPOINTS USED (no auth required):
    https://www.reddit.com/r/{subreddit}/hot.json?limit={N}    -- hot posts
    https://www.reddit.com/r/{subreddit}/new.json?limit={N}    -- chronological
    https://www.reddit.com/r/{subreddit}/top.json?t=day&limit={N}  -- top of day

Returns same article-dict shape as RSS/GDELT/NewsAPI:
    {title, description, link, published, source, source_type}
where source_type='reddit' and source=f'reddit/r/{subreddit}'.

────────────────────────────────────────────────────────────────────────
COVERAGE STRATEGY (v1.0.0)
────────────────────────────────────────────────────────────────────────
Subreddits grouped by stability dimension they feed:

  CIVIL/SOCIAL: r/news, r/MassShootings, r/PublicFreakout, r/weather,
                r/protest, r/ProtestFinderUSA, r/Crime
  POLITICAL:    r/politics, r/Conservative, r/Liberal, r/Centrist,
                r/moderatepolitics, r/AskAnAmerican, r/PoliticalDiscussion
  DEMOCRATIC:   r/scotus, r/law, r/legaladvice, r/lawofficer,
                r/CivilRights, r/Anarchism (constitutional fringe)
  MILITARY:     r/CredibleDefense, r/Military, r/army, r/usmc,
                r/AirForce, r/navy, r/Veterans
  ECONOMIC:     r/economy, r/Economics, r/finance, r/realestate,
                r/personalfinance, r/StockMarket, r/wallstreetbets
  CYBER/INFRA:  r/cybersecurity, r/netsec, r/sysadmin, r/blackhat,
                r/PowerSystems

PRINCIPLE: balance left/right/center where possible. r/politics leans left;
balance with r/Conservative + r/centrist. Asifah is apolitical; we capture
all sides to score stability honestly.

PRINCIPLE: prefer hot+new over top — we want emerging signals, not
yesterday's most-upvoted. Top posts skew toward viral content rather than
emerging stress signals.
"""

import requests
import time
import os
from datetime import datetime, timezone, timedelta


# ────────────────────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────────────────────
REDDIT_BASE = "https://www.reddit.com"
REDDIT_TIMEOUT = 8        # connect+read timeout per subreddit fetch

# User-Agent is REQUIRED by Reddit; without one they 429 immediately.
# Reddit policy: include an identifying name + version + project URL.
REDDIT_UA = (
    "AsifahAnalytics/1.0 (+https://www.asifahanalytics.com; OSINT geopolitical "
    "stability monitoring; contact via site)"
)

# Politeness delay between subreddit fetches to stay well under rate limits.
# Reddit's documented limit is 60/min for OAuth, ~10/min for unauthenticated.
# We pace at 1/sec to stay comfortably under unauthenticated ceiling.
REDDIT_PACING = 1.0


# ────────────────────────────────────────────────────────────────
# SUBREDDIT DIRECTORY — US STABILITY
# ────────────────────────────────────────────────────────────────
# (subreddit_name, weight, dimension_tags[], fetch_mode, description)
#
# weight:  1.2 = primary signal source for that dimension
#          1.0 = strong signal source
#          0.9 = supplemental signal
#          0.85 = specialist / niche
#          0.80 = noise-prone but worth scanning
#
# dimension_tags: which stability dimensions this sub feeds
#   civil_social | political | democratic | military | economic | cyber
#   '*' = relevant across all dimensions (e.g. r/news, r/politics)
#
# fetch_mode:
#   'hot'  — top of feed right now (default; best for emerging signals)
#   'new'  — strictly chronological (best for breaking events)
#   'top_day' — most upvoted in last 24hrs (best for civil/social trends)
#
# STATUS GLOSSARY:
#   [CONFIRMED]   Verified responsive in initial deploy
#   [SPECULATIVE] Architectural inclusion; will silently skip if 404
# ────────────────────────────────────────────────────────────────

REDDIT_SUBS_US = [

    # ═══════════════════════════════════════════════════════════
    # GENERAL US NEWS — primary signal source across all dimensions
    # ═══════════════════════════════════════════════════════════
    ('news',                   1.2, ['*'],          'hot',
        'r/news -- breaking US news, mass casualty events, severe weather [CONFIRMED]'),
    ('news',                   1.2, ['*'],          'new',
        'r/news (new) -- breaking events not yet hot [CONFIRMED]'),
    ('worldnews',              1.0, ['*'],          'hot',
        'r/worldnews -- foreign view of US, often catches signals US press misses [CONFIRMED]'),
    ('UpliftingNews',          0.7, ['*'],          'hot',
        'r/UpliftingNews -- noise filter; counter-balance to negative-only feed [CONFIRMED]'),

    # ═══════════════════════════════════════════════════════════
    # POLITICAL COHESION — cross-spectrum balance is critical
    # ═══════════════════════════════════════════════════════════
    ('politics',               1.0, ['political', 'democratic'], 'hot',
        'r/politics -- left-leaning US politics, very high volume [CONFIRMED]'),
    ('politics',               0.9, ['political', 'democratic'], 'new',
        'r/politics (new) -- chronological politics feed [CONFIRMED]'),
    ('Conservative',           1.0, ['political', 'democratic'], 'hot',
        'r/Conservative -- right-leaning balance to r/politics [CONFIRMED]'),
    ('Liberal',                0.9, ['political'],  'hot',
        'r/Liberal -- explicit liberal community [SPECULATIVE]'),
    ('moderatepolitics',       0.95, ['political'], 'hot',
        'r/moderatepolitics -- moderated cross-spectrum discussion [CONFIRMED]'),
    ('centrist',               0.85, ['political'], 'hot',
        'r/centrist -- center-balance perspective [CONFIRMED]'),
    ('PoliticalDiscussion',    0.85, ['political'], 'hot',
        'r/PoliticalDiscussion -- structured political analysis [CONFIRMED]'),
    ('AskAnAmerican',          0.75, ['political'], 'hot',
        'r/AskAnAmerican -- foreign perception of US conditions [CONFIRMED]'),
    ('AmericanPolitics',       0.85, ['political'], 'hot',
        'r/AmericanPolitics -- cross-spectrum politics [SPECULATIVE]'),
    ('republicans',            0.85, ['political'], 'hot',
        'r/republicans -- alt right-leaning sub [SPECULATIVE]'),
    ('democrats',              0.85, ['political'], 'hot',
        'r/democrats -- alt left-leaning sub [SPECULATIVE]'),
    ('libertarian',            0.80, ['political'], 'hot',
        'r/libertarian -- libertarian perspective [SPECULATIVE]'),

    # ═══════════════════════════════════════════════════════════
    # CIVIL/SOCIAL STABILITY — incident-driven signal
    # ═══════════════════════════════════════════════════════════
    ('PublicFreakout',         0.9, ['civil_social'], 'hot',
        'r/PublicFreakout -- civil unrest, viral incidents (filter for noise) [CONFIRMED]'),
    ('MassShootings',          1.1, ['civil_social'], 'new',
        'r/MassShootings -- specialist tracker (high signal density) [SPECULATIVE]'),
    ('GunPolitics',            0.85, ['civil_social', 'political'], 'hot',
        'r/GunPolitics -- balanced gun policy discussion [CONFIRMED]'),
    ('weather',                0.95, ['civil_social'], 'hot',
        'r/weather -- severe weather warnings, hurricane/tornado tracking [CONFIRMED]'),
    ('TropicalWeather',        0.95, ['civil_social'], 'hot',
        'r/TropicalWeather -- hurricane specialist sub [CONFIRMED]'),
    ('WildfireScanner',        0.9, ['civil_social'], 'new',
        'r/WildfireScanner -- wildfire specialist [SPECULATIVE]'),
    ('Tornado',                0.85, ['civil_social'], 'hot',
        'r/Tornado -- severe weather specialist [SPECULATIVE]'),
    ('Crime',                  0.85, ['civil_social'], 'hot',
        'r/Crime -- US crime/violent incident reporting [SPECULATIVE]'),
    ('TrueCrime',              0.75, ['civil_social'], 'hot',
        'r/TrueCrime -- supplemental crime reporting (some entertainment skew) [CONFIRMED]'),
    ('protest',                0.95, ['civil_social', 'political'], 'hot',
        'r/protest -- protest activity tracker [SPECULATIVE]'),
    ('Anarchism',              0.7, ['civil_social', 'political'], 'hot',
        'r/Anarchism -- fringe political activity signal [CONFIRMED]'),

    # ═══════════════════════════════════════════════════════════
    # DEMOCRATIC INSTITUTIONS — court / law / civil rights
    # ═══════════════════════════════════════════════════════════
    ('scotus',                 1.0, ['democratic'], 'hot',
        'r/scotus -- Supreme Court decisions + analysis [CONFIRMED]'),
    ('law',                    0.95, ['democratic'], 'hot',
        'r/law -- legal news + court decisions [CONFIRMED]'),
    ('Lawyertalk',             0.85, ['democratic'], 'hot',
        'r/Lawyertalk -- practitioner perspective on legal events [SPECULATIVE]'),
    ('legaladvice',            0.7, ['democratic'], 'hot',
        'r/legaladvice -- ground-truth signal of civil rights/access concerns [CONFIRMED]'),
    ('CivilRights',            0.95, ['democratic'], 'hot',
        'r/CivilRights -- civil rights organizing + violations [SPECULATIVE]'),
    ('Constitution',           0.85, ['democratic'], 'hot',
        'r/Constitution -- constitutional law discussion [SPECULATIVE]'),
    ('voting',                 0.9, ['democratic'], 'hot',
        'r/voting -- election integrity discussion [SPECULATIVE]'),
    ('inthenews',              0.85, ['democratic', '*'], 'hot',
        'r/inthenews -- news aggregator with discussion [SPECULATIVE]'),

    # ═══════════════════════════════════════════════════════════
    # MILITARY POSTURE — service members + analysts
    # ═══════════════════════════════════════════════════════════
    ('CredibleDefense',        1.1, ['military'],  'hot',
        'r/CredibleDefense -- gold-standard military analysis [CONFIRMED]'),
    ('LessCredibleDefence',    0.85, ['military'], 'hot',
        'r/LessCredibleDefence -- companion sub for less-strict discussion [CONFIRMED]'),
    ('Military',               0.9, ['military'],  'hot',
        'r/Military -- general military discussion [CONFIRMED]'),
    ('army',                   0.85, ['military'], 'hot',
        'r/army -- US Army community [CONFIRMED]'),
    ('USMC',                   0.85, ['military'], 'hot',
        'r/USMC -- US Marine Corps [CONFIRMED]'),
    ('AirForce',               0.85, ['military'], 'hot',
        'r/AirForce -- US Air Force [CONFIRMED]'),
    ('navy',                   0.85, ['military'], 'hot',
        'r/navy -- US Navy [CONFIRMED]'),
    ('NationalGuard',          0.9, ['military', 'civil_social'], 'hot',
        'r/NationalGuard -- domestic deployment signal [CONFIRMED]'),
    ('Veterans',               0.85, ['military'], 'hot',
        'r/Veterans -- veterans community [CONFIRMED]'),
    ('warcollege',             0.95, ['military'], 'hot',
        'r/warcollege -- doctrine + strategic analysis [CONFIRMED]'),

    # ═══════════════════════════════════════════════════════════
    # ECONOMIC STABILITY — markets, finance, household conditions
    # ═══════════════════════════════════════════════════════════
    ('economy',                1.0, ['economic'],  'hot',
        'r/economy -- US economic news + analysis [CONFIRMED]'),
    ('Economics',              1.0, ['economic'],  'hot',
        'r/Economics -- economic analysis [CONFIRMED]'),
    ('finance',                0.9, ['economic'],  'hot',
        'r/finance -- financial markets + policy [CONFIRMED]'),
    ('StockMarket',            0.85, ['economic'], 'hot',
        'r/StockMarket -- market sentiment [CONFIRMED]'),
    ('investing',              0.85, ['economic'], 'hot',
        'r/investing -- investment community [CONFIRMED]'),
    ('wallstreetbets',         0.75, ['economic'], 'hot',
        'r/wallstreetbets -- retail-trader sentiment + meme finance [CONFIRMED]'),
    ('realestate',             0.85, ['economic'], 'hot',
        'r/realestate -- housing market signal [CONFIRMED]'),
    ('personalfinance',        0.80, ['economic'], 'hot',
        'r/personalfinance -- household financial stress signals [CONFIRMED]'),
    ('povertyfinance',         0.85, ['economic', 'civil_social'], 'hot',
        'r/povertyfinance -- low-income household stress (high signal value) [CONFIRMED]'),
    ('antiwork',               0.80, ['economic', 'political'], 'hot',
        'r/antiwork -- labor market dissent signal [CONFIRMED]'),
    ('layoffs',                0.95, ['economic'], 'hot',
        'r/layoffs -- US layoff tracker (specialist) [CONFIRMED]'),
    ('jobs',                   0.80, ['economic'], 'hot',
        'r/jobs -- labor market sentiment [CONFIRMED]'),
    ('Recession',              0.95, ['economic'], 'hot',
        'r/Recession -- recession signal sub [SPECULATIVE]'),
    ('inflation',              0.95, ['economic'], 'hot',
        'r/inflation -- inflation discussion (sentiment proxy) [SPECULATIVE]'),

    # ═══════════════════════════════════════════════════════════
    # CYBER / INFRASTRUCTURE
    # ═══════════════════════════════════════════════════════════
    ('cybersecurity',          1.05, ['cyber'],    'hot',
        'r/cybersecurity -- security incident reporting [CONFIRMED]'),
    ('netsec',                 1.05, ['cyber'],    'hot',
        'r/netsec -- network security professional sub [CONFIRMED]'),
    ('sysadmin',               0.85, ['cyber'],    'hot',
        'r/sysadmin -- infrastructure outage reports [CONFIRMED]'),
    ('blackhat',               0.85, ['cyber'],    'hot',
        'r/blackhat -- adversarial cyber discussion [SPECULATIVE]'),
    ('Hacking',                0.80, ['cyber'],    'hot',
        'r/Hacking -- hacking community [CONFIRMED]'),
    ('AskNetsec',              0.80, ['cyber'],    'hot',
        'r/AskNetsec -- security Q&A community [CONFIRMED]'),
    ('cybersecurity_news',     0.95, ['cyber'],    'new',
        'r/cybersecurity_news -- specialist news sub [SPECULATIVE]'),
    ('PowerSystems',           0.85, ['cyber'],    'hot',
        'r/PowerSystems -- electrical grid + infrastructure [SPECULATIVE]'),
    ('aviation',               0.80, ['cyber', 'civil_social'], 'hot',
        'r/aviation -- airspace + flight disruption signals [CONFIRMED]'),

    # ═══════════════════════════════════════════════════════════
    # SPECIALIST / OSINT
    # ═══════════════════════════════════════════════════════════
    ('OSINT',                  0.95, ['*'],         'hot',
        'r/OSINT -- open-source intelligence community [CONFIRMED]'),
    ('PropagandaPosters',      0.7, ['political'], 'hot',
        'r/PropagandaPosters -- historical context for current political imagery [CONFIRMED]'),
    ('KremlinFiles',           0.8, ['political', 'military'], 'hot',
        'r/KremlinFiles -- foreign-influence tracking [SPECULATIVE]'),
    ('VATC',                   0.85, ['political'], 'hot',
        'r/VATC (Volunteers Against Trump Cabinet) -- specialist accountability [SPECULATIVE]'),
    ('NeutralPolitics',        1.0, ['political', 'democratic'], 'hot',
        'r/NeutralPolitics -- moderated fact-based politics [CONFIRMED]'),
    ('NeutralNews',            0.95, ['*'],         'hot',
        'r/NeutralNews -- moderated fact-based news [CONFIRMED]'),
]


# ────────────────────────────────────────────────────────────────
# FETCH HELPERS
# ────────────────────────────────────────────────────────────────

def _fetch_subreddit(subreddit, mode='hot', weight=1.0, limit=25, timeout=REDDIT_TIMEOUT):
    """
    Fetch posts from a single subreddit via Reddit's public JSON API.

    Args:
        subreddit: subreddit name without 'r/' prefix
        mode: 'hot', 'new', or 'top_day'
        weight: signal weight (carried through for downstream scoring)
        limit: max posts to fetch (Reddit caps at 100)
        timeout: per-request timeout

    Returns list of article dicts in the WHA backend schema. Returns [] on
    any failure (HTTP error, rate-limit, network issue) so caller can keep
    going through the rest of the subreddit list.
    """
    # Build URL based on mode
    if mode == 'top_day':
        url = f'{REDDIT_BASE}/r/{subreddit}/top.json?t=day&limit={limit}'
    elif mode == 'new':
        url = f'{REDDIT_BASE}/r/{subreddit}/new.json?limit={limit}'
    else:  # default 'hot'
        url = f'{REDDIT_BASE}/r/{subreddit}/hot.json?limit={limit}'

    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={'User-Agent': REDDIT_UA, 'Accept': 'application/json'},
        )
        if resp.status_code == 429:
            print(f"[Reddit US] r/{subreddit}: rate-limited")
            return []
        if resp.status_code in (403, 404):
            # Sub doesn't exist or is private — silent skip
            return []
        if resp.status_code != 200:
            print(f"[Reddit US] r/{subreddit} ({mode}): HTTP {resp.status_code}")
            return []

        data = resp.json()
        children = (data.get('data') or {}).get('children') or []

        articles = []
        for child in children:
            post = child.get('data') or {}

            # Skip stickied posts (mod announcements, not signal)
            if post.get('stickied'):
                continue

            title = post.get('title') or ''
            if not title:
                continue

            # Reddit gives created_utc as a unix timestamp
            created_utc = post.get('created_utc')
            if created_utc:
                try:
                    pub_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                    pub_str = pub_dt.isoformat()
                except Exception:
                    pub_str = ''
            else:
                pub_str = ''

            # Reddit "selftext" = post body if it's a self-post
            selftext = post.get('selftext') or ''
            # Truncate long selftext to keep payload manageable
            if len(selftext) > 1000:
                selftext = selftext[:1000] + '...'

            # Permalink = canonical URL on reddit.com (always works)
            # url = external link if linked post; permalink for self-posts
            permalink = post.get('permalink') or ''
            external_url = post.get('url') or ''
            link = (
                f'https://www.reddit.com{permalink}'
                if permalink else
                external_url
            )

            articles.append({
                'title':       title.strip(),
                'description': selftext.strip(),
                'link':        link,
                'published':   pub_str,
                'source':      f'reddit/r/{subreddit}',
                'source_type': 'reddit',
                # Optional metadata for downstream debugging / analytics:
                'reddit_score':     post.get('score', 0),
                'reddit_num_comments': post.get('num_comments', 0),
                'reddit_subreddit': subreddit,
                'reddit_weight':    weight,
                'reddit_mode':      mode,
            })

        return articles

    except requests.exceptions.Timeout:
        print(f"[Reddit US] r/{subreddit} ({mode}): timeout")
        return []
    except Exception as e:
        print(f"[Reddit US] r/{subreddit} ({mode}): error {str(e)[:120]}")
        return []


# ────────────────────────────────────────────────────────────────
# PUBLIC FETCH FUNCTION
# ────────────────────────────────────────────────────────────────

def fetch_reddit_signals_us(days=7, max_per_sub=25):
    """
    Fetch US stability signals from all configured subreddits.

    Args:
        days: recency cutoff in days (older posts filtered out)
        max_per_sub: max posts to pull per subreddit (Reddit caps at 100)

    Returns deduplicated list of article dicts ready for downstream scoring.
    Articles outside the recency window are dropped. Articles with empty
    titles are dropped. Duplicates by URL are collapsed.

    Tagged with source='reddit/r/{name}' and source_type='reddit' so the
    frontend news tabs can bucket them into the Reddit tab and the dimension
    scorers can detect them as social signals.

    Architecture note:
        This function is called by us_stability.py's run_stability_scan()
        alongside _fetch_rss / _fetch_gdelt / _fetch_newsapi. Treat its
        return value the same way (extend all_articles).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_articles = []
    seen_urls = set()
    subs_queried = 0
    total_filtered_recency = 0

    print(f"[Reddit US] Starting scan -- {len(REDDIT_SUBS_US)} (sub, mode) pairs, days={days}")

    for entry in REDDIT_SUBS_US:
        subreddit, weight, dim_tags, mode, desc = entry
        subs_queried += 1

        posts = _fetch_subreddit(
            subreddit, mode=mode, weight=weight, limit=max_per_sub
        )

        for p in posts:
            # Recency filter
            try:
                pub = p.get('published', '')
                if pub:
                    pub_dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        total_filtered_recency += 1
                        continue
            except Exception:
                # If date parsing fails, keep the post (better than losing signal)
                pass

            # URL-based dedup
            link = p.get('link', '')
            if link and link in seen_urls:
                continue
            if link:
                seen_urls.add(link)

            all_articles.append(p)

        # Politeness pacing — stay well under Reddit's unauth rate limit
        time.sleep(REDDIT_PACING)

    print(
        f"[Reddit US] Done: {len(all_articles)} posts kept "
        f"from {subs_queried} subs queried "
        f"({total_filtered_recency} filtered by recency, "
        f"{subs_queried - len(set(e[0] for e in REDDIT_SUBS_US))} dup mode-pairs)"
    )
    return all_articles


# ────────────────────────────────────────────────────────────────
# HEALTH CHECK
# ────────────────────────────────────────────────────────────────

def get_reddit_us_status():
    """Diagnostics for /debug endpoint visibility."""
    unique_subs = set(e[0] for e in REDDIT_SUBS_US)
    by_dim = {}
    for sub, weight, tags, mode, desc in REDDIT_SUBS_US:
        for t in tags:
            by_dim[t] = by_dim.get(t, 0) + 1
    return {
        'module':           'reddit_signals_us',
        'version':          '1.0.0',
        'total_entries':    len(REDDIT_SUBS_US),
        'unique_subs':      len(unique_subs),
        'sub_mode_pairs':   len(REDDIT_SUBS_US),
        'pacing_seconds':   REDDIT_PACING,
        'auth_required':    False,
        'dimension_coverage': by_dim,
        'estimated_scan_seconds': int(len(REDDIT_SUBS_US) * REDDIT_PACING) + 5,
    }


# ────────────────────────────────────────────────────────────────
# DEBUG / STANDALONE TEST
# ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Quick smoke test — fetch a single subreddit
    import json
    print("=" * 60)
    print("REDDIT US SIGNAL MODULE — STANDALONE TEST")
    print("=" * 60)
    status = get_reddit_us_status()
    print(json.dumps(status, indent=2))
    print()
    print("Test fetch from r/news (hot, limit=5)...")
    posts = _fetch_subreddit('news', mode='hot', limit=5)
    print(f"Got {len(posts)} posts")
    for p in posts[:3]:
        print(f"  [{p['source']}] {p['title'][:80]}")
        print(f"    score={p.get('reddit_score')} comments={p.get('reddit_num_comments')}")
