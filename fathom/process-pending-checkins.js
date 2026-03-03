#!/usr/bin/env node
/**
 * process-pending-checkins.js
 * Processes all .json files in fathom/pending-checkins/ through Use Case A (Asana).
 * Run once to backfill check-ins that accumulated while the stub was active.
 *
 * Usage: node fathom/process-pending-checkins.js [--dry-run]
 */

const fs = require('fs');
const path = require('path');
const https = require('https');

const DRY_RUN = process.argv.includes('--dry-run');
const PENDING_DIR = path.join(__dirname, 'pending-checkins');
const LOG_FILE = path.join(__dirname, 'processor.log');

const ASANA_PAT = process.env.ASANA_PAT;
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
const ASANA_PROJECT_CHECKIN = '1207588849301630';

function log(msg) {
  const line = `[${new Date().toISOString()}] [BACKFILL] ${msg}\n`;
  process.stdout.write(line);
  fs.appendFileSync(LOG_FILE, line);
}

if (!ASANA_PAT || !ANTHROPIC_API_KEY) {
  log('ERROR: ASANA_PAT and ANTHROPIC_API_KEY must be set in environment.');
  process.exit(1);
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function callClaude(systemPrompt, userContent) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      model: 'claude-sonnet-4-5',
      max_tokens: 2048,
      system: systemPrompt,
      messages: [{ role: 'user', content: userContent }]
    });
    const req = https.request({
      hostname: 'api.anthropic.com',
      path: '/v1/messages',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
        'Content-Length': Buffer.byteLength(body)
      }
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)?.content?.[0]?.text || ''); }
        catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function asanaPost(path, body) {
  return new Promise((resolve, reject) => {
    const bodyStr = JSON.stringify(body);
    const req = https.request({
      hostname: 'app.asana.com',
      path: `/api/1.0${path}`,
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${ASANA_PAT}`,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(bodyStr)
      }
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.errors) reject(new Error(JSON.stringify(parsed.errors)));
          else resolve(parsed.data);
        } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.write(bodyStr);
    req.end();
  });
}

function getTitle(p) { return p?.title || p?.meeting_title || 'Team Check-in'; }
function getTranscript(p) {
  const t = p?.transcript;
  if (!t) return '';
  if (typeof t === 'string') return t;
  if (Array.isArray(t)) return t.map(s => `${s?.speaker?.display_name || 'Speaker'}: ${s?.text || ''}`).join('\n');
  return '';
}
function getSummary(p) { return p?.default_summary?.markdown_formatted || p?.summary || ''; }
function getMeetingDate(p) {
  return (p?.scheduled_start_time || p?.recording_start_time || new Date().toISOString()).split('T')[0];
}

// ── Process one check-in ──────────────────────────────────────────────────────

async function processOne(filePath) {
  const payload = JSON.parse(fs.readFileSync(filePath));
  const meetingTitle = getTitle(payload);
  const meetingDate = getMeetingDate(payload);
  const transcript = getTranscript(payload);
  const summary = getSummary(payload);

  log(`Processing: "${meetingTitle}" (${meetingDate}) — ${path.basename(filePath)}`);

  if (!transcript && !summary) {
    log(`  ⚠️  No transcript or summary — skipping.`);
    return false;
  }

  const systemPrompt = `You are an ops assistant processing a team check-in transcript for Edu Mussali, founder of Rethoric (a LinkedIn content ghostwriting agency).

Extract a structured summary suitable for creating an Asana task with action items.

Return ONLY valid JSON:
{
  "meeting_summary": "2-4 sentence summary of what was discussed and decided",
  "key_decisions": ["decision 1"],
  "action_items": [{"task": "verb-led description", "owner": "first name or Edu", "due": "YYYY-MM-DD or null"}],
  "blockers": ["blocker"]
}

Rules: action items must start with a verb. Default owner to "Edu" if unclear. Max 10 action items.`;

  const userContent = `Meeting: ${meetingTitle} (${meetingDate})\n\nTRANSCRIPT:\n${transcript || 'None.'}\n\nSUMMARY:\n${summary || 'None.'}`;

  const raw = await callClaude(systemPrompt, userContent);
  let parsed;
  try {
    parsed = JSON.parse(raw.replace(/```json|```/g, '').trim());
  } catch (e) {
    log(`  ✗ JSON parse failed: ${e.message}`);
    return false;
  }

  // Build notes
  const dateFormatted = new Date(meetingDate + 'T12:00:00Z').toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC'
  });

  let notes = `Check-in Summary — ${dateFormatted}\n${'─'.repeat(50)}\n\n`;
  if (parsed.meeting_summary) notes += `📋 OVERVIEW\n${parsed.meeting_summary}\n\n`;
  if (parsed.key_decisions?.length) {
    notes += `✅ KEY DECISIONS\n${parsed.key_decisions.map(d => `• ${d}`).join('\n')}\n\n`;
  }
  if (parsed.action_items?.length) {
    notes += `🎯 ACTION ITEMS (${parsed.action_items.length})\n`;
    parsed.action_items.forEach(i => {
      notes += `• ${i.task} — ${i.owner}${i.due ? ` [due: ${i.due}]` : ''}\n`;
    });
    notes += '\n';
  }
  if (parsed.blockers?.length) {
    notes += `🚧 BLOCKERS\n${parsed.blockers.map(b => `• ${b}`).join('\n')}\n\n`;
  }
  notes += `\n─ Backfilled by Tony from ${payload.source === 'google_meet' ? 'Google Meet' : 'Fathom'} transcript`;

  const taskName = `${meetingDate} · ${meetingTitle} — Check-in Summary`;

  if (DRY_RUN) {
    log(`  [DRY RUN] Would create: "${taskName}" with ${parsed.action_items?.length || 0} subtasks`);
    log(`  Notes preview:\n${notes.slice(0, 300)}...`);
    return true;
  }

  const parent = await asanaPost('/tasks', {
    data: { name: taskName, notes, projects: [ASANA_PROJECT_CHECKIN], due_on: meetingDate }
  });
  log(`  ✓ Parent task: ${parent.gid} — "${taskName}"`);

  for (const item of (parsed.action_items || [])) {
    const subName = `${item.task}${item.owner && item.owner !== 'Edu' ? ` (${item.owner})` : ''}`;
    try {
      const sub = await asanaPost(`/tasks/${parent.gid}/subtasks`, {
        data: { name: subName, ...(item.due ? { due_on: item.due } : {}) }
      });
      log(`    ↳ Subtask: ${sub.gid} — "${subName}"`);
    } catch (err) {
      log(`    ✗ Subtask failed: ${err.message}`);
    }
  }

  // Move processed file out of pending
  const doneDir = path.join(PENDING_DIR, 'processed');
  fs.mkdirSync(doneDir, { recursive: true });
  fs.renameSync(filePath, path.join(doneDir, path.basename(filePath)));
  log(`  → Moved to processed/`);
  return true;
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const files = fs.readdirSync(PENDING_DIR)
    .filter(f => f.endsWith('.json'))
    .map(f => path.join(PENDING_DIR, f))
    .sort(); // oldest first

  if (files.length === 0) {
    log('No pending check-ins found.');
    return;
  }

  log(`Found ${files.length} pending check-in(s). DRY_RUN=${DRY_RUN}`);

  let ok = 0, fail = 0;
  for (const file of files) {
    try {
      const success = await processOne(file);
      if (success) ok++; else fail++;
    } catch (err) {
      log(`  ✗ Error on ${path.basename(file)}: ${err.message}`);
      fail++;
    }
    // Small delay between API calls
    await new Promise(r => setTimeout(r, 1500));
  }

  log(`Done. ${ok} succeeded, ${fail} failed/skipped.`);
}

main().catch(err => { log(`FATAL: ${err.message}`); process.exit(1); });
