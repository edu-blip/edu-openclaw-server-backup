#!/usr/bin/env python3
"""
Cost Monitor — auto-tracking for all models and providers.
Reads costs from OpenClaw session logs. Providers and models are detected
automatically — no code changes needed when new models are added.

Config: scripts/cost-monitor-config.json

Usage:
  python3 cost-monitor.py            # hourly check (alert only if >= threshold)
  python3 cost-monitor.py --digest   # full daily digest (always posts)
"""

import json
import os
import sys
import glob
import urllib.request
from datetime import datetime, timezone, timedelta

PST = timezone(timedelta(hours=-8))

# ─── CONFIG ──────────────────────────────────────────────────────────────────

def load_config():
    """Load cost-monitor-config.json from the same directory as this script."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "cost-monitor-config.json")
    try:
        with open(config_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[WARN] Config not found at {config_path} — using defaults.")
        return {}
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in cost-monitor-config.json: {e}")
        sys.exit(1)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def get_env(key):
    """Read env var or from .env files."""
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


def provider_from_model(model_str):
    """
    Extract provider prefix from a model string.
    e.g. 'anthropic/claude-sonnet-4-6' -> 'anthropic'
         'google/gemini-3-flash-preview' -> 'google'
         'claude-sonnet-4-6' -> 'anthropic'  (fallback for unprefixed Claude names)
         'gpt-4o' -> 'openai'                (fallback for unprefixed OpenAI names)
    """
    if "/" in model_str:
        return model_str.split("/")[0].lower()
    # Fallback heuristics for unprefixed names
    lower = model_str.lower()
    if lower.startswith("claude"):
        return "anthropic"
    if lower.startswith("gpt") or lower.startswith("o1") or lower.startswith("o3"):
        return "openai"
    if lower.startswith("gemini"):
        return "google"
    if lower.startswith("grok"):
        return "xai"
    if lower.startswith("mistral") or lower.startswith("mixtral"):
        return "mistral"
    if lower.startswith("llama"):
        return "meta"
    return "unknown"


def model_display_name(model_str):
    """Strip the provider prefix for display. e.g. 'anthropic/claude-sonnet-4-6' -> 'claude-sonnet-4-6'"""
    if "/" in model_str:
        return model_str.split("/", 1)[1]
    return model_str


def provider_display_name(provider_key, cfg_providers):
    """Map provider key to a human-readable name from config."""
    return cfg_providers.get(provider_key, provider_key.capitalize())


def get_today_pst():
    return datetime.now(PST).strftime("%Y-%m-%d")

# ─── LOG PARSING ─────────────────────────────────────────────────────────────

def parse_all_costs_from_logs(date_str, sessions_dir, pricing_overrides=None):
    """
    Parse all OpenClaw session JSONL files for costs on date_str (PST).

    Returns:
        {
          "anthropic": {
            "claude-sonnet-4-6": {"total": 1.23, "tokens_in": 1000, "tokens_out": 500, "calls": 10},
            ...
          },
          "google": {
            "gemini-3-flash-preview": { ... }
          },
          ...
        }
    """
    providers = {}   # provider -> model -> stats

    pattern = os.path.join(sessions_dir, "*.jsonl")
    for filepath in glob.glob(pattern):
        try:
            with open(filepath, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line)

                        # Filter by PST date
                        ts = record.get("timestamp", "")
                        if not ts:
                            continue
                        try:
                            dt_utc = datetime.fromisoformat(
                                ts.replace("Z", "").split(".")[0]
                            ).replace(tzinfo=timezone.utc)
                            ts_pst_date = (dt_utc - timedelta(hours=8)).strftime("%Y-%m-%d")
                        except Exception:
                            ts_pst_date = ts[:10]
                        if ts_pst_date != date_str:
                            continue

                        msg = record.get("message", {})
                        if msg.get("role") != "assistant":
                            continue

                        usage = msg.get("usage") or {}
                        cost  = usage.get("cost") or {}
                        raw_model = msg.get("model", "unknown")

                        # Try to get cost total from log; fall back to pricing_overrides
                        cost_total = cost.get("total", 0)
                        if not cost_total and pricing_overrides:
                            stripped = model_display_name(raw_model)
                            override = (
                                pricing_overrides.get(raw_model)
                                or pricing_overrides.get(stripped)
                            )
                            if override:
                                inp = usage.get("input", 0)
                                out = usage.get("output", 0)
                                cr  = usage.get("cache_read", 0)
                                cw  = usage.get("cache_write", 0)
                                cost_total = (
                                    inp * override.get("input", 0) / 1_000_000
                                    + out * override.get("output", 0) / 1_000_000
                                    + cr  * override.get("cache_read", 0) / 1_000_000
                                    + cw  * override.get("cache_write", 0) / 1_000_000
                                )

                        if not cost_total:
                            continue

                        provider = provider_from_model(raw_model)
                        model    = model_display_name(raw_model)

                        if provider not in providers:
                            providers[provider] = {}
                        if model not in providers[provider]:
                            providers[provider][model] = {
                                "total": 0, "tokens_in": 0, "tokens_out": 0, "calls": 0
                            }

                        providers[provider][model]["total"]      += cost_total
                        providers[provider][model]["tokens_in"]  += usage.get("input", 0)
                        providers[provider][model]["tokens_out"] += usage.get("output", 0)
                        providers[provider][model]["calls"]      += 1

                    except (json.JSONDecodeError, KeyError):
                        continue
        except (IOError, PermissionError):
            continue

    return providers


# ─── OPENAI USAGE API ─────────────────────────────────────────────────────────

def get_openai_usage(date_str, cfg_openai):
    """Query OpenAI usage API for Whisper, TTS, etc."""
    if not cfg_openai.get("enabled", True):
        return {"total": 0}

    key = get_env("OPENAI_API_KEY")
    if not key:
        return {"error": "No OPENAI_API_KEY", "total": 0}

    url = f"https://api.openai.com/v1/usage?date={date_str}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return {"error": str(e), "total": 0}

    whisper_per_min = cfg_openai.get("whisper_cost_per_minute", 0.006)
    tts_per_million  = cfg_openai.get("tts_cost_per_million_chars", 15.0)

    whisper_seconds = sum(r.get("num_seconds", 0) for r in data.get("whisper_api_data", []))
    whisper_cost    = (whisper_seconds / 60) * whisper_per_min

    tts_chars = sum(r.get("num_characters", 0) for r in data.get("tts_api_data", []))
    tts_cost  = (tts_chars / 1_000_000) * tts_per_million

    return {
        "whisper_seconds": whisper_seconds,
        "whisper_cost":    whisper_cost,
        "tts_chars":       tts_chars,
        "tts_cost":        tts_cost,
        "total":           whisper_cost + tts_cost,
    }


# ─── FORMATTING ──────────────────────────────────────────────────────────────

def format_message(provider_data, openai_data, date_str, cfg, is_alert=False):
    """
    Format the full cost breakdown.
    provider_data: { provider_key: { model_name: stats } }
    """
    cfg_providers  = cfg.get("providers", {})
    alert_threshold = cfg.get("alert_threshold_usd", 20.00)

    # Grand total
    log_total    = sum(
        m["total"]
        for models in provider_data.values()
        for m in models.values()
    )
    openai_total = openai_data.get("total", 0)

    # Deduct openai models already in logs to avoid double-counting
    openai_in_logs = sum(
        m["total"]
        for models in provider_data.get("openai", {}).values()
        for m in [models]
    ) if isinstance(provider_data.get("openai"), dict) else 0

    grand_total = log_total + openai_total

    lines = []
    if is_alert:
        lines.append(f"🚨 *Daily spend alert: ${grand_total:.2f}* (threshold: ${alert_threshold:.0f})")
    else:
        lines.append(f"📊 *Daily API Cost Digest — {date_str}*")

    # ── Per-provider, per-model breakdown ────────────────────────────────────
    # Sort providers by total spend (descending)
    sorted_providers = sorted(
        provider_data.items(),
        key=lambda kv: sum(m["total"] for m in kv[1].values()),
        reverse=True
    )

    for provider_key, models in sorted_providers:
        provider_total = sum(m["total"] for m in models.values())
        provider_name  = provider_display_name(provider_key, cfg_providers)

        lines.append("")
        lines.append(f"*{provider_name}:*")

        # Sort models by cost descending
        for model_name, stats in sorted(models.items(), key=lambda x: -x[1]["total"]):
            tokens = stats["tokens_in"] + stats["tokens_out"]
            lines.append(
                f"  · {model_name}: ${stats['total']:.4f}"
                f" ({stats['calls']} calls, {tokens:,} tokens)"
            )
        lines.append(f"  *Subtotal: ${provider_total:.4f}*")

    # ── OpenAI consumption-based APIs (Whisper, TTS) ─────────────────────────
    whisper_cost = openai_data.get("whisper_cost", 0)
    tts_cost     = openai_data.get("tts_cost", 0)
    if whisper_cost > 0 or tts_cost > 0:
        lines.append("")
        lines.append("*OpenAI (Usage APIs):*")
        if whisper_cost > 0:
            mins = openai_data.get("whisper_seconds", 0) / 60
            lines.append(f"  · Whisper: ${whisper_cost:.4f} ({mins:.1f} min)")
        if tts_cost > 0:
            lines.append(f"  · TTS: ${tts_cost:.4f}")
        lines.append(f"  *Subtotal: ${whisper_cost + tts_cost:.4f}*")

    # ── No usage case ─────────────────────────────────────────────────────────
    if not sorted_providers and whisper_cost == 0 and tts_cost == 0:
        lines.append("")
        lines.append("  · No usage recorded today")

    lines.append("")
    lines.append("─" * 32)
    lines.append(f"*Total: ${grand_total:.4f}*")

    if is_alert:
        lines.append("")
        # Identify biggest single model
        all_models = {
            f"{pk}/{mn}": ms["total"]
            for pk, models in provider_data.items()
            for mn, ms in models.items()
        }
        if all_models:
            top = max(all_models, key=all_models.get)
            lines.append(f"⚠️ Biggest driver: *{top}* (${all_models[top]:.4f})")
        lines.append("Reply here to discuss or take action.")

    return "\n".join(lines)


# ─── SLACK ────────────────────────────────────────────────────────────────────

def post_to_slack(message, channel_id):
    config_path = "/root/.openclaw/openclaw.json"
    token = None
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        token = cfg.get("channels", {}).get("slack", {}).get("botToken")
    except Exception:
        pass

    if not token:
        print(f"[ERROR] No Slack bot token found.\n{message}")
        return False

    payload = json.dumps({"channel": channel_id, "text": message}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                print(f"[ERROR] Slack API: {result.get('error')}")
                return False
            return True
    except Exception as e:
        print(f"[ERROR] Slack post failed: {e}")
        return False


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    cfg             = load_config()
    is_digest       = "--digest" in sys.argv
    alert_threshold = cfg.get("alert_threshold_usd", 20.00)
    channel_id      = cfg.get("slack_channel_id", "C0AHBCJQJKS")
    sessions_dir    = cfg.get("sessions_dir", "/root/.openclaw/agents/main/sessions")
    pricing_ovr     = cfg.get("pricing_overrides", {}).get("models", {})
    cfg_openai      = cfg.get("openai_usage_api", {})

    today = datetime.now(PST).strftime("%Y-%m-%d")
    # Digest always reports on yesterday's completed data
    date  = (datetime.now(PST) - timedelta(days=1)).strftime("%Y-%m-%d") if is_digest else today

    print(f"[cost-monitor] Checking costs for {date}...")

    provider_data = parse_all_costs_from_logs(date, sessions_dir, pricing_ovr)
    openai_data   = get_openai_usage(date, cfg_openai)

    log_total    = sum(m["total"] for models in provider_data.values() for m in models.values())
    openai_total = openai_data.get("total", 0)
    grand_total  = log_total + openai_total

    print(f"[cost-monitor] Total for {date}: ${grand_total:.4f}")

    if is_digest:
        msg     = format_message(provider_data, openai_data, date, cfg, is_alert=False)
        success = post_to_slack(msg, channel_id)
        print(f"[cost-monitor] Digest posted: {success}")
    else:
        if grand_total >= alert_threshold:
            msg     = format_message(provider_data, openai_data, today, cfg, is_alert=True)
            success = post_to_slack(msg, channel_id)
            print(f"[cost-monitor] Alert posted (${grand_total:.4f} >= ${alert_threshold}): {success}")
        else:
            print(f"[cost-monitor] Under threshold (${grand_total:.4f} < ${alert_threshold}). No alert.")


if __name__ == "__main__":
    main()
