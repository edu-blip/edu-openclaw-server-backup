---
name: kb-ingest
description: "Auto-ingests URLs dropped in #knowledge-base Slack channel into the KB"
metadata: { "openclaw": { "emoji": "📚", "events": ["message:received"] } }
---

# KB Ingest Hook

Listens for messages in the Slack `#knowledge-base` channel (C0AGJ035DGF).
When a URL is detected, runs `kb/ingest.py` and replies with the result.

## What It Does

1. Watches for `message:received` events on the Slack channel
2. Checks the conversation is `#knowledge-base` (C0AGJ035DGF)
3. Extracts any URLs from the message
4. Runs `python3 kb/ingest.py <url>` for each URL
5. Replies to the channel with success/failure

## No Config Needed

Channel ID and workspace path are hardcoded for this deployment.
