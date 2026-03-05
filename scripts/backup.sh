#!/bin/bash
# backup.sh — Daily auto-backup to GitHub
# Runs as openclaw user via cron

WORKSPACE="/home/openclaw/.openclaw/workspace"
LOG="/var/log/openclaw-backup.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M PST')
ENV_FILE="/home/openclaw/.openclaw/.env"

# Load GITHUB_TOKEN from .env
if [ -f "$ENV_FILE" ]; then
  export $(grep -E '^GITHUB_TOKEN=' "$ENV_FILE" | xargs)
fi

if [ -z "$GITHUB_TOKEN" ]; then
  echo "[$TIMESTAMP] ERROR: GITHUB_TOKEN not set — aborting" >> "$LOG"
  exit 1
fi

cd "$WORKSPACE" || { echo "[$TIMESTAMP] ERROR: workspace not found" >> "$LOG"; exit 1; }

# Stage all changes (respects .gitignore — no secrets committed)
git add -A

# Only commit if there's something to commit
if git diff --cached --quiet; then
  echo "[$TIMESTAMP] No changes — skipping commit" >> "$LOG"
else
  git commit -m "auto-backup: $TIMESTAMP" >> "$LOG" 2>&1
  git push "https://$GITHUB_TOKEN@github.com/edu-blip/edu-openclaw-server-backup.git" master >> "$LOG" 2>&1
  echo "[$TIMESTAMP] Backup pushed to GitHub" >> "$LOG"
fi
