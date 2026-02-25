# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## xAI / X Search Integration

**Key:** `XAI_API_KEY` in `/root/.openclaw/.env`

### Scripts
- `scripts/xsearch.py` — Search X posts or the web via Grok Live Search
  - `python3 scripts/xsearch.py "query"` → X search (last 30 days)
  - `python3 scripts/xsearch.py --web "query"` → web search
  - `python3 scripts/xsearch.py --both "query"` → X + web
- `scripts/xread.py` — Read & summarize a specific X post URL
  - `python3 scripts/xread.py https://x.com/.../status/123` → full post summary
  - Add a second arg to ask a specific question about the post

**Model used:** `grok-4-1-fast-non-reasoning` (required for server-side tools)
**Pricing:** X Search $5/1k calls (currently free in beta)

---

## Fathom Integration (Rethoric)

**Built:** 2026-02-24 | **Docs:** `fathom/README.md`

### Service
- Webhook server: `systemctl status fathom-webhook` (Node.js, port 8001)
- Logs: `fathom/webhook.log` and `fathom/processor.log`
- Config: `fathom/config.json` ← edit this to adjust title patterns, channel IDs

### Webhook URL
`https://167.99.162.160/fathom-webhook` — registered in Fathom settings (Edu's account)

### Call Classification (title-match, lowercase)
| Pattern | Routes to |
|---|---|
| `team check-in` | Use Case A — Asana (weekly check-in) |
| `content interview`, `rethoric interview`, `content call` | Use Cases B + C |
| Anything else | Flags to #tony-ops |

### Slack Channels
- `#client-feedback` → `C0AGYTU4N9Y` (Use Case B output)
- `#tony-ops` → `C0AHBCJQJKS` (unclassified call alerts)

### API Keys (all in `/root/.openclaw/.env`)
- `FATHOM_API_KEY`, `FATHOM_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`

### Pending
- Use Case A (Asana): awaiting `ASANA_TOKEN` + `GOOGLE_SERVICE_ACCOUNT` from Edu
- Use Case C (Google Doc): awaiting Google Workspace credentials

### Common Tasks
```bash
# Check if webhook server is running
systemctl status fathom-webhook

# Tail live logs
journalctl -u fathom-webhook -f

# Adjust call title patterns
nano fathom/config.json  # edit internalTitlePatterns / clientTitlePatterns

# Manually test the endpoint
curl -s https://167.99.162.160/fathom-webhook
```

---

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.
