# Nightly Memory Extraction — Cron Prompt

You are running as a nightly extraction job. Your task: read today's session transcripts and extract important information that should be preserved in memory files.

## Steps

1. Check today's date and read `memory/YYYY-MM-DD.md` (today's daily log) to see what's already been captured.

2. List session files modified today:
   ```
   find ~/.openclaw/agents/main/sessions/ -name "*.jsonl" -mtime 0 -not -name "*.deleted*" -not -name "*.lock"
   ```

3. For each session file modified today, read the last 200 lines and extract:
   - **Decisions made** (e.g., "decided to use X instead of Y")
   - **New preferences or rules** Edu stated
   - **Business facts** (client updates, revenue changes, pipeline info)
   - **Technical changes** (config updates, new scripts, integrations)
   - **Action items** that were agreed on but may not have been logged

4. Compare extractions against what's already in today's daily log. Only add NEW information.

5. Append new items to `memory/YYYY-MM-DD.md` under a `## Nightly Extraction` section.

6. If any extraction is clearly durable (a rule, preference, or business fact that should persist), flag it with `→ PROMOTE TO MEMORY.md` so the main agent can review and promote it.

7. Reply with a brief summary of what was extracted, or NO_REPLY if nothing new was found.

## Rules
- Do NOT modify MEMORY.md directly. Only append to the daily log.
- Do NOT include sensitive data (API keys, tokens, passwords) in extractions.
- Keep each extraction to 1-2 lines. Be specific, not verbose.
- Include the session context (e.g., "from Slack DM thread about memory audit").
