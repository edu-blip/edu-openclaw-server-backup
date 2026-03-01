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

# Archive: delete files older than 90 days — but ONLY if already ingested into KB
if [ -d "$ARCHIVE_DIR" ]; then
  CANDIDATES=$(find "$ARCHIVE_DIR" -maxdepth 1 -name "*.json" -mtime +${ARCHIVE_DAYS})
  if [ -z "$CANDIDATES" ]; then
    log "archive/: no files older than ${ARCHIVE_DAYS} days"
  else
    DELETED=0
    SKIPPED=0
    while IFS= read -r f; do
      # Check if this transcript has been ingested into the KB
      INGESTED=$(python3 -c "
import sys, json
sys.path.insert(0, '/root/.openclaw/workspace/kb')
import store
store.init_db()
try:
    with open('$f') as fp: d = json.load(fp)
    rid = str(d.get('recording_id', '')).strip()
    url = f'fathom://transcript/{rid}'
    print('yes' if rid and store.source_exists(url) else 'no')
except Exception as e:
    print('no')
" 2>/dev/null)
      if [ "$INGESTED" = "yes" ]; then
        rm "$f"
        log "archive/: deleted (ingested): $(basename $f)"
        DELETED=$((DELETED + 1))
      else
        log "archive/: SKIPPED — not yet in KB: $(basename $f). Run: python3 fathom/kb_ingest.py $f"
        SKIPPED=$((SKIPPED + 1))
      fi
    done <<< "$CANDIDATES"
    log "archive/: $DELETED deleted, $SKIPPED skipped (not ingested)"
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
