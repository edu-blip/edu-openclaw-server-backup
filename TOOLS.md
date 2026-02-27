# TOOLS.md - Local Notes

## API Keys
All in `/root/.openclaw/.env`: `OPENAI_API_KEY`, `BRAVE_API_KEY`, `XAI_API_KEY`, `FATHOM_API_KEY`, `FATHOM_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`

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

## Fathom (Rethoric)
- Service: `systemctl status fathom-webhook` (port 8001)
- Webhook: `https://167.99.162.160/fathom-webhook`
- Config: `fathom/config.json` | Full docs: `fathom/README.md`
- Pending: Asana PAT + Google Workspace creds from Edu (Use Cases A & C)

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
- Keyring password: set as `GOG_KEYRING_PASSWORD` in `~/.bashrc` and `/root/.openclaw/.env`
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
- Output: daily digest → `#tony-alerts`
