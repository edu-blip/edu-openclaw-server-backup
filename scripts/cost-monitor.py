#!/usr/bin/env python3
"""
Cost Monitor — pulls API spend from local OpenClaw logs + OpenAI usage API.
Posts to Slack channel C0AHBCJQJKS (tony-ops).

Usage:
  python3 cost-monitor.py            # hourly check (alert only if >= threshold)
  python3 cost-monitor.py --digest   # full daily digest (always posts)
"""

import json
import os
import sys
import glob
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# ─── CONFIG ──────────────────────────────────────────────────────────────────
ALERT_THRESHOLD   = 20.00          # USD — alert when daily total hits this
SLACK_CHANNEL_ID  = "C0AHBCJQJKS" # #tony-ops
SESSIONS_DIR      = "/root/.openclaw/agents/main/sessions"

# Pricing (USD per 1M tokens) — update as models change
ANTHROPIC_PRICING = {
    "claude-sonnet-4-6":         {"input": 3.00,  "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4-20250514":  {"input": 3.00,  "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4-6":           {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "claude-haiku-3-5":          {"input": 0.80,  "output": 4.00,  "cache_read": 0.08, "cache_write": 1.00},
    "gemini-flash":              {"input": 0.075, "output": 0.30,  "cache_read": 0.0,  "cache_write": 0.0},
}
# ─────────────────────────────────────────────────────────────────────────────


def get_env(key):
    """Read env var or from /opt/openclaw.env or /root/.openclaw/.env."""
    val = os.environ.get(key)
    if val:
        return val
    for env_file in ["/opt/openclaw.env", "/root/.openclaw/.env"]:
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{key}=") and not line.startswith("#"):
                        return line.split("=", 1)[1]
    return None


PST = timezone(timedelta(hours=-8))

def get_today_pst():
    return datetime.now(PST).strftime("%Y-%m-%d")

def get_today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_anthropic_costs_from_logs(date_str):
    """Parse OpenClaw session JSONL files for Anthropic costs on date_str (PST)."""
    model_costs = {}  # model -> {input, output, cache_read, cache_write, total, tokens}
    
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    for filepath in glob.glob(pattern):
        try:
            with open(filepath, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        ts = record.get("timestamp", "")
                        if not ts:
                            continue
                        # Convert UTC timestamp to PST for date comparison
                        try:
                            dt_utc = datetime.fromisoformat(ts.replace("Z", "").split(".")[0]).replace(tzinfo=timezone.utc)
                            ts_pst_date = (dt_utc - timedelta(hours=8)).strftime("%Y-%m-%d")
                        except Exception:
                            ts_pst_date = ts[:10]  # fallback
                        if ts_pst_date != date_str:
                            continue
                        msg = record.get("message", {})
                        if msg.get("role") != "assistant":
                            continue
                        usage = msg.get("usage", {})
                        # Cost is nested inside usage.cost
                        cost = usage.get("cost", {}) if usage else {}
                        model = msg.get("model", "unknown")
                        # Normalize model name
                        model = model.replace("anthropic/", "").replace("google/", "")
                        
                        if not cost or not cost.get("total"):
                            continue
                        
                        if model not in model_costs:
                            model_costs[model] = {"total": 0, "tokens_in": 0, "tokens_out": 0, "calls": 0}
                        
                        model_costs[model]["total"]     += cost.get("total", 0)
                        model_costs[model]["tokens_in"] += usage.get("input", 0)
                        model_costs[model]["tokens_out"] += usage.get("output", 0)
                        model_costs[model]["calls"]     += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        except (IOError, PermissionError):
            continue
    
    return model_costs


def get_openai_usage(date_str):
    """Query OpenAI usage API for Whisper + other costs."""
    key = get_env("OPENAI_API_KEY")
    if not key:
        return {"error": "No OPENAI_API_KEY found", "whisper_cost": 0, "total": 0}
    
    url = f"https://api.openai.com/v1/usage?date={date_str}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return {"error": str(e), "whisper_cost": 0, "total": 0}
    
    # Whisper: $0.006 per minute
    whisper_seconds = sum(r.get("num_seconds", 0) for r in data.get("whisper_api_data", []))
    whisper_cost = (whisper_seconds / 60) * 0.006
    
    # TTS: $15/1M chars
    tts_chars = sum(r.get("num_characters", 0) for r in data.get("tts_api_data", []))
    tts_cost = (tts_chars / 1_000_000) * 15.0
    
    return {
        "whisper_seconds": whisper_seconds,
        "whisper_cost": whisper_cost,
        "tts_chars": tts_chars,
        "tts_cost": tts_cost,
        "total": whisper_cost + tts_cost,
    }


def post_to_slack(message, channel_id):
    """Post a message to Slack."""
    # Try to get Slack bot token from openclaw config
    config_path = "/root/.openclaw/openclaw.json"
    token = None
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        token = cfg.get("channels", {}).get("slack", {}).get("botToken")
    except Exception:
        pass
    
    if not token:
        print(f"[ERROR] No Slack bot token found. Message:\n{message}")
        return False
    
    payload = json.dumps({"channel": channel_id, "text": message}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                print(f"[ERROR] Slack API error: {result.get('error')}")
                return False
            return True
    except Exception as e:
        print(f"[ERROR] Slack post failed: {e}")
        return False


def format_message(anthropic_data, openai_data, date_str, is_alert=False, threshold=ALERT_THRESHOLD):
    """Format the cost breakdown message."""
    # Anthropic total
    anthropic_total = sum(v["total"] for v in anthropic_data.values())
    openai_total = openai_data.get("total", 0)
    brave_note = "~$0.00 (flat subscription)"
    grand_total = anthropic_total + openai_total

    lines = []
    
    if is_alert:
        lines.append(f"🚨 *Daily spend alert: ${grand_total:.2f}* (threshold: ${threshold:.0f})")
    else:
        lines.append(f"📊 *Daily API Cost Digest — {date_str}*")
    
    lines.append("")
    lines.append("*Anthropic (Claude):*")
    if anthropic_data:
        for model, stats in sorted(anthropic_data.items(), key=lambda x: -x[1]["total"]):
            calls = stats["calls"]
            tokens = stats["tokens_in"] + stats["tokens_out"]
            lines.append(f"  · {model}: ${stats['total']:.4f} ({calls} calls, {tokens:,} tokens)")
    else:
        lines.append("  · No usage today")
    lines.append(f"  *Subtotal: ${anthropic_total:.4f}*")
    
    lines.append("")
    lines.append("*OpenAI:*")
    if openai_data.get("whisper_seconds", 0) > 0:
        mins = openai_data["whisper_seconds"] / 60
        lines.append(f"  · Whisper: ${openai_data['whisper_cost']:.4f} ({mins:.1f} min)")
    else:
        lines.append("  · Whisper: $0.00")
    if openai_data.get("tts_cost", 0) > 0:
        lines.append(f"  · TTS: ${openai_data['tts_cost']:.4f}")
    lines.append(f"  *Subtotal: ${openai_total:.4f}*")
    
    lines.append("")
    lines.append(f"*Brave Search:* {brave_note}")
    
    lines.append("")
    lines.append(f"{'─' * 32}")
    lines.append(f"*Total: ${grand_total:.4f}*")
    
    if is_alert:
        lines.append("")
        # Identify biggest driver
        all_costs = {**{k: v["total"] for k, v in anthropic_data.items()}}
        if all_costs:
            top_model = max(all_costs, key=all_costs.get)
            lines.append(f"⚠️ Biggest driver: *{top_model}* (${all_costs[top_model]:.4f})")
        lines.append("Reply here to discuss or take action.")
    
    return "\n".join(lines)


def main():
    is_digest = "--digest" in sys.argv
    today = get_today_pst()
    # Digest reports on yesterday's completed data, not today's partial data
    date = (datetime.now(PST) - timedelta(days=1)).strftime("%Y-%m-%d") if is_digest else today
    
    print(f"[cost-monitor] Checking costs for {date}...")
    
    anthropic_data = parse_anthropic_costs_from_logs(date)
    openai_data = get_openai_usage(date)
    
    anthropic_total = sum(v["total"] for v in anthropic_data.values())
    openai_total = openai_data.get("total", 0)
    grand_total = anthropic_total + openai_total
    
    print(f"[cost-monitor] Total for {date}: ${grand_total:.4f}")
    
    if is_digest:
        # Always post for daily digest
        msg = format_message(anthropic_data, openai_data, date, is_alert=False)
        success = post_to_slack(msg, SLACK_CHANNEL_ID)
        print(f"[cost-monitor] Digest posted: {success}")
    else:
        # Hourly check — only post if over threshold
        if grand_total >= ALERT_THRESHOLD:
            msg = format_message(anthropic_data, openai_data, today, is_alert=True)
            success = post_to_slack(msg, SLACK_CHANNEL_ID)
            print(f"[cost-monitor] Alert posted (${grand_total:.4f} >= ${ALERT_THRESHOLD}): {success}")
        else:
            print(f"[cost-monitor] Under threshold (${grand_total:.4f} < ${ALERT_THRESHOLD}). No alert.")


if __name__ == "__main__":
    main()
