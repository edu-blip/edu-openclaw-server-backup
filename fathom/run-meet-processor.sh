#!/bin/bash
# Wrapper for meet-processor.js — sources env and runs the processor
set -e
set -a
source /home/openclaw/.openclaw/.env
set +a
export GOG_KEYRING_PASSWORD=gogcli-server-keyring
exec node /home/openclaw/.openclaw/workspace/fathom/meet-processor.js "$@"
