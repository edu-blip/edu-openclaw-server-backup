# Content Radar

Proactive trend intelligence for Edu's LinkedIn content strategy. Monitors X/Twitter, Reddit, and news every 4 hours. Posts high-relevance alerts to `#alec-content` with a scored summary and a ready-to-use hook.

## What It Does

Every 4 hours:
1. **Fetches** recent posts from 50 curated X accounts (AI researchers, VCs, founders, operators)
2. **Fetches** hot posts from 8 Reddit communities (r/startups, r/YCombinator, r/MachineLearning, etc.)
3. **Searches** Brave web for breaking AI/startup news (rotating query set)
4. **Scores** all fresh candidates with Gemini Flash against Edu's 5 content pillars (1–10)
5. **Posts** up to 3 alerts (score ≥ 7) to `#alec-content` with a draft hook

## Alert Format

```
🔥 Content Radar [X/Twitter] · Score: 9/10

*The insight or headline*
_@handle_
<link>

Why this is relevant: one sentence

Draft hook for your take:
_Hook line using Nicolas Cole framework_

Reply "develop this" to get the full post drafted.
```

## Config

- `scripts/content-radar-config.json` — all X accounts, subreddits, search queries, scoring pillars, and delivery settings
- To add/remove accounts: edit `x_accounts` in the config JSON — no code changes needed
- To change the alert threshold: edit `scoring.min_alert_score` (default: 7)
- To change the max alerts per run: edit `MAX_ALERTS_PER_RUN` at the top of `content-radar.js` (default: 3)

## Monitored X Accounts (50 total)

Seeded from Edu's 10 initial accounts. Expanded into 4 categories:
- **AI Researchers** (10): Karpathy, Sam Altman, Greg Brockman, Dario Amodei, Yann LeCun, François Chollet, Ethan Mollick, Simon Willison, Jeremy Howard, Demis Hassabis
- **AI Content Creators** (7): Matthew Berman, steipete, swyx, The Rundown AI, Ben Tossell, Pieter Levels, Dan Shipper
- **VCs/Investors** (15): pmarca, chamath, David Sacks, Turner Novak, Geiger Capital, Paul Graham, Garry Tan, Michael Seibel, Naval, Jason Calacanis, Benedict Evans, a16z, Brad Feld, Semil Shah, Hunter Walk
- **Founders/Operators** (12): Dharmesh Shah, Aaron Levie, Sahil Lavingia, Shreyas Doshi, Jason Lemkin, Aakash Gupta, Greg Isenberg, Alex Hormozi, Dave Gerhardt, Hiten Shah, Daniel Vassallo, Business Barista
- **Startup Ecosystem** (4): YCombinator, TechCrunch, First Round, Sequoia

## Models & Cost

| Task | Model | Frequency |
|------|-------|-----------|
| X monitoring | grok-4-1-fast-non-reasoning | ~4 calls/run (batched 12 accounts) |
| Scoring & hooks | gemini-3-flash-preview | 1 call/run |

Estimated cost: ~$0.10–0.20/run, ~$0.60–1.20/day. All costs logged to `logs/direct-api-costs.jsonl`.

## Schedule

```
0 */4 * * *  # Every 4 hours (midnight, 4am, 8am, noon, 4pm, 8pm PST)
```

## Manual Run

```bash
# Live run
node scripts/content-radar.js

# Dry run (score + print, no Slack posts)
node scripts/content-radar.js --dry
```

## Files

| File | Purpose |
|------|---------|
| `scripts/content-radar.js` | Main script |
| `scripts/content-radar-config.json` | All configuration |
| `logs/content-radar-state.json` | Dedup state (auto-created, 7-day TTL) |
| `/home/openclaw/logs/content-radar.log` | Runtime log |

## "Develop This" Flow

When Edu replies "develop this" to an alert, Alec will write the full post. This currently requires a manual Slack message to Alec — a webhook-based auto-handler is planned as a follow-up build.
