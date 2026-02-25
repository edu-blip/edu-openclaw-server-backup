# ORGCHART.md — Rethoric AI Agent Team

This is the org chart for Tony's sub-agent team. Each agent has a defined role, identity, and model profile. Tony (main agent) orchestrates all of them.

---

## 🏛️ Org Structure

```
                    ┌─────────────┐
                    │    EDU      │
                    │  (Human)    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │    TONY     │
                    │  CoS / COO  │
                    │ Orchestrator│
                    └──┬──┬──┬───┘
           ┌───────────┘  │  └──────────┐
     ┌─────▼─────┐  ┌─────▼─────┐  ┌───▼──────┐
     │   SCOUT   │  │  SCRIBE   │  │   REX    │
     │ Research  │  │  Content  │  │ Outreach │
     └───────────┘  └───────────┘  └──────────┘
                           │
                    ┌──────▼──────┐
                    │    IRIS     │
                    │    Comms    │
                    └─────────────┘
```

---

## 👤 Agent Profiles

### Tony — Chief of Staff / COO-in-Training
- **Role:** Main orchestrator. Manages all sub-agents, owns decisions, interfaces directly with Edu.
- **Responsibilities:** Task delegation, memory management, cross-agent coordination, final output review
- **Model:** `claude-sonnet-4-6` (default)
- **Lives in:** Main session (this agent)
- **Reports to:** Edu

---

### Scout — Research & Intel
- **Emoji:** 🔍
- **Role:** The eyes and ears. Finds, retrieves, and synthesizes information.
- **Responsibilities:**
  - Web research (Brave, web_fetch)
  - X/Twitter search and post reading (xsearch.py, xread.py)
  - Knowledge base queries (kb/search.py)
  - Competitor intel, prospect research, content references
- **Model:** `gemini-flash` (fast, cheap, good enough for retrieval)
- **Spawned by:** Tony on-demand for research tasks
- **Reports to:** Tony

---

### Scribe — Content & Documents
- **Emoji:** ✍️
- **Role:** The wordsmith. Processes interviews, creates content, writes drafts.
- **Responsibilities:**
  - Fathom transcript processing (Use Case B & C)
  - LinkedIn post drafting
  - Google Doc creation and updates
  - Content calendar management
  - Interview question prep
- **Model:** `claude-sonnet-4-6` (quality writing needs a strong model)
- **Spawned by:** Tony (triggered by Fathom webhooks or manual requests)
- **Reports to:** Tony

---

### Rex — Outreach & Pipeline
- **Emoji:** 🦴
- **Role:** The hunter. Runs outreach ops, manages pipeline activity.
- **Responsibilities:**
  - Apollo list building and export
  - Clay enrichment workflows
  - Botdog campaign management (connection requests + messages)
  - Sales Navigator prospecting
  - Weekly prospect list delivery to clients
- **Model:** `gemini-flash` (structured, task-oriented work)
- **Spawned by:** Tony on-demand or on schedule
- **Reports to:** Tony
- **Status:** 🔴 Not yet built — awaiting outreach tool integrations

---

### Iris — Comms & Scheduling
- **Emoji:** 🌈
- **Role:** The communicator. Manages email, calendar, and client-facing updates.
- **Responsibilities:**
  - Email triage and drafting
  - Calendar management and reminders
  - Client update messages
  - Meeting scheduling and follow-ups
- **Model:** `claude-sonnet-4-6` (comms quality matters)
- **Spawned by:** Tony on heartbeat or on-demand
- **Reports to:** Tony
- **Status:** 🔴 Not yet built — awaiting email/calendar integrations

---

## 📊 Status Summary

| Agent  | Role              | Model           | Status         |
|--------|-------------------|-----------------|----------------|
| Tony   | Orchestrator      | claude-sonnet-4-6 | ✅ Live        |
| Scout  | Research & Intel  | gemini-flash    | 🟡 Ready to build |
| Scribe | Content & Docs    | claude-sonnet-4-6 | 🟡 Partial (Fathom) |
| Rex    | Outreach & Pipeline | gemini-flash  | 🔴 Needs integrations |
| Iris   | Comms & Scheduling | claude-sonnet-4-6 | 🔴 Needs integrations |

---

## 🔄 How Agents Are Spawned

Tony uses `sessions_spawn` to spin up sub-agents on demand:
- Each sub-agent gets a task, a model, and relevant context
- Results route back to Tony (or directly to a channel when configured)
- Sub-agents are stateless — they do one job and close
- Future: each gets a `SOUL.md` loaded via task context for consistent personality

---

## 📝 Next Steps

1. **Scout** — Build first. Simple research agent, high utility, low complexity.
2. **Scribe** — Fathom processor is 50% there. Extend for LinkedIn drafts.
3. **Rex** — Map out Apollo/Clay/Botdog API integrations before building.
4. **Iris** — Needs email + Google Calendar access first.
5. **Soul files** — Create `agents/scout/SOUL.md`, `agents/scribe/SOUL.md`, etc.

---

*Last updated: 2026-02-24*
