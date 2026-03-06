#!/bin/bash
# backup.sh — Daily auto-backup to GitHub
# Runs as openclaw user via cron

WORKSPACE="/home/openclaw/.openclaw/workspace"
LOG="/home/openclaw/logs/backup.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M PST')
ENV_FILE="/home/openclaw/.openclaw/.env"
REMOTE_URL="https://github.com/edu-blip/edu-openclaw-server-backup.git"

# --- Log with automatic credential scrubbing ---
# Strips github tokens (ghp_/gho_/github_pat_), generic Bearer tokens,
# and any https://user:secret@host patterns before writing.
log() {
  echo "$1" | sed -E \
    -e 's|https://[^:]+:[^@]+@|https://[REDACTED]@|g' \
    -e 's/(ghp_|gho_|github_pat_)[A-Za-z0-9_]+/[REDACTED]/g' \
    -e 's/Bearer [A-Za-z0-9_\-\.]+/Bearer [REDACTED]/g' \
    >> "$LOG"
}

# Ensure log file exists and is owner-read/write only (not world-readable)
touch "$LOG"
chmod 640 "$LOG"

# Load GITHUB_TOKEN from .env
if [ -f "$ENV_FILE" ]; then
  export $(grep -E '^GITHUB_TOKEN=' "$ENV_FILE" | xargs)
fi

if [ -z "$GITHUB_TOKEN" ]; then
  log "[$TIMESTAMP] ERROR: GITHUB_TOKEN not set — aborting"
  exit 1
fi

cd "$WORKSPACE" || { log "[$TIMESTAMP] ERROR: workspace not found"; exit 1; }

# Stage all changes (respects .gitignore — no secrets committed)
git add -A

# Only commit/push if there's something new
if git diff --cached --quiet; then
  log "[$TIMESTAMP] No changes — skipping commit"
else
  COMMIT_OUTPUT=$(git commit -m "auto-backup: $TIMESTAMP" 2>&1)
  log "[$TIMESTAMP] $COMMIT_OUTPUT"

  # --- Safe push: token goes into a temp credential file, never into a URL ---
  CRED_FILE=$(mktemp)
  chmod 600 "$CRED_FILE"
  printf "https://oauth2:%s@github.com\n" "$GITHUB_TOKEN" > "$CRED_FILE"

  PUSH_OUTPUT=$(GIT_TERMINAL_PROMPT=0 \
    git -c "credential.helper=store --file=${CRED_FILE}" \
    push "$REMOTE_URL" master 2>&1)
  PUSH_EXIT=$?

  # Destroy the temp credential file immediately
  rm -f "$CRED_FILE"

  if [ "$PUSH_EXIT" -eq 0 ]; then
    log "[$TIMESTAMP] Backup pushed to GitHub"
  else
    # Log the error — the scrubber in log() will strip any leaked tokens
    log "[$TIMESTAMP] ERROR: push failed (exit $PUSH_EXIT): $PUSH_OUTPUT"
    exit 1
  fi
fi
