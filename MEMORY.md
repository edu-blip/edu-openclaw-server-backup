# MEMORY.md - Long-Term Memory

## Key Facts
- **Human:** Edu, San Diego (PST)
- **Business:** LinkedIn content agency for tech founders and execs
- **My role:** Starting as intern, growing toward COO
- **First boot:** 2026-02-21

## Preferences
- No filler, no apologies — results or questions only
- Risk framework: Low (auto), Medium (confirm), High (explicit GO)
- Gemini Flash for heartbeats, Claude Sonnet 4.6 as default, Opus 4.6 only when heavy reasoning needed
- **Security-first**: No elevated/root permissions. Server changes = Edu runs exact commands I provide. Long-term: narrow wrapper scripts for specific approved tasks only.

## Setup Backlog
All pending setup/config/skills tasks live in `SETUP.md`. Check it whenever Edu is at a terminal ready to work on configuration.

## API Keys in .env
- `OPENAI_API_KEY` — OpenAI (Whisper, etc.)
- `BRAVE_API_KEY` — Brave web search
- `XAI_API_KEY` — xAI Grok API (added 2026-02-23) — enables Grok models + Live Search (X search + web)

## Fathom Integration (built 2026-02-24)
- **Webhook server**: `/root/.openclaw/workspace/fathom/webhook-server.js` on port 8001
  - Systemd service: `fathom-webhook.service` (enabled + running)
  - Caddy routes `https://167.99.162.160/fathom-webhook` → port 8001
  - Verifies Fathom HMAC signatures using `FATHOM_WEBHOOK_SECRET`
- **Processor**: `/root/.openclaw/workspace/fathom/processor.js`
  - **Call classifier**: routes by meeting title keywords + attendee domains
  - **Use Case A** (weekly check-in → Asana): STUB — awaiting Asana + Google Calendar API keys
  - **Use Case B** (client interview feedback → Slack): functional, needs `clientFeedbackSlackChannel` in config.json
  - **Use Case C** (Edu LinkedIn content ideas → weekly Google Doc): accumulates to JSON, Google Doc creation pending Google Workspace keys
- **Config**: `/root/.openclaw/workspace/fathom/config.json`
  - `internalDomains`: `["rethoric.co", "rethoric.com"]` ✅
  - `clientFeedbackSlackChannel`: `C0AGYTU4N9Y` (#client-feedback) ✅
  - Internal title: "team check-in" ✅
  - Client interview titles: "content interview", "rethoric interview", "content call" ✅
  - Classification: title-match only (external attendees alone do NOT trigger client_interview)
- **Pending from Edu**: Asana Personal Access Token, Google Workspace service account credentials (Use Case A)

## Scripts & Tools Built
- **`scripts/xsearch.py`** — Search X/Twitter posts or web via Grok Live Search. Usage: `python3 scripts/xsearch.py "query"` (X), `--web`, or `--both`. Returns real-time results with citations.
- **`scripts/xread.py`** — Read & summarize a specific X post URL using Grok. Usage: `python3 scripts/xread.py <url>`.
- **`scripts/cost-monitor.py`** — pulls API spend from local OpenClaw session logs + OpenAI usage API. Run manually to get today's spend. Also runs on cron for daily digest + $20 threshold alerts → posts to #tony-ops (C0AHBCJQJKS). Usage: `python3 scripts/cost-monitor.py` (current day) or `--digest` (yesterday's full report).

## Server Security
- **SSH hardened 2026-02-23**: `PasswordAuthentication no`, `PermitRootLogin prohibit-password`
- Edu accesses via Termius (phone) using SSH key — fingerprint `SHA256:8OnDMpz6kQXbvvNlt42Y1gTrEBsjgU93WHAlyqRyUW8` (labeled "Termius-phone")
- 3 keys in authorized_keys: Mac Mini, unknown device, Termius-phone
- fail2ban running; ~3500 brute-force attempts/day from internet scanners (normal background noise)

## Known Issues
- ~~**CLI/Gateway Token Mismatch**~~ → **RESOLVED 2026-02-22**: Approved pending repair request via `openclaw devices approve --latest --token <token>`. Gateway now shows `RPC probe: ok`. New instance runs as root user at `/root/.openclaw/`.
