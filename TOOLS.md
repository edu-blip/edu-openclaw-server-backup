# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## xAI / X Search Integration

**Key:** `XAI_API_KEY` in `/root/.openclaw/.env`

### Scripts
- `scripts/xsearch.py` — Search X posts or the web via Grok Live Search
  - `python3 scripts/xsearch.py "query"` → X search (last 30 days)
  - `python3 scripts/xsearch.py --web "query"` → web search
  - `python3 scripts/xsearch.py --both "query"` → X + web
- `scripts/xread.py` — Read & summarize a specific X post URL
  - `python3 scripts/xread.py https://x.com/.../status/123` → full post summary
  - Add a second arg to ask a specific question about the post

**Model used:** `grok-4-1-fast-non-reasoning` (required for server-side tools)
**Pricing:** X Search $5/1k calls (currently free in beta)

---

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.
