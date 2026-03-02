#!/usr/bin/env node
/**
 * Fathom Call Processor
 * Routes a queued webhook payload to the appropriate use case handlers.
 * Called by webhook-server.js with the path to a .json queue file.
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const { spawn } = require('child_process');

const payloadFile = process.argv[2];
if (!payloadFile || !fs.existsSync(payloadFile)) {
  console.error('Usage: node processor.js <path-to-payload.json>');
  process.exit(1);
}

// Load config
const CONFIG_FILE = path.join(__dirname, 'config.json');
const config = fs.existsSync(CONFIG_FILE) ? JSON.parse(fs.readFileSync(CONFIG_FILE)) : {};

const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN || config.slackBotToken || '';
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY || config.anthropicApiKey || '';
const LOG_FILE = path.join(__dirname, 'processor.log');

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  process.stdout.write(line);
  fs.appendFileSync(LOG_FILE, line);
}

// ─────────────────────────────────────────────
// PAYLOAD HELPERS
// Fathom webhook payload is FLAT — no nested "meeting" object.
// ─────────────────────────────────────────────
function getTitle(payload) {
  return payload?.title || payload?.meeting_title || '';
}

function getTranscriptText(payload) {
  const t = payload?.transcript;
  if (!t) return '';
  if (typeof t === 'string') return t;
  if (Array.isArray(t)) {
    return t.map(seg => `${seg?.speaker?.display_name || 'Speaker'}: ${seg?.text || ''}`).join('\n');
  }
  return '';
}

function getSummary(payload) {
  return payload?.default_summary?.markdown_formatted
    || payload?.summary
    || '';
}

function getAttendees(payload) {
  return payload?.calendar_invitees || [];
}

function getMeetingDate(payload) {
  return payload?.scheduled_start_time || payload?.recording_start_time || new Date().toISOString();
}

// ─────────────────────────────────────────────
// CALL CLASSIFIER
// ─────────────────────────────────────────────
/**
 * Determines which use case(s) apply to this call.
 * Returns array of: 'weekly_checkin' | 'client_interview' | 'unknown'
 *
 * Classification: title-match only (external attendees ≠ client interview)
 */
function classifyCall(payload) {
  const title = getTitle(payload).toLowerCase();
  const attendees = getAttendees(payload);
  const attendeeDomains = attendees.map(a => (a.email || '').split('@')[1]).filter(Boolean);

  // Internal domain(s) — update in config.json as needed
  const internalDomains = config.internalDomains || ['rethoric.co', 'rethoric.com'];

  const INTERNAL_TITLE_PATTERNS = config.internalTitlePatterns || [
    'weekly sync', 'check-in', 'check in', 'team sync', 'standup',
    'monday sync', 'thursday sync', 'internal'
  ];

  const CLIENT_TITLE_PATTERNS = config.clientTitlePatterns || [
    'content interview', 'interview', 'monthly interview', 'recording'
  ];

  const SALES_TITLE_PATTERNS = config.salesTitlePatterns || [
    'rethoric intro call', 'intro call', 'discovery call'
  ];

  const matchesInternal = INTERNAL_TITLE_PATTERNS.some(p => title.includes(p));
  const matchesClient = CLIENT_TITLE_PATTERNS.some(p => title.includes(p));
  const matchesSales = SALES_TITLE_PATTERNS.some(p => title.includes(p));

  const useCases = [];

  if (matchesInternal) {
    useCases.push('weekly_checkin');
  } else if (matchesClient) {
    // Only classify as client_interview if the title explicitly matches —
    // external attendees alone are NOT sufficient (sales calls, intros, etc.)
    useCases.push('client_interview');
  } else if (matchesSales) {
    // Sales/discovery calls — log quietly, no alert. CRM integration TBD.
    useCases.push('sales_call');
  } else {
    // Unknown: flag to #tony-ops for manual classification
    useCases.push('unknown');
  }

  log(`Classified "${getTitle(payload)}" as: ${useCases.join(', ')}`);
  return useCases;
}

// ─────────────────────────────────────────────
// CLAUDE API HELPER
// ─────────────────────────────────────────────
function callClaude(systemPrompt, userContent, model = 'claude-sonnet-4-5') {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      model,
      max_tokens: 4096,
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
        try {
          const parsed = JSON.parse(data);
          resolve(parsed?.content?.[0]?.text || '');
        } catch (e) {
          reject(e);
        }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// ─────────────────────────────────────────────
// SLACK HELPER
// ─────────────────────────────────────────────
function postToSlack(channel, text, blocks) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ channel, text, ...(blocks ? { blocks } : {}) });
    const req = https.request({
      hostname: 'slack.com',
      path: '/api/chat.postMessage',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${SLACK_BOT_TOKEN}`,
        'Content-Length': Buffer.byteLength(body)
      }
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(JSON.parse(data)));
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// ─────────────────────────────────────────────
// USE CASE B: CLIENT FEEDBACK
// ─────────────────────────────────────────────
async function processClientFeedback(payload) {
  const channelId = config.clientFeedbackSlackChannel || 'PLACEHOLDER_CHANNEL';
  const transcript = getTranscriptText(payload);
  const summary = getSummary(payload);
  const meetingTitle = getTitle(payload) || 'Unknown';
  const attendees = getAttendees(payload).map(a => a.name || a.email).join(', ');

  const systemPrompt = `You are a feedback capture agent for Edu's client content interviews at Rethoric (a LinkedIn content ghostwriting agency for B2B tech founders).

Your job: detect any client feedback about the writing, content quality, voice representation, or Rethoric's services. Return ONLY structured JSON.

Rules:
- Capture implicit feedback too — hints, hesitations, or soft suggestions count
- Never editorialize beyond what was said
- If zero feedback found, return: {"has_feedback": false}
- If feedback found: {"has_feedback": true, "client_name": "...", "feedback_items": [{"summary": "...", "direct_quote": "...", "context": "..."}]}`;

  const userContent = `Meeting: ${meetingTitle}
Attendees: ${attendees}

TRANSCRIPT:
${transcript || 'No transcript available — check summary below.'}

SUMMARY:
${summary}`;

  log(`[USE CASE B] Analyzing transcript for client feedback...`);
  const result = await callClaude(systemPrompt, userContent, 'claude-sonnet-4-5');

  let parsed;
  try {
    parsed = JSON.parse(result.replace(/```json|```/g, '').trim());
  } catch (e) {
    log(`[USE CASE B] JSON parse error: ${e.message}\nRaw: ${result}`);
    return;
  }

  if (!parsed.has_feedback) {
    log(`[USE CASE B] No client feedback found — no Slack message sent.`);
    return;
  }

  // Format Slack message
  const clientName = parsed.client_name || 'Unknown client';
  const items = parsed.feedback_items || [];
  let text = `*Client Feedback Detected* — ${clientName} (${meetingTitle})\n\n`;
  items.forEach((item, i) => {
    text += `*Feedback ${items.length > 1 ? `${i + 1}` : ''}:* ${item.summary}\n`;
    if (item.direct_quote) text += `*Direct quote:* _"${item.direct_quote}"_\n`;
    if (item.context) text += `*Context:* ${item.context}\n`;
    text += '\n';
  });

  log(`[USE CASE B] Posting feedback to Slack channel ${channelId}`);
  await postToSlack(channelId, text);
}

// ─────────────────────────────────────────────
// USE CASE C: CONTENT IDEAS (accumulator)
// Saves ideas to a weekly file; Google Doc created on Monday via cron
// ─────────────────────────────────────────────
async function processContentIdeas(payload, callType) {
  const transcript = getTranscriptText(payload);
  const summary = getSummary(payload);
  const meetingTitle = getTitle(payload) || 'Unknown';
  const meetingDate = getMeetingDate(payload).split('T')[0];

  const isClientInterview = callType === 'client_interview';

  const systemPrompt = `You are a content intelligence agent for Edu Mussali, founder of Rethoric — a LinkedIn content ghostwriting agency for B2B tech founders.

## Who Edu Is (use this to personalize every post angle)
- 4x founder, 2 companies acquired
- Runs Rethoric: ghostwrites LinkedIn content for Series A+ B2B tech founders and C-level execs ($10M+ raised, NOT healthcare)
- Currently building AI operations into Rethoric — deploying an AI agent (Tony) as a kind of "AI COO" to handle ops, outreach, and workflow automation
- Not technical, but leading AI adoption from the top — hands-on, opinionated, learning in public
- Sells to and deeply understands his ICP (B2B founders) because he IS one
- Believes most founders underestimate how personal LinkedIn content has to be to convert
- Pipeline goal: 8–10 meetings/month → 30+/month

## Your Job
Mine this transcript and surface high-quality LinkedIn content IDEAS (not finished posts) that reflect Edu's voice as a thought leader.

Context: ${isClientInterview
    ? "This is a CLIENT CONTENT INTERVIEW. Edu is the interviewer; the client is a Series A+ B2B founder. Focus on insights Edu shares, his reactions, frameworks he uses, or what clients say that Edu could comment on ('I had a conversation with a founder who...')."
    : "This is an INTERNAL TEAM CHECK-IN. Look for strategic decisions, lessons learned, mistakes discussed, or business insights worth sharing publicly."}

Return ONLY valid JSON:
{
  "has_ideas": true/false,
  "reason_if_none": "...",
  "ideas": [
    {
      "idea": "One-line topic",
      "hook_angle": "Opening tension or insight that makes this worth reading",
      "edu_post_angle": "The specific post concept tailored to Edu. Reference his actual experience — his agency, his founder background, his AI ops work, his clients, his ICP. Write the angle as the story Edu would personally tell and the argument he'd make. Not generic thought leadership — Edu's version of it. 2–4 sentences.",
      "key_points": ["point 1", "point 2", "point 3"],
      "source": "Meeting name + approximate context",
      "content_bucket": "Growth | Authority | Conversion"
    }
  ]
}

## Content Bucket Definitions (critical — assign carefully)
- **Authority**: Thought leadership in Edu's specific niche (LinkedIn content strategy, ghostwriting, B2B founder content, agency ops). Builds trust with his ICP (Series A+ B2B founders). Works well as paid promotion targeted at ICP. If it would only resonate with someone who cares about LinkedIn content or founder content strategy, it's Authority.
- **Growth**: Highest viral potential. Relevant to the broader startup/founder ecosystem — fundraising, hiring, AI trends, YC, company building. Resonates with people beyond Edu's niche. Use when Edu wants to grow reach and followers.
- **Conversion**: Case studies, client results, direct CTA to book a call. Designed to turn readers into booked calls. Cap at 20% of total content. Use sparingly.

Rules:
- 0 ideas if nothing strong — never force it
- Every idea must trace directly to something said in the transcript
- edu_post_angle must be specific — if it could apply to any founder, rewrite it until it could only be Edu
- Content bucket assignment must reflect Edu's actual strategy — not just topic area
- Target audience: B2B founders, operators, VCs — high-signal only
- Max 5 ideas per single transcript (weekly aggregation caps at 10)`;

  const userContent = `Meeting: ${meetingTitle} (${meetingDate})

TRANSCRIPT:
${transcript || 'No transcript — using summary below.'}

SUMMARY:
${summary}`;

  log(`[USE CASE C] Mining transcript for content ideas...`);
  const result = await callClaude(systemPrompt, userContent, 'claude-sonnet-4-5');

  let parsed;
  try {
    parsed = JSON.parse(result.replace(/```json|```/g, '').trim());
  } catch (e) {
    log(`[USE CASE C] JSON parse error: ${e.message}`);
    return;
  }

  // Save to weekly ideas file (Monday cron will pick these up and create the Google Doc)
  const weekFile = path.join(__dirname, 'content-ideas', `week-${getISOWeek()}.json`);
  fs.mkdirSync(path.dirname(weekFile), { recursive: true });

  const existing = fs.existsSync(weekFile) ? JSON.parse(fs.readFileSync(weekFile)) : { ideas: [], sources: [] };
  existing.sources.push({ meeting: meetingTitle, date: meetingDate, callType });

  if (parsed.has_ideas && parsed.ideas?.length > 0) {
    existing.ideas.push(...parsed.ideas.map(i => ({ ...i, meeting: meetingTitle, date: meetingDate })));
    log(`[USE CASE C] Added ${parsed.ideas.length} ideas to ${weekFile}`);
  } else {
    log(`[USE CASE C] No strong ideas from this transcript: ${parsed.reason_if_none || 'none given'}`);
  }

  fs.writeFileSync(weekFile, JSON.stringify(existing, null, 2));
}

// ─────────────────────────────────────────────
// USE CASE A: WEEKLY CHECK-IN (stub — awaiting Asana keys)
// ─────────────────────────────────────────────
async function processWeeklyCheckin(payload) {
  log(`[USE CASE A] Weekly check-in received — STUB (awaiting Asana + Google keys)`);

  // Save payload for later processing when keys are available
  const stubDir = path.join(__dirname, 'pending-checkins');
  fs.mkdirSync(stubDir, { recursive: true });
  const file = path.join(stubDir, `${Date.now()}.json`);
  fs.writeFileSync(file, JSON.stringify(payload, null, 2));
  log(`[USE CASE A] Saved to ${file} for processing once Asana keys are configured`);
}

// ─────────────────────────────────────────────
// SALES CALL: log quietly, no alert (CRM integration TBD)
// ─────────────────────────────────────────────
async function processSalesCall(payload) {
  const title = getTitle(payload) || 'Untitled';
  const attendees = getAttendees(payload).map(a => a.email).join(', ');
  log(`[SALES] Discovery/intro call detected — logged, no alert. Title: "${title}" | Attendees: ${attendees}`);

  // Save for future CRM integration
  const salesDir = path.join(__dirname, 'sales-calls');
  fs.mkdirSync(salesDir, { recursive: true });
  const file = path.join(salesDir, `${Date.now()}.json`);
  fs.writeFileSync(file, JSON.stringify(payload, null, 2));
  log(`[SALES] Saved to ${file} for future CRM pipeline`);
}

// ─────────────────────────────────────────────
// UNKNOWN: flag to Slack
// ─────────────────────────────────────────────
async function flagUnknown(payload) {
  const channelId = config.opsSlackChannel || 'PLACEHOLDER_OPS_CHANNEL';
  const title = getTitle(payload) || 'Untitled';
  const attendees = getAttendees(payload).map(a => a.email).join(', ');
  const text = `⚠️ *Unclassified Fathom call received*\n*Title:* ${title}\n*Attendees:* ${attendees || 'unknown'}\nNeeds manual routing — reply with the correct use case.`;

  log(`[UNKNOWN] Could not classify call "${title}" — flagging to Slack`);
  if (SLACK_BOT_TOKEN && channelId !== 'PLACEHOLDER_OPS_CHANNEL') {
    await postToSlack(channelId, text);
  }
}

// ─────────────────────────────────────────────
// CREDENTIAL REDACTION
// Applied to the full payload before archiving to disk.
// Matches common credential patterns in verbatim transcript text.
// ─────────────────────────────────────────────

const REDACTION_PATTERNS = [
  // AWS Access Key IDs
  { pattern: /\bAKIA[0-9A-Z]{16}\b/g,                                   label: '[REDACTED:AWS_KEY_ID]' },
  // AWS Secret Access Keys (40-char base64-ish)
  { pattern: /\b[0-9a-zA-Z/+]{40}\b/g,                                  label: '[REDACTED:AWS_SECRET]' },
  // Spoken password disclosure: "password is <word>", "the password is <word>", etc.
  { pattern: /\b(password\s+is\s+)\S+/gi,                               label: '$1[REDACTED]' },
  { pattern: /\b(the\s+password\s+is\s+)\S+/gi,                        label: '$1[REDACTED]' },
  { pattern: /\b(my\s+password\s+is\s+)\S+/gi,                         label: '$1[REDACTED]' },
  { pattern: /\b(our\s+password\s+is\s+)\S+/gi,                        label: '$1[REDACTED]' },
  { pattern: /\b(it'?s\s+)([\w!@#$%^&*()+=\-_.]{8,})\b/gi,            label: (m, p1) => p1 + '[REDACTED]' },
  // API key/token disclosure patterns
  { pattern: /\b(api\s+key\s+is\s+)\S+/gi,                             label: '$1[REDACTED]' },
  { pattern: /\b(token\s+is\s+)\S+/gi,                                  label: '$1[REDACTED]' },
  { pattern: /\b(secret\s+is\s+)\S+/gi,                                 label: '$1[REDACTED]' },
  // Credit card numbers (13–19 digits, optionally space/dash separated)
  { pattern: /\b(\d[\d \-]{11,17}\d)\b/g,                              label: '[REDACTED:CC]' },
  // US SSN
  { pattern: /\b\d{3}[-\s]\d{2}[-\s]\d{4}\b/g,                        label: '[REDACTED:SSN]' },
  // Generic long alphanumeric tokens (≥32 chars, likely keys/hashes)
  { pattern: /\b[a-zA-Z0-9_\-]{32,}\b/g,                               label: '[REDACTED:TOKEN]' },
];

function redactString(text) {
  if (!text || typeof text !== 'string') return text;
  let out = text;
  for (const { pattern, label } of REDACTION_PATTERNS) {
    out = out.replace(pattern, label);
  }
  return out;
}

function redactPayload(payload) {
  if (!payload || typeof payload !== 'object') return payload;
  const clone = JSON.parse(JSON.stringify(payload));

  // Redact top-level string fields that may contain spoken text
  const TEXT_FIELDS = ['transcript', 'summary', 'notes', 'description'];
  for (const field of TEXT_FIELDS) {
    if (typeof clone[field] === 'string') {
      clone[field] = redactString(clone[field]);
    }
  }

  // Redact transcript array (Fathom segment format)
  if (Array.isArray(clone.transcript)) {
    clone.transcript = clone.transcript.map(seg => ({
      ...seg,
      text: redactString(seg.text),
    }));
  }

  // Redact default_summary sub-fields
  if (clone.default_summary && typeof clone.default_summary === 'object') {
    for (const key of Object.keys(clone.default_summary)) {
      if (typeof clone.default_summary[key] === 'string') {
        clone.default_summary[key] = redactString(clone.default_summary[key]);
      }
    }
  }

  clone._redacted = true;
  clone._redacted_at = new Date().toISOString();
  return clone;
}

// ─────────────────────────────────────────────
// ISO WEEK HELPER
// ─────────────────────────────────────────────
function getISOWeek(date = new Date()) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`;
}

// ─────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────
async function main() {
  const payload = JSON.parse(fs.readFileSync(payloadFile));
  const useCases = classifyCall(payload);

  for (const useCase of useCases) {
    try {
      if (useCase === 'weekly_checkin') {
        await processWeeklyCheckin(payload);
        await processContentIdeas(payload, 'weekly_checkin');
      } else if (useCase === 'client_interview') {
        await processClientFeedback(payload);
        await processContentIdeas(payload, 'client_interview');
      } else if (useCase === 'sales_call') {
        await processSalesCall(payload);
      } else {
        await flagUnknown(payload);
      }
    } catch (err) {
      log(`Error processing use case ${useCase}: ${err.message}\n${err.stack}`);
    }
  }

  // Redact credentials/PII from payload before archiving
  const redactedPayload = redactPayload(payload);
  log(`Redaction applied (${REDACTION_PATTERNS.length} pattern checks)`);

  // Archive processed file (write redacted version, then remove queue file)
  const archiveDir = path.join(path.dirname(payloadFile), '..', 'archive');
  fs.mkdirSync(archiveDir, { recursive: true });
  const archivedFile = path.join(archiveDir, path.basename(payloadFile));
  fs.writeFileSync(archivedFile, JSON.stringify(redactedPayload, null, 2), { mode: 0o600 });
  fs.unlinkSync(payloadFile);
  log(`Archived (redacted): ${archivedFile}`);

  // Trigger KB ingestion (fire-and-forget — non-blocking)
  const kbIngest = path.join(__dirname, 'kb_ingest.py');
  const ingestProc = spawn('python3', [kbIngest, archivedFile], {
    detached: true,
    stdio: 'ignore',
    env: { ...process.env }
  });
  ingestProc.unref();
  log(`KB ingestion triggered for: ${path.basename(archivedFile)}`);
}

main().catch(err => {
  log(`FATAL: ${err.message}\n${err.stack}`);
  process.exit(1);
});
