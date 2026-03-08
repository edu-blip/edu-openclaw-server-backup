#!/usr/bin/env python3
"""
outbound-audit.py — Periodic outbound secret scanner.

Scans recent log files and Fathom archives for leaked credentials that may
have slipped into outbound content. Alerts to #tony-alerts if found.

No LLM calls. Pure regex.

Run: daily (or on-demand). Added to cron at 4am PST.

What it scans:
  - /home/openclaw/logs/*.log       (last 500 lines each)
  - workspace/fathom/archive/       (files modified in last 48h)
  - workspace/logs/*.jsonl          (last 200 lines each)

What it looks for:
  - API keys (sk-..., xai-..., AKIA..., Bearer tokens)
  - Slack bot tokens (xoxb-..., xoxp-...)
  - Private key headers
  - Hardcoded passwords in common formats
  - Server IP + credential combos
  - AWS secrets
"""

import re
import os
import glob
import json
import time
import urllib.request
from datetime import datetime, timezone

WORKSPACE  = "/home/openclaw/.openclaw/workspace"
LOGS_DIR   = "/home/openclaw/logs"
STATE_FILE = "/home/openclaw/logs/outbound-audit-state.json"
SLACK_CHANNEL = "C0AHBCJQJKS"

# ─── SECRET PATTERNS ──────────────────────────────────────────────────────────
# Each entry: (label, compiled_regex)
# Order matters: more specific first.

SECRET_PATTERNS = [
    ("ANTHROPIC_API_KEY",   re.compile(r'\bsk-ant-[a-zA-Z0-9\-_]{20,}\b')),
    ("OPENAI_API_KEY",      re.compile(r'\bsk-[a-zA-Z0-9]{20,}\b')),
    ("XAI_API_KEY",         re.compile(r'\bxai-[a-zA-Z0-9\-_]{20,}\b')),
    ("SLACK_BOT_TOKEN",     re.compile(r'\bxox[bpoa]-[a-zA-Z0-9\-]{10,}\b')),
    ("GOOGLE_API_KEY",      re.compile(r'\bAIza[0-9A-Za-z\-_]{35}\b')),
    ("AWS_ACCESS_KEY_ID",   re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ("AWS_SECRET_KEY",      re.compile(r'(?i)aws.{0,20}secret.{0,20}[=:]\s*["\']?[A-Za-z0-9/+]{40}\b')),
    ("BEARER_TOKEN",        re.compile(r'\bBearer\s+[a-zA-Z0-9\-_.]{32,}\b')),
    ("PRIVATE_KEY_BLOCK",   re.compile(r'-----BEGIN\s+(RSA\s+)?PRIVATE KEY-----')),
    ("GITHUB_TOKEN",        re.compile(r'\bghp_[a-zA-Z0-9]{36}\b|\bgh[sr]_[a-zA-Z0-9]{36,}\b')),
    ("GENERIC_SECRET",      re.compile(r'(?i)(password|passwd|secret|api_?key|auth_?token)\s*[=:]\s*["\']?[a-zA-Z0-9!@#$%^&*()\-_+=]{12,}["\']?')),
]

# Files/dirs to skip entirely (these are expected to contain the actual secrets)
SKIP_PATHS = {
    "/home/openclaw/.openclaw/.env",
    "/home/openclaw/.openclaw/openclaw.json",
    os.path.join(WORKSPACE, "scripts/cost_logger.py"),  # contains variable names only
}

# Patterns that are likely false positives in these contexts
# (e.g., REDACTED tokens, variable placeholders)
FALSE_POSITIVE_PATTERNS = [
    re.compile(r'\[REDACTED'),         # already redacted
    re.compile(r'PLACEHOLDER'),        # placeholder text
    re.compile(r'example\.com'),       # doc examples
    re.compile(r'YOUR_[A-Z_]+_HERE'),  # template vars
    re.compile(r'<YOUR_'),             # template vars
    re.compile(r'process\.env\.'),     # env var references (not values)
    re.compile(r'os\.environ'),        # env var references
    re.compile(r'get_env\('),          # env var helper calls
    re.compile(r'#.*sk-'),             # comments
    re.compile(r'//.*sk-'),            # code comments
]

# ─── STATE ────────────────────────────────────────────────────────────────────

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_run": None, "known_findings": []}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ─── SCANNING ─────────────────────────────────────────────────────────────────

def is_false_positive(line):
    for pat in FALSE_POSITIVE_PATTERNS:
        if pat.search(line):
            return True
    return False


def scan_lines(lines, filepath):
    """Scan a list of text lines. Return list of Finding dicts."""
    findings = []
    for lineno, line in enumerate(lines, 1):
        if is_false_positive(line):
            continue
        for label, pat in SECRET_PATTERNS:
            m = pat.search(line)
            if m:
                # Redact the matched value in the finding (don't log the actual secret)
                start, end = m.span()
                preview = line[max(0, start-20):start] + "[REDACTED]" + line[end:end+20]
                findings.append({
                    "file":    filepath,
                    "line":    lineno,
                    "type":    label,
                    "preview": preview.strip()[:200],
                })
                break  # one match per line is enough
    return findings


def tail_file(path, n=500):
    """Read last N lines of a file. Returns list of strings."""
    try:
        with open(path, "r", errors="replace") as f:
            return f.readlines()[-n:]
    except (IOError, PermissionError, IsADirectoryError):
        return []


def scan_log_files():
    """Scan recent log files."""
    findings = []
    pattern = os.path.join(LOGS_DIR, "*.log")
    for path in glob.glob(pattern):
        if path in SKIP_PATHS:
            continue
        lines = tail_file(path, n=500)
        findings.extend(scan_lines(lines, path))
    return findings


def scan_jsonl_files():
    """Scan recent JSONL log files."""
    findings = []
    for pattern in [
        os.path.join(LOGS_DIR, "*.jsonl"),
        os.path.join(WORKSPACE, "logs", "*.jsonl"),
    ]:
        for path in glob.glob(pattern):
            if path in SKIP_PATHS:
                continue
            lines = tail_file(path, n=200)
            findings.extend(scan_lines(lines, path))
    return findings


def scan_fathom_archives():
    """Scan Fathom archive files modified in the last 48h."""
    findings = []
    archive_dir = os.path.join(WORKSPACE, "fathom", "archive")
    if not os.path.exists(archive_dir):
        return findings

    cutoff = time.time() - 48 * 3600
    for path in glob.glob(os.path.join(archive_dir, "*.json")):
        if path in SKIP_PATHS:
            continue
        if os.path.getmtime(path) < cutoff:
            continue
        lines = tail_file(path, n=1000)
        findings.extend(scan_lines(lines, path))
    return findings


def scan_pending_asana():
    """Scan pending Asana JSON files (contain AI-extracted content)."""
    findings = []
    pending_dir = os.path.join(WORKSPACE, "fathom", "pending-asana")
    if not os.path.exists(pending_dir):
        return findings
    for path in glob.glob(os.path.join(pending_dir, "*.json")):
        if path in SKIP_PATHS:
            continue
        lines = tail_file(path, n=300)
        findings.extend(scan_lines(lines, path))
    return findings

# ─── DEDUP ────────────────────────────────────────────────────────────────────

def finding_key(f):
    return f"{f['file']}:{f['line']}:{f['type']}"


def new_findings(all_findings, known_keys):
    return [f for f in all_findings if finding_key(f) not in known_keys]

# ─── SLACK ────────────────────────────────────────────────────────────────────

def get_slack_token():
    for path in ["/home/openclaw/.openclaw/openclaw.json"]:
        try:
            with open(path) as f:
                cfg = json.load(f)
            token = cfg.get("channels", {}).get("slack", {}).get("botToken")
            if token:
                return token
        except Exception:
            pass
    for env_file in ["/home/openclaw/.openclaw/.env"]:
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("SLACK_BOT_TOKEN=") and not line.startswith("#"):
                        return line.split("=", 1)[1]
    return None


def post_to_slack(text, channel=SLACK_CHANNEL):
    token = get_slack_token()
    if not token:
        print(f"[outbound-audit] No Slack token — would have posted:\n{text}")
        return False
    payload = json.dumps({"channel": channel, "text": text}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                print(f"[outbound-audit] Slack error: {result.get('error')}")
                return False
            return True
    except Exception as e:
        print(f"[outbound-audit] Slack post failed: {e}")
        return False

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    state      = load_state()
    known_keys = set(state.get("known_findings", []))

    print("[outbound-audit] Scanning logs and archives for leaked secrets...")

    all_findings = []
    all_findings.extend(scan_log_files())
    all_findings.extend(scan_jsonl_files())
    all_findings.extend(scan_fathom_archives())
    all_findings.extend(scan_pending_asana())

    print(f"[outbound-audit] Raw matches: {len(all_findings)}")

    fresh = new_findings(all_findings, known_keys)
    print(f"[outbound-audit] New findings: {len(fresh)}")

    if fresh:
        # Build alert message (never includes actual secret values)
        lines = [f"🔐 *Outbound Secret Scan — {len(fresh)} new finding(s)*\n"]
        for f in fresh[:10]:  # cap at 10 to avoid massive Slack message
            lines.append(f"• *{f['type']}* in `{os.path.basename(f['file'])}` line {f['line']}")
            lines.append(f"  `{f['preview']}`")
        if len(fresh) > 10:
            lines.append(f"_...and {len(fresh)-10} more. Check server logs._")
        lines.append("\nReview and rotate any exposed credentials immediately.")

        msg = "\n".join(lines)
        if post_to_slack(msg):
            print("[outbound-audit] Alert posted to #tony-alerts")
            # Only mark as known after successful alert (so we don't silently swallow)
            for f in fresh:
                known_keys.add(finding_key(f))
    else:
        print("[outbound-audit] No new findings. All clear.")

    # Update state
    # Keep known_findings list bounded (max 500 entries)
    state["known_findings"] = list(known_keys)[-500:]
    state["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_state(state)
    print("[outbound-audit] Done.")


if __name__ == "__main__":
    main()
