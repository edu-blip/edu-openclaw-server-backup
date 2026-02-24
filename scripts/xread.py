#!/usr/bin/env python3
"""
xread.py - Read and summarize an X/Twitter post URL using Grok.

Usage:
  python3 scripts/xread.py https://x.com/someone/status/123456789
  python3 scripts/xread.py "https://x.com/someone/status/123456789" "what's the main point?"
"""

import sys
import os
import json
import requests

# Load API key from .env
env_path = "/root/.openclaw/.env"
api_key = None
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("XAI_API_KEY="):
                api_key = line.split("=", 1)[1]
                break

if not api_key:
    print("ERROR: XAI_API_KEY not found in /root/.openclaw/.env")
    sys.exit(1)

args = sys.argv[1:]
if not args:
    print(__doc__)
    sys.exit(1)

url = args[0]
extra_question = args[1] if len(args) > 1 else None

prompt = f"Please read this X post and give me a full summary of what it says, including any key insights, stats, or arguments made: {url}"
if extra_question:
    prompt += f"\n\nAlso answer this: {extra_question}"

payload = {
    "model": "grok-4-1-fast-non-reasoning",
    "input": [
        {
            "role": "system",
            "content": "You are a research assistant. When given an X/Twitter URL, use your x_search tool to look up and read the post content. Provide a clear, detailed summary."
        },
        {
            "role": "user",
            "content": prompt
        }
    ],
    "tools": [
        {
            "type": "x_search"
        },
        {
            "type": "web_search"
        }
    ]
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

print(f"📖 Reading X post: {url}\n")
print("⏳ Asking Grok...\n")

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
    print("⚠️  Could not extract text. Raw response:")
    print(json.dumps(data, indent=2))
    sys.exit(1)

print(result_text)
