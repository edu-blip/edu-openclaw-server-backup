# BACKLOG.md — Projects & To-Dos

Prioritized list of upcoming builds. Update as things get done or re-prioritized.

---

## 🔴 Active / In Progress
_(nothing currently in progress)_

---

## 🟡 Queued — Ready to Build

### 1. Content Persistent Agent
**Added:** 2026-02-26 | **Requested by:** Edu
**See:** Full scope below ↓

### 2. Fathom Use Case A — Asana Check-In Integration
**Added:** initial setup | **Blocked by:** Asana PAT + Project ID from Edu
**What:** After team check-in calls, auto-create Asana tasks from action items
**Status:** Code ready, waiting on credentials

---

## 🔵 Scoped — Needs Prioritization

_(nothing here yet)_

---

## 💡 Ideas / Not Yet Scoped

- Rethoric Platform takeover (replace Marco dependency) — HIGH complexity, discuss timing
- Proposal creation automation
- CRM updates after sales calls
- Content interview prep + question generation

---

---

# 📋 SCOPE: Content Persistent Agent

## What It Is
A persistent sub-agent with its own memory, focused entirely on Edu's LinkedIn content. Unlike Tony (general ops), this agent specializes in content — and gets better at it over time as it accumulates context about Edu's voice, what's worked, what's been posted, and how the strategy evolves.

Tony orchestrates; the content agent executes all content-related tasks.

## Why It Makes Sense
Right now content extraction is wired into the Fathom processor (Tony's code). It works, but it has no memory, no research capability, and can't go deeper than a single transcript. A dedicated agent would:
- Build a persistent model of Edu's voice and content history
- Handle on-demand ideation (not just weekly extraction)
- Eventually let the ghostwriter skip the interview entirely

## Phases

### Phase 1 — Foundation (start here)
- Move content extraction logic out of `processor.js` into the content agent
- Give the agent its own memory: `content-agent/MEMORY.md` (voice, patterns, what's worked)
- Give it a strategy file: `content-agent/strategy.md` (current quarterly goals, bucket targets, conversion cap)
- Tony routes Fathom webhooks to the content agent instead of handling extraction directly
- Weekly doc generation stays automated, but now runs through the content agent

### Phase 2 — On-Demand Ideation
- Edu can say in Slack: *"give me 5 ideas on [topic/theme]"*
- Content agent generates ideas with personalized `edu_post_angle` without needing a transcript
- Pulls from its growing memory of Edu's story, business context, and past ideas

### Phase 3 — Research Layer
- Agent monitors what's trending in Edu's ICP world (LinkedIn, X, newsletters, funding news)
- Surfaces "here's a trending topic + here's Edu's angle on it"
- Feeds into the weekly doc alongside transcript-extracted ideas

### Phase 4 — Ghost-Writeable Drafts
- Doc gets detailed enough that the ghostwriter can create posts without interviewing Edu
- Agent drafts post outlines or full drafts from the weekly ideas doc
- Feedback loop: Edu approves/rejects → agent learns what hits

## What It Needs Access To
- All Fathom transcripts (already in `/workspace/fathom/archive/`)
- Google Drive — read/write weekly content docs
- Web search — for research layer (Phase 3)
- Its own memory files (voice, strategy, content history)
- Slack — to receive on-demand requests from Edu

## Memory Structure
```
content-agent/
  MEMORY.md         ← Edu's voice patterns, what's worked, audience reactions
  strategy.md       ← Current quarterly goals, bucket mix targets
  published.md      ← Track of published posts (Phase 3+)
  ideas-archive/    ← All past weekly idea JSONs (already exists in fathom/content-ideas/)
```

## Integration with Current System
- `processor.js` currently handles extraction — becomes a thin router that calls the content agent
- `create-content-doc.js` stays but gets called by the content agent
- No disruption to current Fathom webhook flow

## Open Questions Before Building
1. What are Edu's content goals for Q1/Q2 2026? (bucket mix targets)
2. Does Edu want the agent to have its own Slack handle, or route through Tony?
3. Any posts already published we should feed in as "voice examples"?
