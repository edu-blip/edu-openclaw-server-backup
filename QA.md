# QA.md — Quality Assurance & Security Gate

Last updated: 2026-03-01

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
- [ ] QA log entry added below (Integration Status table)
- [ ] Edu notified with pass/fail evidence before "ready" is declared

---

## Integration Status — Live Inventory

Format: `Status` = ✅ QA verified | ⚠️ Partially tested | ❌ Broken/unknown | 🔄 Pending QA

---

### 🔁 Always-On Services

| Integration | Status | Last QA | Notes |
|---|---|---|---|
| fail2ban | ⚠️ | Never formal QA | Running (confirmed via systemctl). No end-to-end block test done. |
| fathom-webhook service | ⚠️ | Never formal QA | systemd running. Use Cases B+C deployed. No structured end-to-end test with real Fathom payload since setup. |
| Security scanner (full, Sun 3:30am) | ⚠️ | Never formal QA | Cron exists. scan_history.json present. Output/alerting not verified. |
| Security scanner (diff, Mon–Sat 3:30am) | ⚠️ | Never formal QA | Same as above. |

---

### ⏰ Cron Jobs

| Integration | Schedule | Status | Last QA | Notes |
|---|---|---|---|---|
| Cost monitor — hourly alert | Every hour | ⚠️ | Never formal QA | Runs, but alert threshold behavior and Slack delivery not end-to-end tested. |
| Cost monitor — daily digest | Daily 8am PST | ⚠️ | Never formal QA | Digest logic not formally verified. |
| Fathom — Monday content doc | Mon 9am PST | ⚠️ | Never formal QA | Script exists. Google Drive output not verified live post-setup. |
| Fathom — pre-call briefing | Every 15min Mon+Thu | ⚠️ | Never formal QA | Fires when calendar has calls. Not verified with a real upcoming meeting. |
| Fathom — cleanup | Daily 2am PST | ⚠️ | Never formal QA | Cleanup logic not verified end-to-end. |
| notify-gateway-ready | @reboot (+30s) | ⚠️ | Never formal QA | Posts to #tony-alerts. Not re-tested since setup. |

---

### 🤖 OpenClaw Crons

| Integration | Schedule | Status | Last QA | Notes |
|---|---|---|---|---|
| nightly-extraction | Daily 11pm PST | ⚠️ | Never formal QA | Status=ok in cron list. But output accuracy not verified (see REGRESSIONS 2026-02-28). |
| healthcheck:update-status | Mon 9am PST | ⚠️ | Never formal QA | idle — hasn't run yet since set up. |

---

### 🔧 Manual Scripts / Tools

| Integration | Status | Last QA | Notes |
|---|---|---|---|
| gogcli (Google: Gmail, Calendar, Drive) | ⚠️ | Partial | Auth works. Calendar reads confirmed. Drive/Docs write never tested deliberately. |
| xsearch.py (X search) | ⚠️ | Never formal QA | Ran manually, appeared to work. No structured test. |
| xread.py (X post reader) | ⚠️ | Never formal QA | Same as above. |
| kb/ingest.py (Knowledge Base ingest) | ⚠️ | Never formal QA | Ran during setup. Retrieval accuracy not verified. |
| kb/search.py (Knowledge Base search) | ⚠️ | Never formal QA | Same as above. |
| agents/scout | ⚠️ | Never formal QA | Exists. Role/readiness not documented. |

---

### ⏳ Pending / Not Live

| Integration | Status | Notes |
|---|---|---|
| Fathom Use Case A (check-in → Asana) | ❌ Pending | Blocked on Asana PAT + Project ID |
| GitHub automated backup | ❌ Not built | Active hold in ACTIVE_CONTEXT.md |

---

## Weekly Regression Run (Sundays)

Every Sunday, a QA agent smoke-tests all ✅ verified integrations:
- Trigger each live service/script
- Confirm expected output
- Check systemd service health
- Report pass/fail to #tony-alerts

If anything fails: alert Edu immediately, mark as ❌ in this file, investigate.

---

## QA Log — Historical Record

Each QA pass gets an entry here.

```
[YYYY-MM-DD] Integration: <name>
  Tester: QA sub-agent (or Tony)
  Functional: PASS / FAIL — <evidence>
  Security: PASS / FAIL — <finding>
  Action: <what was fixed, if anything>
```

*(No entries yet — QA process starts 2026-03-01)*

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
