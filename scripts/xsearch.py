#!/usr/bin/env python3
"""
xsearch.py - Search X/Twitter and the web using xAI's Grok API with Live Search tools.

Usage:
  python3 scripts/xsearch.py "what are founders saying about AI agents on X?"
  python3 scripts/xsearch.py --web "latest news on LinkedIn algorithm changes"
  python3 scripts/xsearch.py --both "Series A SaaS founders talking about churn"

Flags:
  (default)  --x     Search X/Twitter posts only
  --web              Search the web only
  --both             Search both X and the web
"""

import sys
import os
import json
import requests
from datetime import datetime, timedelta

# Load API key from .env
env_path = "/home/openclaw/.openclaw/.env"
api_key = None
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("XAI_API_KEY="):
                api_key = line.split("=", 1)[1]
                break

if not api_key:
    print("ERROR: XAI_API_KEY not found in /home/openclaw/.openclaw/.env")
    sys.exit(1)

# Parse args
args = sys.argv[1:]
mode = "x"  # default: X search
if "--web" in args:
    mode = "web"
    args = [a for a in args if a != "--web"]
elif "--both" in args:
    mode = "both"
    args = [a for a in args if a != "--both"]
elif "--x" in args:
    mode = "x"
    args = [a for a in args if a != "--x"]

if not args:
    print(__doc__)
    sys.exit(1)

query = " ".join(args)

# Build tools list
tools = []
if mode in ("x", "both"):
    # Search last 30 days by default
    to_date = datetime.now()
    from_date = to_date - timedelta(days=30)
    tools.append({
        "type": "x_search",
        "filters": {
            "from_date": from_date.strftime("%Y-%m-%dT00:00:00Z"),
            "to_date": to_date.strftime("%Y-%m-%dT23:59:59Z"),
        }
    })

if mode in ("web", "both"):
    tools.append({"type": "web_search"})

# Determine model based on mode
model = "grok-4-1-fast-non-reasoning"  # required for server-side search tools

payload = {
    "model": model,
    "input": [
        {
            "role": "system",
            "content": "You are a research assistant. Search for the requested information and provide a clear, structured summary. Include key quotes and insights. Always cite your sources."
        },
        {
            "role": "user",
            "content": query
        }
    ],
    "tools": tools
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

print(f"🔍 Searching [{mode.upper()}]: {query}\n")
print("⏳ Calling Grok API...\n")

try:
    resp = requests.post(
        "https://api.x.ai/v1/responses",
        headers=headers,
        json=payload,
        timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
except requests.exceptions.RequestException as e:
    print(f"ERROR: API call failed: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"Response: {e.response.text}")
    sys.exit(1)

# Extract response text
output = data.get("output", [])
result_text = ""
for item in output:
    if item.get("type") == "message":
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                result_text = content.get("text", "")
                break

if not result_text:
    # Fallback: dump raw response for debugging
    print("⚠️  Could not extract text. Raw response:")
    print(json.dumps(data, indent=2))
    sys.exit(1)

print(result_text)

# Show citations if available
citations = data.get("citations", [])
if citations:
    print("\n📎 Sources:")
    for c in citations:
        print(f"  - {c}")

# Show tool usage stats
tool_usage = data.get("server_side_tool_usage", {})
if tool_usage:
    print(f"\n📊 Tool calls: {tool_usage}")
