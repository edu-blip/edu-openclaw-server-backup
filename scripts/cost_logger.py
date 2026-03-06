"""
cost_logger.py - Shared cost logging module for direct API calls.

Import this in any Python script that calls an AI API directly:

    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # or: sys.path.insert(0, '/home/openclaw/.openclaw/workspace/scripts')
    from cost_logger import log_cost

    log_cost(
        model="grok-4-1-fast-non-reasoning",
        input_tokens=1234,
        output_tokens=56,
        source="xread.py"
    )
"""

import json
import os
from datetime import datetime, timezone

LOG_FILE = "/home/openclaw/logs/direct-api-costs.jsonl"


def log_cost(model: str, input_tokens: int, output_tokens: int, source: str, timestamp_utc: str = None):
    """
    Append a cost record to the direct API costs log.

    Args:
        model:          Model name used (e.g. "grok-4-1-fast-non-reasoning")
        input_tokens:   Number of input/prompt tokens
        output_tokens:  Number of output/completion tokens
        source:         Calling script name (e.g. "xread.py")
        timestamp_utc:  ISO8601 UTC timestamp (defaults to now)
    """
    try:
        ts = timestamp_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = {
            "ts": ts,
            "model": str(model),
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "source": str(source),
        }

        # Ensure log directory exists
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

        # Append mode is atomic on Linux for small writes — no extra locking needed
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        # Silent failure — never crash the calling script
        pass
