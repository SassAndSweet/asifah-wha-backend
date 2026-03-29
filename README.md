# asifah-wha-backend

**Asifah Analytics — Western Hemisphere Backend**
`v1.0.0 | March 2026`

Flask backend service powering the Western Hemisphere regional dashboard for [Asifah Analytics](https://asifahanalytics.com) — a personal-time, non-commercial, open-source OSINT geopolitical intelligence platform.

---

## Overview

This service covers SOUTHCOM area countries and actors:

| Country | Tier | Focus |
|---|---|---|
| 🇻🇪 Venezuela | Tier 2 | Post-Maduro transition, US DEA/military involvement, narco-military nexus |
| 🇨🇺 Cuba | Tier 2 | Regime stability, Russian/Chinese naval presence, protest suppression |
| 🇭🇹 Haiti | Tier 2 | MSS gang control (de facto military actor), Kenyan security mission |
| 🇵🇦 Panama | Tier 3 | Panama Canal security, Chinese port presence, Darien Gap |
| 🇨🇴 Colombia | Tier 3 | ELN/FARC dissidents, US military advisors, Venezuela border |
| 🇲🇽 Mexico | Tier 3 | Cartel military operations (inward-facing), US border posture |
| 🇧🇷 Brazil | Tier 3 | Regional power, Amazon military operations, organized crime |

---

## Tech Stack

- **Runtime:** Python 3.x / Flask
- **Hosting:** Render (paid $7/mo tier)
- **Start command:** `gunicorn app:app --timeout 300 --workers 2`
- **Cache:** Upstash Redis (shared instance across all Asifah backends)
- **Data sources:** GDELT, NewsAPI, Google News RSS, Reddit

---

## Environment Variables

Set these in Render before deploying:

| Variable | Description |
|---|---|
| `UPSTASH_REDIS_URL` | Upstash Redis REST URL (shared across all backends) |
| `UPSTASH_REDIS_TOKEN` | Upstash Redis Bearer token |
| `NEWSAPI_KEY` | NewsAPI.org API key |

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/wha/stability/<country>` | Stability score and assessment for a country |
| `GET /api/wha/stability/<country>?force=true` | Force cache refresh |
| `GET /api/wha/threat/<country>` | Threat probability for a country |
| `GET /api/wha/threat/<country>?force=true` | Force threat rescan |
| `GET /api/rhetoric/wha/<country>` | Rhetoric tracker data |
| `GET /health` | Service health check |

**Supported country slugs:** `venezuela`, `cuba`, `haiti`, `panama`, `colombia`, `mexico`, `brazil`

---

## Architecture

Follows the standard Asifah Analytics backend pattern:

- Background refresh threads (4-6 hour cycles, `daemon=True`, 60-120s boot delay)
- Redis-first caching with `/tmp` file fallback
- `?force=true` cache bypass on all endpoints
- Per-country stability scoring: 0-100 composite with rhetoric penalty
- Gunicorn `--timeout 300` required for full scan duration

See [asifah_architecture.docx](https://github.com/SassAndSweet/asifah-analytics) for full platform architecture documentation.

---

## Deployment

1. Push to `main` branch
2. Render auto-deploys on push
3. Verify start command: `gunicorn app:app --timeout 300 --workers 2`
4. Set environment variables in Render dashboard
5. Test with: `https://asifah-wha-backend.onrender.com/health`
6. Force first scan: `https://asifah-wha-backend.onrender.com/api/wha/stability/venezuela?force=true`

Cold starts take 30-60s after inactivity on the free/starter tier.

---

## Related Services

| Service | URL | Coverage |
|---|---|---|
| ME Backend | `asifah-backend.onrender.com` | Iran, Iraq, Lebanon, Syria, Yemen, Israel, Gulf |
| Europe Backend | `asifah-europe-backend.onrender.com` | Ukraine, Russia, Poland, Greenland |
| Asia Backend | `asifah-asia-backend.onrender.com` | China, Taiwan |
| WHA Backend | `asifah-wha-backend.onrender.com` | This service |

---

## License

See `LICENSE` file. Not for operational use.
Built and maintained independently by RCGG in personal time.

*Asifah Analytics © 2025-2026 RCGG. All rights reserved.*
