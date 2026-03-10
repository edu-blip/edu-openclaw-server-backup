#!/usr/bin/env node
/**
 * asana-push.js
 * Pushes a pending-approved check-in to Asana.
 * Called by the main Tony agent after Edu approves in Slack.
 *
 * Usage:
 *   node fathom/asana-push.js <refId> [options]
 *
 * Options:
 *   --delete 2,5         Remove action items at positions 2 and 5 (1-indexed)
 *   --edit "3: new text" Replace action item 3 with new text
 *   --reject             Discard the pending file without pushing
 *
 * Examples:
 *   node fathom/asana-push.js checkin-1772532000123
 *   node fathom/asana-push.js checkin-1772532000123 --delete 2,5
 *   node fathom/asana-push.js checkin-1772532000123 --edit "3: Updated task text" --delete 7
 *   node fathom/asana-push.js checkin-1772532000123 --reject
 *
 * Output: JSON summary to stdout
 */

const fs = require('fs');
const path = require('path');
const https = require('https');

const ASANA_PAT = process.env.ASANA_PAT;
const ASANA_PROJECT_CHECKIN = process.env.ASANA_PROJECT_CHECKIN || '1207588849301630';
const PENDING_DIR = path.join(__dirname, 'pending-asana');
const PUSHED_DIR = path.join(__dirname, 'pending-asana', 'pushed');
const REJECTED_DIR = path.join(__dirname, 'pending-asana', 'rejected');
const LOG_FILE = path.join(__dirname, 'processor.log');

if (!ASANA_PAT) {
  console.log(JSON.stringify({ error: 'ASANA_PAT not set' }));
  process.exit(1);
}

// ── Arg parsing ───────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const refId = args[0];

if (!refId) {
  console.log(JSON.stringify({ error: 'Usage: node asana-push.js <refId> [--delete N,M] [--edit "N: text"] [--reject]' }));
  process.exit(1);
}

// Validate refId format to prevent injection
if (!/^[a-zA-Z0-9_-]{4,120}$/.test(refId)) {
  console.log(JSON.stringify({ error: 'Invalid refId format' }));
  process.exit(1);
}

const isReject = args.includes('--reject');

// Parse --delete indices (1-indexed, comma-separated)
const deleteArg = args.indexOf('--delete');
const toDelete = new Set();
if (deleteArg !== -1 && args[deleteArg + 1]) {
  args[deleteArg + 1].split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n)).forEach(n => toDelete.add(n));
}

// Parse --edit "N: text" (multiple allowed)
const edits = {}; // { index: newText }
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--edit' && args[i + 1]) {
    const match = args[i + 1].match(/^(\d+):\s*(.+)$/);
    if (match) edits[parseInt(match[1], 10)] = match[2].trim();
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function log(msg) {
  const line = `[${new Date().toISOString()}] [ASANA-PUSH] ${msg}\n`;
  process.stdout.write(line);
  fs.appendFileSync(LOG_FILE, line);
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

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  // Find the pending file (search by exact refId or partial match)
  const files = fs.readdirSync(PENDING_DIR).filter(f => f.endsWith('.json') && f.includes(refId));
  if (files.length === 0) {
    const result = { error: `No pending file found for refId: ${refId}`, pending_dir: PENDING_DIR };
    console.log(JSON.stringify(result));
    process.exit(1);
  }

  const filePath = path.join(PENDING_DIR, files[0]);

  // Guard against path traversal
  const resolvedPending = path.resolve(PENDING_DIR);
  if (!path.resolve(filePath).startsWith(resolvedPending + path.sep)) {
    console.log(JSON.stringify({ error: 'Path traversal detected' }));
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(filePath));

  if (data.status === 'pushed') {
    console.log(JSON.stringify({ error: 'Already pushed to Asana', refId }));
    process.exit(1);
  }

  // Handle reject
  if (isReject) {
    data.status = 'rejected';
    data.rejectedAt = new Date().toISOString();
    fs.mkdirSync(REJECTED_DIR, { recursive: true });
    fs.renameSync(filePath, path.join(REJECTED_DIR, files[0]));
    log(`Rejected: ${refId}`);
    console.log(JSON.stringify({ status: 'rejected', refId }));
    return;
  }

  const { meetingTitle, meetingDate, extracted, source } = data;
  let actionItems = [...(extracted.action_items || [])];

  // Apply edits (1-indexed)
  for (const [idxStr, newText] of Object.entries(edits)) {
    const idx = parseInt(idxStr, 10) - 1;
    if (idx >= 0 && idx < actionItems.length) {
      log(`Edit item ${idx + 1}: "${actionItems[idx].task}" → "${newText}"`);
      actionItems[idx] = { ...actionItems[idx], task: newText };
    }
  }

  // Apply deletes (1-indexed, remove in reverse order to preserve indices)
  const deletesSorted = [...toDelete].sort((a, b) => b - a);
  for (const idx of deletesSorted) {
    const i = idx - 1;
    if (i >= 0 && i < actionItems.length) {
      log(`Delete item ${idx}: "${actionItems[i].task}"`);
      actionItems.splice(i, 1);
    }
  }

  log(`Pushing to Asana: "${meetingTitle}" (${meetingDate}) — ${actionItems.length} tasks`);

  // Build parent task notes
  const dateFormatted = new Date(meetingDate + 'T12:00:00Z').toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC'
  });

  let notes = `Check-in Summary — ${dateFormatted}\n${'─'.repeat(50)}\n\n`;
  if (extracted.meeting_summary) notes += `📋 OVERVIEW\n${extracted.meeting_summary}\n\n`;
  if (extracted.key_decisions?.length) {
    notes += `✅ KEY DECISIONS\n${extracted.key_decisions.map(d => `• ${d}`).join('\n')}\n\n`;
  }
  if (actionItems.length) {
    notes += `🎯 ACTION ITEMS (${actionItems.length})\n`;
    actionItems.forEach(i => {
      notes += `• ${i.task} — ${i.owner || 'Edu'}${i.due ? ` [due: ${i.due}]` : ''}\n`;
    });
    notes += '\n';
  }
  if (extracted.blockers?.length) {
    notes += `🚧 BLOCKERS\n${extracted.blockers.map(b => `• ${b}`).join('\n')}\n\n`;
  }
  notes += `\n─ Auto-generated by Tony from ${source === 'google_meet' ? 'Google Meet' : 'Fathom'} transcript`;

  // Create parent task
  const taskName = `${meetingDate} · ${meetingTitle} — Check-in Summary`;
  const parent = await asanaPost('/tasks', {
    data: { name: taskName, notes, projects: [ASANA_PROJECT_CHECKIN], due_on: meetingDate }
  });
  log(`Parent task created: ${parent.gid} — "${taskName}"`);

  const subtasks = [];
  for (const item of actionItems) {
    const subName = `${item.task}${item.owner && item.owner !== 'Edu' ? ` (${item.owner})` : ''}`;
    try {
      const sub = await asanaPost(`/tasks/${parent.gid}/subtasks`, {
        data: { name: subName, ...(item.due ? { due_on: item.due } : {}) }
      });
      log(`  ↳ Subtask: ${sub.gid} — "${subName}"`);
      subtasks.push({ gid: sub.gid, name: subName });
    } catch (err) {
      log(`  ✗ Subtask failed: "${subName}": ${err.message}`);
    }
    await new Promise(r => setTimeout(r, 400));
  }

  // Mark as pushed
  data.status = 'pushed';
  data.pushedAt = new Date().toISOString();
  data.asanaTaskGid = parent.gid;
  data.asanaTaskName = taskName;
  data.appliedEdits = edits;
  data.appliedDeletes = [...toDelete];
  data.finalActionItems = actionItems;

  fs.mkdirSync(PUSHED_DIR, { recursive: true });
  fs.writeFileSync(path.join(PUSHED_DIR, files[0]), JSON.stringify(data, null, 2), { mode: 0o600 });
  fs.unlinkSync(filePath);

  const result = {
    status: 'pushed',
    refId,
    asanaTaskGid: parent.gid,
    asanaTaskUrl: `https://app.asana.com/0/${ASANA_PROJECT_CHECKIN}/${parent.gid}`,
    taskName,
    subtasksCreated: subtasks.length,
    subtasks
  };

  console.log(JSON.stringify(result, null, 2));
  log(`Done. ${subtasks.length} subtasks pushed. Task GID: ${parent.gid}`);
}

main().catch(err => {
  console.log(JSON.stringify({ error: err.message }));
  log(`FATAL: ${err.message}`);
  process.exit(1);
});
