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
const { execSync } = require('child_process');

const CONTENT_IDEAS_DIR = path.join(__dirname, 'content-ideas');
const LOG_FILE = path.join(__dirname, 'processor.log');
const DRIVE_FOLDER_ID = '1xiMgCRlVGhTWc79PIgaZ72zWcp9g5iq1'; // Rethoric > Marketing > LinkedIn content
const GOG_ACCOUNT = 'tony@rethoric.com';
const GOG_ENV = { ...process.env, GOG_KEYRING_PASSWORD: 'gogcli-server-keyring' };

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

  log(`Uploading to Google Drive: "${docTitle}"`);
  try {
    const result = execSync(
      `gog drive upload "${tmpFile}" --name "${docTitle}" --parent "${DRIVE_FOLDER_ID}" --convert-to=doc --account ${GOG_ACCOUNT} --json`,
      { env: GOG_ENV, encoding: 'utf8' }
    );
    let parsed;
    try { parsed = JSON.parse(result); } catch (e) { log(`Warning: could not parse upload JSON: ${e.message}`); }
    let fileId = parsed?.file?.id || parsed?.id || null;
    let url = parsed?.file?.webViewLink
      || (fileId ? `https://docs.google.com/document/d/${fileId}/edit` : null);

    // Fallback: search Drive for the doc by name if URL wasn't returned
    if (!url) {
      log(`URL not returned from upload — searching Drive for "${docTitle}"...`);
      try {
        const searchResult = execSync(
          `gog drive search "${docTitle}" --account ${GOG_ACCOUNT} --json`,
          { env: GOG_ENV, encoding: 'utf8' }
        );
        const searchParsed = JSON.parse(searchResult);
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

    // Mark the weekly file as published
    data.publishedAt = new Date().toISOString();
    data.googleDocUrl = url;
    data.googleDocId = fileId;
    fs.writeFileSync(weekFile, JSON.stringify(data, null, 2));

    // Clean up temp file
    fs.unlinkSync(tmpFile);

    // Notify Edu via Slack
    notifySlack(docTitle, url, ideas.length, data.sources?.length || 0);
  } catch (err) {
    log(`Error uploading to Drive: ${err.message}`);
    fs.unlinkSync(tmpFile);
    throw err;
  }
}

function notifySlack(title, url, ideaCount, sourceCount) {
  const https = require('https');
  const token = process.env.SLACK_BOT_TOKEN;
  if (!token) { log('No SLACK_BOT_TOKEN — skipping Slack notification'); return; }

  const opsChannel = 'C0AHBCJQJKS'; // #tony-ops
  const text = `📄 *Weekly LinkedIn content doc ready:*\n*${title}* — ${ideaCount} ideas from ${sourceCount} call(s)\n${url}`;
  const body = JSON.stringify({ channel: opsChannel, text });

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

log(`Starting weekly content doc creation for ${targetWeek}`);
createDoc(targetWeek).catch(err => {
  log(`FATAL: ${err.message}`);
  process.exit(1);
});
