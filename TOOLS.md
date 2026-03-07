# TOOLS.md - Local Notes

## API Keys
All in `/home/openclaw/.openclaw/.env`: `OPENAI_API_KEY`, `BRAVE_API_KEY`, `XAI_API_KEY`, `FATHOM_API_KEY`, `FATHOM_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`

## Central Model Registry
- File: `config/models.json`
- Single source of truth for all model names across the codebase (JS + Python)
- **Edit this file only** to update any model — no script changes needed elsewhere
- Covers: `claude_default`, `claude_opus`, `claude_haiku`, `gemini_default`, `grok_default`, scanner-specific models
- Added: 2026-03-03 (commit: `refactor: centralize model names in config/models.json`)

## Slack Channels
- `#tony-alerts` → `C0AHBCJQJKS`
- `#client-feedback` → `C0AGYTU4N9Y`

---

## xAI / X Search
- `python3 scripts/xsearch.py "query"` → X posts (last 30 days)
- `python3 scripts/xsearch.py --web "query"` → web search
- `python3 scripts/xread.py <url>` → read & summarize X post
- Model: `grok-4-1-fast-non-reasoning` | Key: `XAI_API_KEY`

---

## Asana
- PAT stored as `ASANA_PAT` in `.env` (Edu's personal account, `edu@rethoric.com`)
- Workspace GID: `1206594553706994` (Rethoric)
- User GID: `1206594553352666` (Eduardo Mussali)
- Weekly Sync Call project GID: `1207588849301630`
- Heartbeat read: `source .env && ASANA_PAT=$ASANA_PAT node fathom/asana-digest.js`
  - `--all` for all incomplete tasks assigned to Edu
  - `--project <gid>` for specific project tasks
- **Use Case A flow (approval-first):**
  1. Check-in processed → Claude extracts tasks → saved to `fathom/pending-asana/<refId>.json`
  2. Slack preview posted to `#tony-alerts` with numbered task list + ref ID
  3. Edu replies in #openclaw-setup: `approve`, `approve delete 2,5`, `approve edit 3: new text`, or `reject`
  4. Tony runs: `source .env && ASANA_PAT=$ASANA_PAT node fathom/asana-push.js <refId> [--delete N,M] [--edit "N: text"] [--reject]`
- Pending approvals: `fathom/pending-asana/` | Pushed: `pending-asana/pushed/` | Rejected: `pending-asana/rejected/`
- Config keys: `asanaProjectCheckin`, `asanaWorkspace` in `fathom/config.json`

---

## Fathom (Rethoric)
- Service: `systemctl status fathom-webhook` (port 8001)
- Webhook: `https://167.99.162.160/fathom-webhook`
- Config: `fathom/config.json` | Full docs: `fathom/README.md`
- Pending: Asana PAT + Google Workspace creds from Edu (Use Case A)

---

## Google Meet Processor
- Script: `fathom/meet-processor.js`
- Polls Google Drive `Meet Recordings` folder via gogcli every 2 hours
- Deduplicates against Fathom (skips meetings already processed by Fathom webhook)
- Runs same use cases as Fathom pipeline (B + C for client/content calls, A for team check-ins)
- Classifiers: `sales_call`, `content_interview`, `team_checkin`, `client_status`, `platform_dev`, `unknown`
- Unknown → alert to #tony-alerts; `platform_dev` (Marco Podesta etc.) → silent archive
- State file: `fathom/meet-processor-state.json` | Logs: `fathom/meet-processor.log`
- Manual run: `node fathom/meet-processor.js` | Cron: every 2 hours

---

## Knowledge Base (RAG)
- Ingest: `python3 kb/ingest.py <url>`
- Search: `python3 kb/search.py "query"`
- DB: `kb/kb.db` | Full docs: `kb/README.md`
- Pending: Wire up Slack handler, create `#knowledge-base` channel

---

## Google (gogcli)
- Binary: `/usr/local/bin/gog` (v0.11.0)
- Auth: `tony@rethoric.com` → Gmail, Calendar, Drive, Docs, Sheets
- Keyring password: set as `GOG_KEYRING_PASSWORD` in `~/.bashrc` and `/home/openclaw/.openclaw/.env`
- Usage: `export GOG_KEYRING_PASSWORD=gogcli-server-keyring && gog <command> --account tony@rethoric.com`
- Edu's calendars (shared with tony@rethoric.com):
  - `edu@rethoric.com` → "Rethoric" calendar (writer)
  - `eduardomussali@gmail.com` → "Personal" calendar (writer)
- ⚠️ NEVER modify/delete anything without Edu's explicit consent
- Examples:
  - `gog gmail search "in:inbox" --limit 10 --account tony@rethoric.com`
  - `gog calendar events --all --account tony@rethoric.com --tomorrow`
  - `gog calendar events --all --account tony@rethoric.com --days 7`
  - `gog drive ls --account tony@rethoric.com --limit 20`
- Docs: `gog --help`

---

## Cost Monitor
- Script: `scripts/cost-monitor.py`
- Config: `scripts/cost-monitor-config.json` — edit thresholds, channel ID, provider display names here. Never edit the script.
- Auto-detects ALL providers/models from logs — zero code changes when new models are added
- Per-provider + per-model breakdown in every digest
- Output: daily digest → `#tony-alerts`
- **Direct API cost logger (added 2026-03-06):** `scripts/cost_logger.py` (Python) + `scripts/cost-logger.js` (JS) — shared modules imported by all scripts that call APIs directly. Appends to `logs/direct-api-costs.jsonl`. Picked up automatically by cost-monitor. Covers: fathom scripts (Claude), xread/xsearch/twitter extractor (xAI/Grok), security scanner (Claude+Gemini).

---

## GitHub Auto-Backup
- Script: `scripts/backup.sh`
- Repo: `github.com/edu-blip/edu-openclaw-server-backup` (private)
- Cron: daily 3am PST
- Excludes: credentials, MEMORY.md, USER.md, call transcripts, logs, DB files
- Manual push: `cd /home/openclaw/.openclaw/workspace && source /home/openclaw/.openclaw/.env && git add -A && git commit -m "manual" && git push "https://$GITHUB_TOKEN@github.com/edu-blip/edu-openclaw-server-backup.git" master`
- ⚠️ Token is in `.env` as `GITHUB_TOKEN` (not in remote URL — fixed 2026-03-05). Rotate PAT on GitHub when able (old token was exposed in .git/config).

---

## Gateway Ready Notification
- Script: `scripts/notify-gateway-ready.sh`
- Trigger: `@reboot` cron (30s delay after boot)
- Output: posts to `#tony-alerts` when gateway is healthy
- Logs: `/var/log/notify-gateway-ready.log`
- Manual restarts: Tony replies in the active thread after confirming health
