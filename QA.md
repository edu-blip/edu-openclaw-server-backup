# QA.md — Quality Assurance & Security Gate

Last updated: 2026-03-01 (full audit run)

---

## The Rule

Nothing gets declared "ready" until this gate passes. No exceptions.

**Done = code written + QA agent verified it live + security agent cleared it + Edu notified with evidence.**

---

## Pre-Build: Acceptance Criteria Template

Before any build starts, Tony fills this out and Edu approves it:

```
Integration: <name>
What it does: <one sentence>
Success looks like: <exact observable outcome — what appears where>
Test steps: <numbered, runnable steps>
Failure modes to test: <2–3 edge cases>
Security notes: <any endpoints, keys, or data involved>
```

No coding starts until Edu says "yes" to the above.

---

## QA Gate Checklist (every integration)

### Functional QA (Step 3a)
- [ ] Happy path tested in LIVE environment (not local, not simulated)
- [ ] Real output confirmed (showed up in Slack / file exists / log entry present)
- [ ] At least one failure/edge case tested (bad input, missing data, service down)
- [ ] Evidence captured (log snippet, screenshot, or command output)
- [ ] No adjacent integrations broken (spot-check neighboring systems)

### Security QA (Step 3b)
- [ ] No secrets or API keys hardcoded in any new file (scan with grep)
- [ ] New endpoints require authentication (or explicitly documented as intentionally public)
- [ ] Script/service runs with minimum required permissions (not root unless required)
- [ ] No sensitive data (keys, PII, credentials) written to logs in plaintext
- [ ] No unexpected outbound network calls to unrecognized hosts
- [ ] `.env` is the only place credentials live — confirmed

### Sign-off
- [ ] Both QA checklists passed
- [ ] QA log entry added below (QA Log section)
- [ ] Edu notified with pass/fail evidence before "ready" is declared

---

## Integration Status — Full Audit (2026-03-01)

Format: ✅ QA verified | ⚠️ Working but issues found | ❌ Broken | 🚫 Not built | 🔒 Security issue

---

### 🔁 Always-On Services

**fathom-webhook (systemd service)** — ✅ RUNNING
- Service: active and stable
- Use Case B (client feedback → #client-feedback): receiving real webhooks, classifying calls, processing client transcripts. Last payload: 2026-02-28.
- Use Case C (content ideas mining): extracting ideas from calls, writing to week JSON files. Last run: 2026-02-28, added 5 ideas.
- Use Case A (check-in → Asana): ❌ STUB — pending Asana PAT
- Signature verification: FATHOM_WEBHOOK_SECRET is set and enforced — webhook rejects unsigned requests
- Issue found: None functionally. Security findings logged below.

**fail2ban** — ✅ RUNNING
- 1 jail active (sshd)
- Currently banning 6 IPs, 2417 total banned since deployment
- 19,837 failed attempts filtered. Working as intended.

---

### ⏰ Cron Jobs

**Cost monitor — hourly alert** — ✅ RUNNING
- Running every hour, reading session logs correctly
- Today's cost tracking: $10.19 as of last check, under $20 threshold
- Threshold logic working (no false alerts)
- Issue: daily digest posting to Slack not directly confirmed via log — only threshold checks visible

**Cost monitor — daily digest** — ⚠️ UNCONFIRMED
- Cron fires at 8am PST daily
- Log shows hourly checks working but no digest-specific entry visible in today's log
- Next step: verify digest appeared in #tony-alerts after 8am today

**notify-gateway-ready (@reboot)** — ✅ CONFIRMED
- Fired this morning at 11:45am PST after gateway restart
- Slack post confirmed: "#tony-alerts received ✅ Tony is back online. Gateway restarted and healthy."
- Full Slack API response confirmed in log

**Fathom — Monday content doc (Mon 9am PST)** — ⚠️ PARTIAL
- Cron fires and runs create-content-doc.js
- Error found on 2026-02-27: `--convert-to cannot be combined with --replace` caused first attempt to fail
- Second path succeeded: Updated existing Google Doc via gog CLI directly
- Doc link confirmed: https://docs.google.com/document/d/1PJ6mifw7WD2iDRKp8X5wiaaXTkqILfbxqwN0swWo304/edit
- Slack notified: true
- Issue: The Drive upload error path is untested. If gog doc update fails, the fallback may silently fail.

**Fathom — pre-call briefing (every 15min Mon+Thu)** — ⚠️ UNCONFIRMED WITH REAL MEETING
- Cron fires correctly every 15 minutes
- All logged runs: "No upcoming check-ins in window — nothing to do"
- Not tested against a real upcoming meeting — no way to confirm alert fires correctly
- Next test: verify Tuesday (Mon) when there's a real meeting on the calendar

**Fathom — cleanup (daily 2am PST)** — ⚠️ UNCONFIRMED
- Script is well-built: deletes archive files >90 days (only if KB-ingested), pending >30 days
- No files are old enough to trigger yet (all content from Feb 2026)
- Has not run in any meaningful way — purely timing-based gap
- Cleanup.log not checked — will confirm tomorrow

**Security scanner — full (Sun 3:30am PST)** — ⚠️ RUNNING BUT SILENT
- Ran at 12:37am PST (manual/baseline) — found 175 findings in scan_history.json
- Cron log file (/var/log/security-scanner.log) is 0 bytes — scanner produces no stdout
- Finding: results only go to scan_history.json. No alerting mechanism exists.
- No one is notified when critical findings are found. This is broken.
- Fix needed: scanner should post critical/high findings to #tony-alerts

**Security scanner — diff (Mon-Sat 3:30am PST)** — ⚠️ SAME ISSUE
- Same silent logging problem as full scan

---

### 🤖 OpenClaw Crons

**nightly-extraction (11pm PST)** — ⚠️ STATUS OK BUT ACCURACY UNVERIFIED
- Last ran 16h ago, status=ok
- Known regression: previously reported "no sessions" on a day with real activity (see REGRESSIONS.md 2026-02-28)
- Fix was applied but accuracy not re-verified since

**healthcheck:update-status (Mon 9am PST)** — ❌ NEVER RAN
- Status: idle — has not run since being created
- First scheduled run: tomorrow (Mon March 2)

---

### 🔧 Manual Scripts / Tools

**gogcli (Google: Gmail, Calendar, Drive)** — ✅ LIVE TEST PASSED
- Live test: `gog calendar events --all --account tony@rethoric.com --days 3`
- Returned 8 real calendar events from Rethoric + Personal calendars
- Auth working, both calendars visible

**xsearch.py (X search)** — ✅ LIVE TEST PASSED
- Live test: `python3 scripts/xsearch.py "LinkedIn content"`
- Returned structured results with sources and citations
- Grok API responding correctly

**xread.py (X post reader)** — ⚠️ NOT RE-TESTED
- Previously worked. Not re-tested this session — depends on same Grok API as xsearch (which passed).

**kb/ingest.py + kb/search.py (Knowledge Base)** — ✅ LIVE TEST PASSED
- Search test: `python3 kb/search.py "LinkedIn content strategy"`
- Returned 4 relevant results with scores, entity extraction, and source attribution
- Fathom transcripts correctly indexed (5h ago)
- Ingest not re-tested but search confirms data is in the DB

**agents/scout** — ❌ NOT DOCUMENTED / NOT TESTED
- Directory exists with SOUL.md and README.md
- Role and readiness not tested. Needs documentation.

---

### 🤖 Sub-Agents & Model Routing

**Sub-agent spawning (general)** — ✅ CONFIRMED
- QA test sub-agent spawned successfully this session
- Opus sub-agent spawned earlier this session (for QA process design)
- Mechanism works

**Karpathy (openai/gpt-5.1-codex-max)** — ✅ CONFIGURED
- Model appears in `openclaw models list`
- Not spawned in a live task this session — configured but not live-tested
- openai/gpt-5.1-codex and openai/gpt-5.1-codex-max: both `configured`
- openai-codex/gpt-5.3-codex: available but requires ChatGPT Pro OAuth (different provider)

**Model routing** — ✅ WORKING
- Default: anthropic/claude-sonnet-4-6 — active this session
- Opus: anthropic/claude-opus-4-6 — spawned this session
- Gemini Flash (google/gemini-3-flash-preview): configured for heartbeats, not live-tested today

---

### ⏳ Not Built / Pending

**Fathom Use Case A (check-in → Asana)** — ❌ BLOCKED
- Needs Asana Personal Access Token + Project ID from Edu

**GitHub automated backup** — ❌ NOT BUILT
- Active hold in ACTIVE_CONTEXT.md

**Security scanner alerting** — ❌ NOT BUILT
- Scanner finds issues but never tells anyone

---

## 🚨 Critical Issues Found in This Audit

### STOP — Immediate Action Required

**[CRITICAL → RESOLVED 2026-03-01] AWS credentials exposed in Fathom transcript**
- File: `fathom/archive/1772052374370-hjckfa.json`
- What happened: dev@rethoric.com AWS root password was spoken aloud in a recorded meeting, transcribed by Fathom, stored in plaintext on the server.
- Risk: Full AWS account takeover. Access to all AWS services, S3, RDS, billing.
- ✅ Edu confirmed credentials rotated on 2026-03-01.

### High Priority Fixes (This Week)

**[HIGH] Security scanner never alerts anyone**
- 175 findings exist in scan_history.json. Nobody is notified. Fix: add a cron step that reads scan_history.json and posts new CRITICAL/HIGH findings to #tony-alerts.

**[HIGH] GOG_KEYRING_PASSWORD hardcoded in source files**
- Files: `fathom/create-content-doc.js`, `fathom/precall-briefing.js`
- The keyring password is in source code as a string literal. Should be env var only.

**[HIGH] All services run as root**
- Any exploitation gives full server access. Long-term fix: create a dedicated service user.

**[HIGH] No backup**
- Server has zero backup. Single point of failure. Fix: GitHub backup (30-min job).

**[MEDIUM] Archive files not encrypted**
- Client call transcripts stored as plaintext JSON. Contains client PII, business strategy.
- Fix: chmod 600 on archive directory at minimum.

**[MEDIUM] fathom/archive should be added to .gitignore before GitHub backup goes live**
- Contains full client transcripts — must NOT be committed to git.

---

## QA Log — Historical Record

```
[2026-03-01] FULL SYSTEM AUDIT
  Tester: Tony (main session)
  Scope: All live integrations, crons, sub-agents, model routing

  Functional results:
  PASS: fathom-webhook service, fail2ban, cost monitor (hourly), notify-gateway-ready,
        gogcli (calendar), xsearch.py, kb/search.py, sub-agent spawning,
        model routing (Sonnet/Opus), Karpathy model config

  PARTIAL/UNCONFIRMED: cost monitor daily digest, fathom Monday doc (error on first
        attempt, fallback succeeded), pre-call briefing (no real meeting to test against),
        nightly extraction (accuracy), fathom cleanup (no old files yet)

  BROKEN: security scanner alerting (silent — no notifications), healthcheck cron
        (never ran), agents/scout (undocumented), Fathom Use Case A (pending Asana)

  Security:
  CRITICAL: AWS credentials in fathom transcript archive — requires immediate rotation
  175 total findings from security scanner (26 critical, 65 high, 69 medium, 15 low)
  Mitigating factor: FATHOM_WEBHOOK_SECRET confirmed set and enforced
```

---

## Security Scan Commands (reference)

Use these when running security QA on new files:

```bash
# Check for hardcoded secrets in new files
grep -rE "(api_key|API_KEY|secret|password|token|Bearer)\s*=\s*['\"][^'\"]{8,}" <path>

# Check for outbound network calls
grep -rE "(requests\.get|requests\.post|curl|urllib|fetch|axios)" <path>

# Verify .env usage (should see os.environ or dotenv, not hardcoded strings)
grep -rE "os\.environ|dotenv|process\.env" <path>

# Check file permissions
ls -la <path>

# Check who a service runs as
systemctl show <service> | grep User
```

---

## Weekly Regression Run (Sundays)

Every Sunday, a QA agent smoke-tests all ✅ verified integrations:
- Trigger each live service/script
- Confirm expected output
- Check systemd service health
- Post pass/fail to #tony-alerts

Next run: 2026-03-08
