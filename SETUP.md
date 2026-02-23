# SETUP.md - Pending Configuration & Setup Tasks

This file tracks everything related to Tony's setup, skills, and agent configuration.
When Edu is at a terminal, just ask: **"What's on the setup list?"** and I'll run through all of this.

---

## 🖥️ Server / System

- [x] **Fix timezone** → Done 2026-02-21, set to America/Los_Angeles (PST)
- [x] **Add OpenAI API key** → Done 2026-02-21
- [ ] **Fix browser device token mismatch** → rotate/reissue device token so browser tool works (needed for reading X posts, web automation, etc.)
- [x] **Set up Brave Search API key** → Done 2026-02-21. Set via BRAVE_API_KEY in .env
- [x] **Elevated permissions — DECIDED: NO** → Security-first decision (2026-02-21). Risk of prompt injection + root = too dangerous. Instead: build narrow wrapper scripts for specific approved tasks (restart openclaw, install approved skills only). See research Edu shared.
- [ ] **Build narrow wrapper scripts** → e.g., `/opt/scripts/restart-openclaw.sh`, `/opt/scripts/install-skill.sh` — specific safe commands only, not broad root access

## 🧠 Skills to Install

- [ ] **Humanizer skill** → find + install from ClaWHub or similar
- [ ] **Bird / Twitter skill** → for reading tweets shared in chat (check ClaWHub for the exact name)

## 🔧 Other

- [x] **Audio/voice note transcription** → Working as of 2026-02-21. Slack file downloads fixed (added `files:read` scope).
- [x] **Fix Slack file downloads** → Fixed 2026-02-21. Added `files:read` + other missing scopes to Slack bot.

---

*Last updated: 2026-02-21*
