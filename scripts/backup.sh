#!/bin/bash
# backup.sh — Daily auto-backup to GitHub
# Runs as openclaw user via cron

WORKSPACE="/home/openclaw/.openclaw/workspace"
LOG="/var/log/openclaw-backup.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M PST')

cd "$WORKSPACE" || { echo "[$TIMESTAMP] ERROR: workspace not found" >> "$LOG"; exit 1; }

# Stage all changes (respects .gitignore — no secrets committed)
git add -A

# Only commit if there's something to commit
if git diff --cached --quiet; then
  echo "[$TIMESTAMP] No changes — skipping commit" >> "$LOG"
else
  git commit -m "auto-backup: $TIMESTAMP" >> "$LOG" 2>&1
  git push origin master >> "$LOG" 2>&1
  echo "[$TIMESTAMP] Backup pushed to GitHub" >> "$LOG"
fi
