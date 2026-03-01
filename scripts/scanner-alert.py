#!/usr/bin/env python3
"""
scanner-alert.py — Security Scanner Alert Bridge

Reads scan_history.json, finds findings that are:
  - CRITICAL or HIGH severity
  - Status: open
  - Not yet alerted (tracked by alerted_ids.json)

Posts new findings to #tony-alerts in Slack.
Run after scanner.py via cron.

Usage:
  python3 scripts/scanner-alert.py
  python3 scripts/scanner-alert.py --dry-run   # print without posting
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

WORKSPACE = Path(__file__).parent.parent
SCAN_HISTORY = WORKSPACE / 'security-scanner' / 'scan_history.json'
ALERTED_IDS_FILE = WORKSPACE / 'security-scanner' / 'alerted_ids.json'
ENV_FILE = Path('/root/.openclaw/.env')
SLACK_CHANNEL = 'C0AHBCJQJKS'  # #tony-alerts

ALERT_SEVERITIES = {'CRITICAL', 'HIGH'}
DRY_RUN = '--dry-run' in sys.argv

def get_env(key):
    val = os.environ.get(key)
    if val:
        return val
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith(f'{key}=') and not line.startswith('#'):
                return line[len(key)+1:].strip().strip('"').strip("'")
    return None

def load_alerted_ids():
    if ALERTED_IDS_FILE.exists():
        try:
            return set(json.loads(ALERTED_IDS_FILE.read_text()).get('alerted', []))
        except Exception:
            return set()
    return set()

def save_alerted_ids(ids):
    ALERTED_IDS_FILE.write_text(json.dumps({'alerted': sorted(ids)}, indent=2))

def load_findings():
    if not SCAN_HISTORY.exists():
        print('[scanner-alert] scan_history.json not found — skipping')
        return []
    try:
        data = json.loads(SCAN_HISTORY.read_text())
        return data.get('findings', [])
    except Exception as e:
        print(f'[scanner-alert] Failed to parse scan_history.json: {e}')
        return []

def post_to_slack(token, message):
    payload = json.dumps({
        'channel': SLACK_CHANNEL,
        'text': message,
        'unfurl_links': False
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://slack.com/api/chat.postMessage',
        data=payload,
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json; charset=utf-8'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get('ok'):
                print(f'[scanner-alert] Slack error: {result.get("error")}')
                return False
            return True
    except Exception as e:
        print(f'[scanner-alert] Slack request failed: {e}')
        return False

def main():
    findings = load_findings()
    alerted_ids = load_alerted_ids()

    new_findings = [
        f for f in findings
        if f.get('severity') in ALERT_SEVERITIES
        and f.get('status') == 'open'
        and f.get('id') not in alerted_ids
    ]

    if not new_findings:
        print(f'[scanner-alert] No new {"/".join(ALERT_SEVERITIES)} findings to alert.')
        return

    token = get_env('SLACK_BOT_TOKEN')
    if not token and not DRY_RUN:
        print('[scanner-alert] SLACK_BOT_TOKEN not set — cannot post to Slack')
        sys.exit(1)

    # Group by severity
    critical = [f for f in new_findings if f['severity'] == 'CRITICAL']
    high = [f for f in new_findings if f['severity'] == 'HIGH']

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = [f':rotating_light: *Security Scanner Alert — {now}*']
    lines.append(f'*{len(new_findings)} new finding(s):* {len(critical)} CRITICAL, {len(high)} HIGH\n')

    for f in new_findings[:10]:  # cap at 10 per run to avoid flooding
        sev_emoji = ':red_circle:' if f['severity'] == 'CRITICAL' else ':large_orange_circle:'
        lines.append(f"{sev_emoji} *[{f['id']}] {f['title']}*")
        lines.append(f"  File: `{f.get('file', 'unknown')}`")
        risk = f.get('risk', '')[:200]
        if risk:
            lines.append(f"  Risk: {risk}")
        fix = f.get('fix', '')[:200]
        if fix:
            lines.append(f"  Fix: {fix}")
        lines.append('')

    if len(new_findings) > 10:
        lines.append(f'_...and {len(new_findings) - 10} more. See scan_history.json for full list._')

    lines.append('_Run `python3 security-scanner/scanner.py` for full details._')
    message = '\n'.join(lines)

    if DRY_RUN:
        print('[DRY RUN] Would post to Slack:')
        print(message)
        return

    if post_to_slack(token, message):
        newly_alerted = {f['id'] for f in new_findings[:10]}
        alerted_ids.update(newly_alerted)
        save_alerted_ids(alerted_ids)
        print(f'[scanner-alert] Posted {len(new_findings)} findings to Slack. Marked {len(newly_alerted)} as alerted.')
    else:
        print('[scanner-alert] Failed to post to Slack — will retry next run.')

if __name__ == '__main__':
    main()
