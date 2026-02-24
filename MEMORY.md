# MEMORY.md - Long-Term Memory

## Key Facts
- **Human:** Edu, San Diego (PST)
- **Business:** LinkedIn content agency for tech founders and execs
- **My role:** Starting as intern, growing toward COO
- **First boot:** 2026-02-21

## Preferences
- No filler, no apologies — results or questions only
- Risk framework: Low (auto), Medium (confirm), High (explicit GO)
- Gemini Flash for heartbeats, Claude Sonnet 4.6 as default, Opus 4 only when heavy reasoning needed
- **Security-first**: No elevated/root permissions. Server changes = Edu runs exact commands I provide. Long-term: narrow wrapper scripts for specific approved tasks only.

## Setup Backlog
All pending setup/config/skills tasks live in `SETUP.md`. Check it whenever Edu is at a terminal ready to work on configuration.

## API Keys in .env
- `OPENAI_API_KEY` — OpenAI (Whisper, etc.)
- `BRAVE_API_KEY` — Brave web search
- `XAI_API_KEY` — xAI Grok API (added 2026-02-23) — enables Grok models + Live Search (X search + web)

## Scripts & Tools Built
- **`scripts/xsearch.py`** — Search X/Twitter posts or web via Grok Live Search. Usage: `python3 scripts/xsearch.py "query"` (X), `--web`, or `--both`. Returns real-time results with citations.
- **`scripts/xread.py`** — Read & summarize a specific X post URL using Grok. Usage: `python3 scripts/xread.py <url>`.
- **`scripts/cost-monitor.py`** — pulls API spend from local OpenClaw session logs + OpenAI usage API. Run manually to get today's spend. Also runs on cron for daily digest + $20 threshold alerts → posts to #tony-ops (C0AHBCJQJKS). Usage: `python3 scripts/cost-monitor.py` (current day) or `--digest` (yesterday's full report).

## Known Issues
- ~~**CLI/Gateway Token Mismatch**~~ → **RESOLVED 2026-02-22**: Approved pending repair request via `openclaw devices approve --latest --token <token>`. Gateway now shows `RPC probe: ok`. New instance runs as root user at `/root/.openclaw/`.
