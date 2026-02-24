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

## Scripts & Tools Built
- **`scripts/cost-monitor.py`** — pulls API spend from local OpenClaw session logs + OpenAI usage API. Run manually to get today's spend. Also runs on cron for daily digest + $20 threshold alerts → posts to #tony-ops (C0AHBCJQJKS). Usage: `python3 scripts/cost-monitor.py` (current day) or `--digest` (yesterday's full report).

## Known Issues
- ~~**CLI/Gateway Token Mismatch**~~ → **RESOLVED 2026-02-22**: Approved pending repair request via `openclaw devices approve --latest --token <token>`. Gateway now shows `RPC probe: ok`. New instance runs as root user at `/root/.openclaw/`.
