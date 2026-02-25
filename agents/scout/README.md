# Scout — Research & Intel Sub-Agent

Scout is an on-demand research sub-agent. Tony spawns Scout when a task requires web research, X/Twitter search, knowledge base queries, or URL reading.

## How to Spawn Scout

Tony uses `sessions_spawn` with Scout's soul embedded in the task:

```
Task format:
[SCOUT SOUL]
<contents of agents/scout/SOUL.md>

[YOUR TASK]
<specific research request>
```

### Example spawn call (from Tony's internal logic):
```json
{
  "task": "<scout soul> + <task description>",
  "model": "google/gemini-2.0-flash-001",
  "label": "scout-<topic>",
  "runTimeoutSeconds": 120
}
```

## When to Use Scout

| Trigger | Example |
|---------|---------|
| "Research X" | "Look up what Edu's top clients are posting about" |
| "Find competitors" | "Search for LinkedIn content agencies on X" |
| "Summarize a URL" | "Read this article and pull the key points" |
| "KB query" | "Search the knowledge base for our ICP definition" |
| "X post" | "What did this person post recently?" |

## Model
`google/gemini-2.0-flash-001` — fast and cheap, perfect for retrieval tasks.

## Status
✅ Ready to use. Tony loads `agents/scout/SOUL.md` and embeds it in the task prompt.
