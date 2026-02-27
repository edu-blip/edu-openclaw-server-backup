# Fathom Integration — Rethoric

Built: 2026-02-24

## What This Does

Automatically processes Fathom call recordings after they finish. One webhook, three use cases.

```
Fathom call ends → transcript ready
        ↓
POST https://167.99.162.160/fathom-webhook
        ↓
webhook-server.js (port 8001) — verifies HMAC signature
        ↓
processor.js — classifies call by title
        ├── "Team check-in"          → Use Case A: Asana action items
        ├── "Content interview: …"   → Use Cases B + C
        ├── "Rethoric interview: …"  → Use Cases B + C
        ├── "Content call: …"        → Use Cases B + C
        └── Unknown                  → Alert to #tony-ops
```

---

## Use Cases

### A — Weekly Team Check-in → Asana ⏳ (pending Asana + Google keys)
- Extracts action items from transcript (independent of Fathom's output)
- Reconciles with Fathom's action items, flags discrepancies
- Creates/updates tasks in Asana "Weekly sync call" project with assignee + due date
- **Never duplicates** existing tasks
- Moves stale tasks to Abandoned section when superseded
- Pre-call briefing fires 1 hour before each Monday + Thursday check-in via Google Calendar API
- On-demand queries answered via Asana API (not transcript re-reads)

**Still needs:** `ASANA_TOKEN`, `ASANA_PROJECT_ID` (Google Calendar already works via gogcli)

### B — Client Interview Feedback → #client-feedback ✅
- Reads full transcript, detects any client feedback about:
  - Writing quality / style
  - Voice representation
  - What they liked/didn't like
  - Suggestions or frustrations about Rethoric
- Posts structured Slack message to `#client-feedback` (C0AGYTU4N9Y)
- **Captures implicit feedback** — hints and hesitations count
- If zero feedback detected: silent (no message sent)
- One consolidated message per call even if multiple feedback points

### C — Edu LinkedIn Content Ideas → Weekly Google Doc ✅ FULLY LIVE
- Mines transcripts for high-quality LinkedIn ideas from Edu's perspective
- Sources: client interview insights (Edu's commentary + client quotes Edu could riff on) + team check-in insights
- Accumulates to `fathom/content-ideas/week-YYYY-WXX.json` throughout the week
- Every Monday: creates a Google Doc in `Rethoric > Marketing > LinkedIn content`
- Doc name format: `"Edu content ideas - week 8 2026"`
- 5–10 ideas max per week. Quality over volume. No padding.

**Drive folder:** `1xiMgCRlVGhTWc79PIgaZ72zWcp9g5iq1` (Rethoric > Marketing > LinkedIn content) ✅
**Cron:** Every Monday 9 AM PST ✅

---

## File Structure

```
fathom/
├── README.md              ← you are here
├── webhook-server.js      ← HTTP server, receives Fathom POSTs, verifies signature
├── processor.js           ← classifies call, runs use case handlers
├── config.json            ← title patterns, Slack channel IDs, domains (edit freely)
├── webhook.log            ← webhook server log
├── processor.log          ← processor log
├── queue/                 ← incoming payloads awaiting processing (auto-cleared)
├── archive/               ← processed payloads (kept for audit)
├── content-ideas/         ← weekly JSON accumulator files
│   └── week-YYYY-WXX.json
└── pending-checkins/      ← team check-in payloads saved until Asana keys arrive
```

---

## Configuration (`config.json`)

```json
{
  "internalDomains": ["rethoric.co", "rethoric.com"],
  "internalTitlePatterns": ["team check-in", ...],
  "clientTitlePatterns": ["content interview", "rethoric interview", "content call"],
  "clientFeedbackSlackChannel": "C0AGYTU4N9Y",
  "opsSlackChannel": "C0AHBCJQJKS"
}
```

**To add a new title pattern:** edit `clientTitlePatterns` or `internalTitlePatterns`, then `systemctl restart fathom-webhook`.

---

## Infrastructure

| Component | Details |
|---|---|
| Webhook URL | `https://167.99.162.160/fathom-webhook` |
| Server | Node.js on port 8001 |
| Systemd service | `fathom-webhook.service` (auto-starts on reboot) |
| Caddy route | `/fathom-webhook*` → `localhost:8001` |
| Signature verification | HMAC-SHA256, `fathom-signature` header, secret in `.env` |
| AI model | `claude-sonnet-4-5` (configurable per use case in processor.js) |

---

## Ops Runbook

### Check service health
```bash
systemctl status fathom-webhook
curl -s https://167.99.162.160/fathom-webhook  # should return "Fathom webhook server OK"
```

### View live logs
```bash
journalctl -u fathom-webhook -f        # service stdout
tail -f fathom/processor.log           # processing details
```

### Restart after config changes
```bash
systemctl restart fathom-webhook
```

### Something got misclassified
1. Check `#tony-ops` — unclassified calls alert there automatically
2. Add the title pattern to `config.json`
3. Restart the service
4. The misclassified payload is in `fathom/archive/` — re-process manually if needed:
   ```bash
   node fathom/processor.js fathom/archive/<filename>.json
   ```

### Webhook not firing
1. Verify Fathom settings: `fathom.video/customize#api-access-header` → check webhook URL + checkboxes (transcript ✅ summary ✅ action items ✅)
2. Check `fathom/webhook.log` for incoming requests
3. Test endpoint manually: `curl -s https://167.99.162.160/fathom-webhook`

---

## Pending Work (Use Case A completion)

When Edu provides Asana + Google credentials:
1. Add `ASANA_TOKEN`, `ASANA_PROJECT_ID` to `.env`
2. Add `GOOGLE_SERVICE_ACCOUNT_JSON` (path) to `.env`
3. Build out `processWeeklyCheckin()` in `processor.js`
4. Set up cron for pre-call briefings (Mon + Thu, 1hr before check-in time)
5. Process any saved payloads in `fathom/pending-checkins/`
