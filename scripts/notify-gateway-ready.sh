#!/bin/bash
# notify-gateway-ready.sh
# Waits for the OpenClaw gateway to be healthy, then posts to #tony-alerts.
# Runs via @reboot cron on server start.

set -e

# Load env vars (bot token)
source /root/.openclaw/.env

CHANNEL="C0AHBCJQJKS"
MAX_WAIT=120   # max seconds to wait for gateway
INTERVAL=5
elapsed=0

echo "[$(date)] Waiting for gateway to become healthy..."

while [ $elapsed -lt $MAX_WAIT ]; do
    if openclaw gateway status 2>/dev/null | grep -q "RPC probe: ok"; then
        echo "[$(date)] Gateway healthy. Sending notification."
        curl -s -X POST "https://slack.com/api/chat.postMessage" \
            -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{
                \"channel\": \"$CHANNEL\",
                \"text\": \":white_check_mark: *Tony is back online.* Gateway restarted and healthy.\"
            }" > /dev/null
        echo "[$(date)] Notification sent."
        exit 0
    fi
    sleep $INTERVAL
    elapsed=$((elapsed + INTERVAL))
done

echo "[$(date)] Gateway did not become healthy within ${MAX_WAIT}s. No notification sent."
exit 1
