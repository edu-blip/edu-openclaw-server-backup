#!/usr/bin/env node
/**
 * asana-digest.js
 * Fetches tasks assigned to Edu that are due soon or overdue.
 * Used by heartbeat checks and on-demand queries.
 *
 * Usage:
 *   node asana-digest.js              → tasks due in next 48h + overdue
 *   node asana-digest.js --all        → all incomplete tasks assigned to Edu
 *   node asana-digest.js --project <gid>  → all tasks in a specific project
 *
 * Output: JSON to stdout
 */

const https = require('https');

const ASANA_PAT = process.env.ASANA_PAT;
const ASANA_WORKSPACE = process.env.ASANA_WORKSPACE || '1206594553706994';
const ASANA_USER_GID = process.env.ASANA_USER_GID || '1206594553352666'; // Eduardo Mussali

if (!ASANA_PAT) {
  console.error(JSON.stringify({ error: 'ASANA_PAT not set' }));
  process.exit(1);
}

const args = process.argv.slice(2);
const mode = args.includes('--all') ? 'all'
  : args.includes('--project') ? 'project'
  : 'upcoming';

const projectGid = mode === 'project' ? args[args.indexOf('--project') + 1] : null;

function asanaGet(path) {
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: 'app.asana.com',
      path: `/api/1.0${path}`,
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${ASANA_PAT}`,
        'Accept': 'application/json'
      }
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.errors) reject(new Error(JSON.stringify(parsed.errors)));
          else resolve(parsed.data);
        } catch (e) {
          reject(new Error(`Parse error: ${e.message}`));
        }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

function toDateStr(d) {
  return d.toISOString().split('T')[0];
}

async function main() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const in48h = new Date(today);
  in48h.setDate(in48h.getDate() + 2);

  let tasks = [];

  if (mode === 'project' && projectGid) {
    // Fetch all tasks in a specific project
    const fields = 'gid,name,due_on,completed,assignee,notes,permalink_url';
    tasks = await asanaGet(`/projects/${projectGid}/tasks?opt_fields=${fields}&completed_since=now&limit=100`);
  } else {
    // Fetch tasks assigned to Edu across workspace
    const fields = 'gid,name,due_on,completed,projects,permalink_url,notes';
    const assignee = ASANA_USER_GID;
    const params = new URLSearchParams({
      assignee,
      workspace: ASANA_WORKSPACE,
      completed_since: 'now',
      opt_fields: fields,
      limit: '100'
    });
    tasks = await asanaGet(`/tasks?${params.toString()}`);
  }

  if (!Array.isArray(tasks)) {
    console.log(JSON.stringify({ error: 'Unexpected response', raw: tasks }));
    process.exit(1);
  }

  // Filter by due date for upcoming mode
  let filtered = tasks;
  if (mode === 'upcoming') {
    filtered = tasks.filter(t => {
      if (!t.due_on) return false;
      const due = new Date(t.due_on + 'T12:00:00Z');
      return due <= in48h; // overdue or due within 48h
    });
  }

  // Sort by due date (overdue first)
  filtered.sort((a, b) => {
    if (!a.due_on) return 1;
    if (!b.due_on) return -1;
    return a.due_on.localeCompare(b.due_on);
  });

  const todayStr = toDateStr(today);
  const result = {
    fetched_at: new Date().toISOString(),
    mode,
    total: filtered.length,
    tasks: filtered.map(t => ({
      gid: t.gid,
      name: t.name,
      due_on: t.due_on || null,
      status: !t.due_on ? 'no_due_date'
        : t.due_on < todayStr ? 'overdue'
        : t.due_on === todayStr ? 'due_today'
        : 'upcoming',
      projects: (t.projects || []).map(p => p.name).join(', '),
      url: t.permalink_url || null
    }))
  };

  console.log(JSON.stringify(result, null, 2));
}

main().catch(err => {
  console.error(JSON.stringify({ error: err.message }));
  process.exit(1);
});
