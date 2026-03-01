#!/usr/bin/env node
/**
 * Use Case A — Pre-Call Briefing
 * Checks Google Calendar for upcoming "Team check-in" events within the next hour.
 * If found, sends Edu a briefing via Slack with:
 *   - All open Asana tasks (grouped by assignee) [once Asana is connected]
 *   - Overdue tasks
 *   - Topics to cover
 *
 * Runs every 15 minutes via cron. Fires briefing only once per event.
 * State tracked in: fathom/briefing-state.json
 */

const { execSync } = require('child_process');
const https = require('https');
const fs = require('fs');
const path = require('path');

const STATE_FILE = path.join(__dirname, 'briefing-state.json');
const LOG_FILE = path.join(__dirname, 'processor.log');
// GOG_KEYRING_PASSWORD must be injected via environment (cron sets it; never hardcode here)
if (!process.env.GOG_KEYRING_PASSWORD) {
  process.stderr.write('[FATAL] GOG_KEYRING_PASSWORD not set — refusing to run\n');
  process.exit(1);
}
const GOG_ENV = { ...process.env };
const GOG_ACCOUNT = 'tony@rethoric.com';
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || '';
const EDU_SLACK_CHANNEL = 'C0AHBCJQJKS'; // #tony-ops (direct briefings go here until a dedicated channel is set)

// How far ahead to look (minutes)
const LOOKAHEAD_MIN = 75;
const LOOKBACK_MIN = 45; // don't fire if event starts in less than this (already started)

function log(msg) {
  const line = `[${new Date().toISOString()}] [BRIEFING] ${msg}\n`;
  process.stdout.write(line);
  fs.appendFileSync(LOG_FILE, line);
}

function loadState() {
  if (fs.existsSync(STATE_FILE)) {
    try { return JSON.parse(fs.readFileSync(STATE_FILE)); } catch (e) {}
  }
  return { sentBriefings: {} };
}

function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

function getUpcomingCheckins() {
  try {
    const result = execSync(
      `gog calendar events --all --account ${GOG_ACCOUNT} --days 1 --json`,
      { env: GOG_ENV, encoding: 'utf8' }
    );
    const data = JSON.parse(result);
    const events = data?.events || data || [];
    const now = new Date();
    const cutoffFar = new Date(now.getTime() + LOOKAHEAD_MIN * 60000);
    const cutoffNear = new Date(now.getTime() + LOOKBACK_MIN * 60000);

    return events.filter(ev => {
      const title = (ev.summary || ev.title || '').toLowerCase();
      if (!title.includes('team check-in') && !title.includes('team check in')) return false;
      const start = new Date(ev.start?.dateTime || ev.start?.date || ev.startTime);
      return start >= cutoffNear && start <= cutoffFar;
    });
  } catch (err) {
    log(`Error fetching calendar: ${err.message}`);
    return [];
  }
}

function postToSlack(text) {
  return new Promise((resolve, reject) => {
    if (!SLACK_BOT_TOKEN) { log('No SLACK_BOT_TOKEN — skipping'); resolve(); return; }
    const body = JSON.stringify({ channel: EDU_SLACK_CHANNEL, text });
    const req = https.request({
      hostname: 'slack.com', path: '/api/chat.postMessage', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${SLACK_BOT_TOKEN}`, 'Content-Length': Buffer.byteLength(body) }
    }, res => {
      let d = ''; res.on('data', c => d += c);
      res.on('end', () => resolve(JSON.parse(d)));
    });
    req.on('error', reject);
    req.write(body); req.end();
  });
}

async function generateBriefing(event) {
  const startTime = new Date(event.start?.dateTime || event.start?.date || event.startTime);
  const minutesAway = Math.round((startTime - new Date()) / 60000);

  // TODO (Use Case A — Phase 2): Query Asana for open tasks by assignee
  // For now: send a calendar reminder + note about Asana pending
  const timeStr = startTime.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Los_Angeles' });

  let msg = `🗓️ *Team check-in in ~${minutesAway} minutes* (${timeStr} PST)\n\n`;
  msg += `*Pre-call briefing:*\n`;
  msg += `• Asana task review: ⏳ _coming soon — awaiting Asana API credentials_\n`;
  msg += `• Open action items will appear here once Asana is connected\n\n`;
  msg += `_To get Asana connected: drop your Asana Personal Access Token in a new thread._`;

  return msg;
}

async function main() {
  const state = loadState();
  const upcomingCheckins = getUpcomingCheckins();

  if (upcomingCheckins.length === 0) {
    log('No upcoming check-ins in window — nothing to do');
    process.exit(0);
  }

  for (const event of upcomingCheckins) {
    const eventId = event.id || event.uid || JSON.stringify(event.start);
    const today = new Date().toISOString().split('T')[0];
    const stateKey = `${today}:${eventId}`;

    if (state.sentBriefings[stateKey]) {
      log(`Briefing already sent for event ${eventId} — skipping`);
      continue;
    }

    log(`Upcoming check-in: "${event.summary}" at ${event.start?.dateTime || event.start?.date}`);
    const msg = await generateBriefing(event);
    const result = await postToSlack(msg);
    log(`Briefing sent: ${result?.ok ? 'ok' : result?.error}`);

    state.sentBriefings[stateKey] = new Date().toISOString();
    // Prune old entries (keep last 30 days)
    const cutoff = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    Object.keys(state.sentBriefings).forEach(k => {
      if (k.split(':')[0] < cutoff) delete state.sentBriefings[k];
    });
    saveState(state);
  }
}

main().catch(err => {
  log(`FATAL: ${err.message}`);
  process.exit(1);
});
