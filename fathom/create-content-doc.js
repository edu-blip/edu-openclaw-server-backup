#!/usr/bin/env node
/**
 * Use Case C — Weekly LinkedIn Content Ideas Google Doc
 * Creates a Google Doc every Monday with the previous week's accumulated ideas.
 * Can also be run manually: node fathom/create-content-doc.js [YYYY-WXX]
 *
 * Usage:
 *   node fathom/create-content-doc.js            → processes current/last week
 *   node fathom/create-content-doc.js 2026-W09   → processes specific week
 */

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const CONTENT_IDEAS_DIR = path.join(__dirname, 'content-ideas');
const LOG_FILE = path.join(__dirname, 'processor.log');
const DRIVE_FOLDER_ID = '1xiMgCRlVGhTWc79PIgaZ72zWcp9g5iq1'; // Rethoric > Marketing > LinkedIn content
const GOG_ACCOUNT = 'tony@rethoric.com';
// GOG_KEYRING_PASSWORD must be set in the environment (cron injects it; never hardcode here)
if (!process.env.GOG_KEYRING_PASSWORD) {
  process.stderr.write('[FATAL] GOG_KEYRING_PASSWORD not set — refusing to run\n');
  process.exit(1);
}
const GOG_ENV = { ...process.env };

function log(msg) {
  const line = `[${new Date().toISOString()}] [USE CASE C] ${msg}\n`;
  process.stdout.write(line);
  fs.appendFileSync(LOG_FILE, line);
}

function getISOWeek(date = new Date()) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`;
}

function getWeekLabel(isoWeek) {
  // "2026-W09" → "week 9 2026"
  const [year, wPart] = isoWeek.split('-');
  const weekNum = parseInt(wPart.replace('W', ''), 10);
  return `week ${weekNum} ${year}`;
}

function formatIdeasAsMarkdown(data, isoWeek) {
  const weekLabel = getWeekLabel(isoWeek);
  const ideas = data.ideas || [];
  const sources = data.sources || [];

  let doc = `# Edu Content Ideas — ${weekLabel}\n\n`;
  doc += `_Generated automatically from ${sources.length} transcript(s)_\n\n`;
  doc += `---\n\n`;

  if (ideas.length === 0) {
    doc += `No strong ideas generated this week.\n\n`;
    doc += `**Sources reviewed:**\n`;
    sources.forEach(s => {
      doc += `- ${s.meeting} (${s.callType}) — ${s.date}\n`;
    });
    return doc;
  }

  // Group by content bucket
  const buckets = {};
  ideas.forEach(idea => {
    const bucket = idea.content_bucket || 'Uncategorized';
    if (!buckets[bucket]) buckets[bucket] = [];
    buckets[bucket].push(idea);
  });

  const bucketOrder = ['Authority', 'Growth', 'Conversion', 'Uncategorized'];
  const orderedBuckets = [
    ...bucketOrder.filter(b => buckets[b]),
    ...Object.keys(buckets).filter(b => !bucketOrder.includes(b))
  ];

  orderedBuckets.forEach(bucket => {
    doc += `## ${bucket}\n\n`;
    buckets[bucket].forEach((idea, i) => {
      doc += `### ${i + 1}. ${idea.idea}\n\n`;
      doc += `**Hook angle:** ${idea.hook_angle}\n\n`;
      if (idea.edu_post_angle) {
        doc += `**Edu's angle:** ${idea.edu_post_angle}\n\n`;
      }
      if (idea.key_points?.length) {
        doc += `**Key points:**\n`;
        idea.key_points.forEach(p => { doc += `- ${p}\n`; });
        doc += '\n';
      }
      doc += `**Source:** ${idea.source || idea.meeting || 'Unknown'}\n\n`;
      doc += `**Bucket:** ${idea.content_bucket || bucket}\n\n`;
      doc += `---\n\n`;
    });
  });

  doc += `## Sources This Week\n\n`;
  sources.forEach(s => {
    doc += `- ${s.meeting} (${s.callType}) — ${s.date}\n`;
  });

  return doc;
}

async function createDoc(isoWeek) {
  const weekFile = path.join(CONTENT_IDEAS_DIR, `week-${isoWeek}.json`);

  if (!fs.existsSync(weekFile)) {
    log(`No content ideas file found for ${isoWeek} — skipping`);
    return;
  }

  const data = JSON.parse(fs.readFileSync(weekFile));
  const ideas = data.ideas || [];
  log(`Processing ${ideas.length} ideas from week ${isoWeek} (${(data.sources || []).length} sources)`);

  const docTitle = `Edu content ideas - ${getWeekLabel(isoWeek)}`;
  const markdown = formatIdeasAsMarkdown(data, isoWeek);

  // Write temp markdown file
  const tmpFile = `/tmp/edu-content-ideas-${isoWeek}.md`;
  fs.writeFileSync(tmpFile, markdown);

  const existingDocId = data.googleDocId && data.googleDocId !== 'None' ? data.googleDocId : null;
  log(`${existingDocId ? 'Updating' : 'Creating'} Google Doc: "${docTitle}"`);
  try {
    let fileId, url;

    if (existingDocId) {
      // Update existing doc in-place using gog docs write
      const writeResult = spawnSync('gog', ['docs', 'write', existingDocId, '--file', tmpFile, '--replace', '--markdown', '--force', '--account', GOG_ACCOUNT], { env: GOG_ENV, encoding: 'utf8' });
      if (writeResult.status !== 0) throw new Error(writeResult.stderr || 'Command failed');
      fileId = existingDocId;
      url = `https://docs.google.com/document/d/${fileId}/edit`;
      log(`Updated existing Google Doc: ${docTitle} → ${url}`);
    } else {
      // Create new doc via Drive upload
      const uploadResult = spawnSync('gog', ['drive', 'upload', tmpFile, '--name', docTitle, '--parent', DRIVE_FOLDER_ID, '--convert-to=doc', '--account', GOG_ACCOUNT, '--json'], { env: GOG_ENV, encoding: 'utf8' });
      if (uploadResult.status !== 0) throw new Error(uploadResult.stderr || 'Command failed');
      const result = uploadResult.stdout;
      let parsed;
      try { parsed = JSON.parse(result); } catch (e) { log(`Warning: could not parse upload JSON: ${e.message}`); }
      fileId = parsed?.file?.id || parsed?.id || null;
      url = parsed?.file?.webViewLink
        || (fileId ? `https://docs.google.com/document/d/${fileId}/edit` : null);

      // Fallback: search Drive for the doc by name if URL wasn't returned
      if (!url) {
        log(`URL not returned from upload — searching Drive for "${docTitle}"...`);
        try {
          const searchRaw = spawnSync('gog', ['drive', 'search', docTitle, '--account', GOG_ACCOUNT, '--json'], { env: GOG_ENV, encoding: 'utf8' });
          if (searchRaw.status !== 0) throw new Error(searchRaw.stderr || 'Command failed');
          const searchParsed = JSON.parse(searchRaw.stdout);
          const files = searchParsed?.files || searchParsed?.items || [];
          const match = files.find(f => f.name === docTitle);
          if (match) {
            fileId = match.id;
            url = match.webViewLink || `https://docs.google.com/document/d/${match.id}/edit`;
            log(`Found via search: ${url}`);
          }
        } catch (se) { log(`Search fallback failed: ${se.message}`); }
      }
      if (!url) url = 'URL unavailable — check Google Drive';
      log(`Created Google Doc: ${docTitle} → ${url}`);
    }

    // Mark the weekly file as published
    data.publishedAt = new Date().toISOString();
    data.googleDocUrl = url;
    data.googleDocId = fileId;
    fs.writeFileSync(weekFile, JSON.stringify(data, null, 2));

    // Clean up temp file
    fs.unlinkSync(tmpFile);

    // Notify Edu via Slack
    notifySlack(docTitle, url, ideas.length, data.sources?.length || 0, ideas);
  } catch (err) {
    log(`Error uploading to Drive: ${err.message}`);
    fs.unlinkSync(tmpFile);
    throw err;
  }
}

function notifySlack(title, url, ideaCount, sourceCount, ideas) {
  const https = require('https');
  const token = process.env.SLACK_BOT_TOKEN;
  if (!token) { log('No SLACK_BOT_TOKEN — skipping Slack notification'); return; }

  const alecChannel = 'C0AKHKDJ2MC'; // #alec-content

  // Build a formatted digest for Alec
  let digest = `📬 *New batch of content ideas ready — week ${getISOWeek()}*\n`;
  digest += `${ideaCount} idea(s) from ${sourceCount} call(s) — <${url}|full doc>\n\n`;

  if (ideas && ideas.length > 0) {
    // Group by bucket
    const buckets = {};
    ideas.forEach(idea => {
      const b = idea.content_bucket || 'Uncategorized';
      if (!buckets[b]) buckets[b] = [];
      buckets[b].push(idea);
    });
    const bucketOrder = ['Growth', 'Authority', 'Conversion', 'Uncategorized'];
    const ordered = [...bucketOrder.filter(b => buckets[b]), ...Object.keys(buckets).filter(b => !bucketOrder.includes(b))];
    ordered.forEach(bucket => {
      digest += `*${bucket}*\n`;
      buckets[bucket].forEach((idea, i) => {
        digest += `${i + 1}. ${idea.idea}\n`;
        if (idea.hook_angle) digest += `   _Hook angle: ${idea.hook_angle}_\n`;
      });
      digest += '\n';
    });
  }

  digest += `Which ones should I develop first?`;

  const body = JSON.stringify({ channel: alecChannel, text: digest });

  const req = https.request({
    hostname: 'slack.com', path: '/api/chat.postMessage', method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`, 'Content-Length': Buffer.byteLength(body) }
  }, res => { let d = ''; res.on('data', c => d += c); res.on('end', () => log(`Slack notified: ${JSON.parse(d).ok}`)); });
  req.on('error', e => log(`Slack error: ${e.message}`));
  req.write(body); req.end();
}

// Main
const targetWeek = process.argv[2] || (() => {
  // If run on Monday, process the PREVIOUS week's ideas (already accumulated)
  // If run manually with a week arg, use that week
  const today = new Date();
  if (today.getDay() === 1) {
    // Monday: process last week
    const lastWeek = new Date(today);
    lastWeek.setDate(today.getDate() - 7);
    return getISOWeek(lastWeek);
  }
  return getISOWeek(); // fallback: current week (for manual runs)
})();

// Validate isoWeek format before using it in shell commands
const ISO_WEEK_RE = /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/;
if (!ISO_WEEK_RE.test(targetWeek)) {
  log(`FATAL: Invalid week format "${targetWeek}" — expected YYYY-WNN`);
  process.exit(1);
}

log(`Starting weekly content doc creation for ${targetWeek}`);
createDoc(targetWeek).catch(err => {
  log(`FATAL: ${err.message}`);
  process.exit(1);
});
