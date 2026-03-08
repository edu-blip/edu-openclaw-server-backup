#!/usr/bin/env python3
"""
cost-governor.py — Real-time cost spike detector.

Runs every 2 minutes via cron. Computes rolling spend windows across
all cost sources and fires alerts to #tony-alerts when thresholds are hit.

No LLM calls. Pure math.

Thresholds (configurable below or via cost-governor-config.json):
  WARNING  : $5   in last 5 min  → warning alert
  CRITICAL : $15  in last 5 min  → critical alert + @mention
  CRITICAL : $25  in last 60 min → hourly burn alert

Dedup: one alert per threshold per DEDUP_MINUTES (default 10min).
"""

import json
import os
import sys
import glob
from datetime import datetime, timezone, timedelta
import urllib.request

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE    = os.path.join(SCRIPT_DIR, "cost-governor-config.json")
STATE_FILE     = "/home/openclaw/logs/cost-governor-state.json"
DIRECT_API_LOG = "/home/openclaw/logs/direct-api-costs.jsonl"
SESSIONS_DIR   = "/home/openclaw/.openclaw/agents/main/sessions"
SLACK_CHANNEL  = "C0AHBCJQJKS"
EDU_SLACK_ID   = "U01GQHG5FNZ"

# Default thresholds — override in cost-governor-config.json
DEFAULTS = {
    "warn_5min_usd":      5.00,
    "critical_5min_usd":  15.00,
    "critical_60min_usd": 25.00,
    "dedup_minutes":      10,
}

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            return {**DEFAULTS, **json.load(f)}
    except FileNotFoundError:
        return dict(DEFAULTS)
    except json.JSONDecodeError as e:
        print(f"[cost-governor] Bad config JSON: {e}")
        return dict(DEFAULTS)

# ─── STATE (dedup) ────────────────────────────────────────────────────────────

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def should_alert(state, key, dedup_minutes):
    """Return True if enough time has passed since last alert for this key."""
    last = state.get(key)
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() > dedup_minutes * 60
    except Exception:
        return True

def mark_alerted(state, key):
    state[key] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ─── COST PARSING ─────────────────────────────────────────────────────────────

def parse_direct_api_costs(since_dt):
    """
    Read direct-api-costs.jsonl. Return total $ spent since since_dt.
    Also returns per-model breakdown for alert messages.
    """
    total = 0.0
    breakdown = {}

    # Pricing table (per 1M tokens, input/output)
    pricing = {
        "grok-4-1-fast-non-reasoning": (5.00, 15.00),
        "grok-4-1":                    (5.00, 15.00),
    }
    default_pricing = (3.00, 15.00)

    if not os.path.exists(DIRECT_API_LOG):
        return total, breakdown

    try:
        with open(DIRECT_API_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    ts_str = r.get("ts", "")
                    if not ts_str:
                        continue
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if dt < since_dt:
                        continue

                    model   = r.get("model", "unknown")
                    inp_tok = int(r.get("input_tokens", 0) or 0)
                    out_tok = int(r.get("output_tokens", 0) or 0)
                    p_in, p_out = pricing.get(model, default_pricing)
                    cost = (inp_tok * p_in + out_tok * p_out) / 1_000_000

                    total += cost
                    breakdown[model] = breakdown.get(model, 0.0) + cost
                except (json.JSONDecodeError, ValueError):
                    continue
    except (IOError, PermissionError):
        pass

    return total, breakdown


def parse_session_costs(since_dt):
    """
    Read OpenClaw session JSONL files. Return total $ spent since since_dt.
    Uses cost.total field logged by OpenClaw; skips records with no cost.
    """
    total = 0.0
    breakdown = {}

    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    cutoff_str = since_dt.strftime("%Y-%m-%d")  # only scan today's files roughly

    for filepath in glob.glob(pattern):
        try:
            with open(filepath) as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        ts_str = record.get("timestamp", "")
                        if not ts_str:
                            continue
                        # Quick pre-filter: skip old records by date prefix
                        if ts_str[:10] < cutoff_str:
                            continue
                        dt = datetime.fromisoformat(
                            ts_str.replace("Z", "+00:00").split(".")[0] + "+00:00"
                        )
                        if dt < since_dt:
                            continue

                        msg = record.get("message", {})
                        if msg.get("role") != "assistant":
                            continue

                        usage = msg.get("usage") or {}
                        cost_info = usage.get("cost") or {}
                        cost_val = float(cost_info.get("total") or 0)
                        if not cost_val:
                            continue

                        model = msg.get("model", "unknown")
                        total += cost_val
                        breakdown[model] = breakdown.get(model, 0.0) + cost_val

                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
        except (IOError, PermissionError):
            continue

    return total, breakdown


def combined_spend(since_dt):
    """Total spend since since_dt from all sources."""
    direct_total, direct_bd   = parse_direct_api_costs(since_dt)
    session_total, session_bd = parse_session_costs(since_dt)

    total = direct_total + session_total

    # Merge breakdowns
    breakdown = dict(direct_bd)
    for model, cost in session_bd.items():
        breakdown[model] = breakdown.get(model, 0.0) + cost

    return total, breakdown

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
    # Fallback to .env
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
        print(f"[cost-governor] No Slack token — would have posted:\n{text}")
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
                print(f"[cost-governor] Slack error: {result.get('error')}")
                return False
            return True
    except Exception as e:
        print(f"[cost-governor] Slack post failed: {e}")
        return False

# ─── FORMATTING ───────────────────────────────────────────────────────────────

def format_breakdown(breakdown, limit=3):
    """Return top N models by cost as a compact string."""
    if not breakdown:
        return "  (no model detail)"
    top = sorted(breakdown.items(), key=lambda x: -x[1])[:limit]
    return "\n".join(f"  · {m}: ${c:.4f}" for m, c in top)


def format_alert(level, window_label, total, breakdown, threshold, cfg):
    if level == "warning":
        icon  = "⚠️"
        title = f"Cost spike warning: *${total:.3f}* in last {window_label}"
    else:
        icon  = "🚨"
        mention = f"<@{EDU_SLACK_ID}> " if level == "critical" else ""
        title = f"{mention}Cost spike CRITICAL: *${total:.3f}* in last {window_label} (threshold: ${threshold:.0f})"

    bd_str = format_breakdown(breakdown)
    return (
        f"{icon} {title}\n"
        f"{bd_str}\n"
        f"Check `logs/direct-api-costs.jsonl` or cron logs for runaway processes."
    )

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    cfg   = load_config()
    state = load_state()
    now   = datetime.now(timezone.utc)
    alerted_any = False

    warn_5min      = cfg["warn_5min_usd"]
    critical_5min  = cfg["critical_5min_usd"]
    critical_60min = cfg["critical_60min_usd"]
    dedup_min      = cfg["dedup_minutes"]

    # ── 5-minute window ───────────────────────────────────────────────────────
    since_5min = now - timedelta(minutes=5)
    spend_5min, bd_5min = combined_spend(since_5min)

    print(f"[cost-governor] 5-min spend: ${spend_5min:.4f}")

    if spend_5min >= critical_5min:
        if should_alert(state, "critical_5min", dedup_min):
            msg = format_alert("critical", "5 min", spend_5min, bd_5min, critical_5min, cfg)
            if post_to_slack(msg):
                mark_alerted(state, "critical_5min")
                mark_alerted(state, "warn_5min")  # suppress lower-tier when critical fires
                alerted_any = True
                print(f"[cost-governor] CRITICAL 5-min alert sent")
        else:
            print(f"[cost-governor] CRITICAL 5-min threshold hit but dedup active")

    elif spend_5min >= warn_5min:
        if should_alert(state, "warn_5min", dedup_min):
            msg = format_alert("warning", "5 min", spend_5min, bd_5min, warn_5min, cfg)
            if post_to_slack(msg):
                mark_alerted(state, "warn_5min")
                alerted_any = True
                print(f"[cost-governor] WARNING 5-min alert sent")
        else:
            print(f"[cost-governor] WARNING 5-min threshold hit but dedup active")

    # ── 60-minute window ──────────────────────────────────────────────────────
    since_60min = now - timedelta(minutes=60)
    spend_60min, bd_60min = combined_spend(since_60min)

    print(f"[cost-governor] 60-min spend: ${spend_60min:.4f}")

    if spend_60min >= critical_60min:
        if should_alert(state, "critical_60min", dedup_min):
            msg = format_alert("critical", "60 min", spend_60min, bd_60min, critical_60min, cfg)
            if post_to_slack(msg):
                mark_alerted(state, "critical_60min")
                alerted_any = True
                print(f"[cost-governor] CRITICAL 60-min alert sent")
        else:
            print(f"[cost-governor] CRITICAL 60-min threshold hit but dedup active")

    if alerted_any or True:  # always save state (updates last-checked time)
        save_state(state)

    print(f"[cost-governor] Done.")


if __name__ == "__main__":
    main()
