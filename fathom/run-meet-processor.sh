#!/bin/bash
# Wrapper for meet-processor.js — sources env and runs the processor
set -e
set -a
source /home/openclaw/.openclaw/.env
set +a
# GOG_KEYRING_PASSWORD is sourced from .env above — no hardcoded fallback
exec node /home/openclaw/.openclaw/workspace/fathom/meet-processor.js "$@"
