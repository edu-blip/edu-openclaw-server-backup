#!/bin/bash
# fathom/cleanup.sh — Transcript retention policy
# Runs daily at 2 AM. Keeps the archive lean and limits exposure window.
#
# Policy:
#   - fathom/archive/      → delete files older than 90 days
#   - fathom/pending-checkins/ → delete files older than 30 days
#
# Rationale: once content is extracted and the Google Doc is written, the raw
# transcript is no longer needed. 90 days gives a safety window for re-processing;
# 30 days is sufficient for the check-in queue which processes within hours.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_DIR="$SCRIPT_DIR/archive"
PENDING_DIR="$SCRIPT_DIR/pending-checkins"
LOG_FILE="$SCRIPT_DIR/cleanup.log"
ARCHIVE_DAYS=90
PENDING_DAYS=30

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $1" | tee -a "$LOG_FILE"
}

log "=== Fathom cleanup run ==="

# Archive: delete files older than 90 days
if [ -d "$ARCHIVE_DIR" ]; then
  DELETED=$(find "$ARCHIVE_DIR" -maxdepth 1 -name "*.json" -mtime +${ARCHIVE_DAYS} -print -delete 2>&1)
  if [ -n "$DELETED" ]; then
    COUNT=$(echo "$DELETED" | wc -l)
    log "archive/: deleted $COUNT file(s) older than ${ARCHIVE_DAYS} days"
    echo "$DELETED" | while read -r f; do log "  removed: $(basename $f)"; done
  else
    log "archive/: no files older than ${ARCHIVE_DAYS} days"
  fi
else
  log "archive/: directory not found — skipping"
fi

# Pending checkins: delete files older than 30 days
if [ -d "$PENDING_DIR" ]; then
  DELETED=$(find "$PENDING_DIR" -maxdepth 1 -name "*.json" -mtime +${PENDING_DAYS} -print -delete 2>&1)
  if [ -n "$DELETED" ]; then
    COUNT=$(echo "$DELETED" | wc -l)
    log "pending-checkins/: deleted $COUNT file(s) older than ${PENDING_DAYS} days"
  else
    log "pending-checkins/: no files older than ${PENDING_DAYS} days"
  fi
else
  log "pending-checkins/: directory not found — skipping"
fi

log "=== Done ==="
