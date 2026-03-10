#!/usr/bin/env node
/**
 * content-radar.js — Content Intelligence System
 *
 * Monitors X accounts, Reddit, and news every 4 hours.
 * Scores candidates with Gemini Flash against Edu's content pillars.
 * Posts top alerts (score ≥ 7) to #alec-content.
 *
 * Config:   scripts/content-radar-config.json
 * State:    logs/content-radar-state.json
 * Log:      /home/openclaw/logs/content-radar.log
 *
 * Usage:
 *   node scripts/content-radar.js          # normal run
 *   node scripts/content-radar.js --dry    # score without posting
 */

'use strict';

const fs      = require('fs');
const path    = require('path');
const https   = require('https');
const { URL } = require('url');

// ─── Paths & Constants ──────────────────────────────────────────────────────
const WORKSPACE    = '/home/openclaw/.openclaw/workspace';
const ENV_PATH     = '/home/openclaw/.openclaw/.env';
const CONFIG_FILE  = path.join(WORKSPACE, 'scripts/content-radar-config.json');
const STATE_FILE   = path.join(WORKSPACE, 'logs/content-radar-state.json');
const LOG_FILE     = '/home/openclaw/logs/content-radar.log';

const MAX_ALERTS_PER_RUN  = 3;    // Max posts to #alec-content per run
const MIN_SCORE           = 7;    // Minimum Gemini score to alert
const X_BATCH_SIZE        = 12;   // X accounts per xAI API call
const REDDIT_MIN_SCORE    = 50;   // Minimum Reddit upvotes
const REDDIT_MAX_AGE_H    = 12;   // Reddit posts older than this are skipped
const STATE_TTL_DAYS      = 7;    // Days before dedup entries expire
const CHANNEL_ID          = 'C0AKHKDJ2MC';
const REDDIT_UA           = 'ContentRadar/1.0 (OpenClaw; github.com/edu-blip)';

const DRY_RUN = process.argv.includes('--dry');

// ─── Env Loader ────────────────────────────────────────────────────────────
function loadEnv() {
  const vars = {};
  try {
    const lines = fs.readFileSync(ENV_PATH, 'utf8').split('\n');
    for (const line of lines) {
      const m = line.match(/^([A-Z0-9_]+)=(.+)$/);
      if (m) vars[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
    }
  } catch (e) { log(`WARN loadEnv: ${e.message}`); }
  return vars;
}

// ─── Logger ─────────────────────────────────────────────────────────────────
function log(msg) {
  const ts   = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
  const line = `[${ts}] ${msg}`;
  process.stderr.write(line + '\n');
  try {
    fs.mkdirSync(path.dirname(LOG_FILE), { recursive: true });
    fs.appendFileSync(LOG_FILE, line + '\n');
  } catch (_) {}
}

// ─── State ─────────────────────────────────────────────────────────────────
function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); }
  catch { return { seen: {}, last_run: null }; }
}

function saveState(state) {
  const cutoff = Date.now() - STATE_TTL_DAYS * 24 * 60 * 60 * 1000;
  for (const k of Object.keys(state.seen)) {
    if (state.seen[k] < cutoff) delete state.seen[k];
  }
  state.last_run = new Date().toISOString();
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

// ─── HTTP Helpers ──────────────────────────────────────────────────────────
function httpsPost(options, body) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch { resolve({ _raw: data }); }
      });
    });
    req.on('error', reject);
    req.setTimeout(30000, () => { req.destroy(); reject(new Error('timeout')); });
    if (body) req.write(body);
    req.end();
  });
}

function httpsGetJson(urlStr, headers = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr);
    const opts = {
      hostname: u.hostname,
      path:     u.pathname + u.search,
      headers:  { 'User-Agent': REDDIT_UA, ...headers }
    };
    const req = https.get(opts, res => {
      // Handle redirects
      if ([301, 302, 303, 307].includes(res.statusCode) && res.headers.location) {
        httpsGetJson(res.headers.location, headers).then(resolve).catch(reject);
        return;
      }
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch { resolve({ _raw: data }); }
      });
    });
    req.on('error', reject);
    req.setTimeout(20000, () => { req.destroy(); reject(new Error('timeout')); });
  });
}

// ─── Cost Logger ───────────────────────────────────────────────────────────
let _logCost;
try { _logCost = require('../fathom/cost-logger').logCost; }
catch { _logCost = () => {}; }

// ─── Source 1: X Accounts via xAI ─────────────────────────────────────────
async function fetchXPosts(env, accounts) {
  const results = [];
  const now     = new Date();
  const from4h  = new Date(now - 4 * 60 * 60 * 1000);

  for (let i = 0; i < accounts.length; i += X_BATCH_SIZE) {
    const batch = accounts.slice(i, i + X_BATCH_SIZE);
    const names = batch.join(', ');

    const prompt = `Search X for recent high-engagement posts from these accounts in the last 4–12 hours: ${names}.

Return ONLY a JSON array of up to 6 notable posts (no prose, no markdown outside JSON).
Each item: { "author": "@handle", "text": "key insight or quote (max 200 chars)", "url": "tweet URL or null", "engagement": "high|medium", "topic": "2-4 word topic" }

Focus on: announcements, strong opinions, viral moments, contrarian takes. Skip replies and reposts.`;

    try {
      const body = JSON.stringify({
        model: 'grok-4-1-fast-non-reasoning',
        input: [
          { role: 'system', content: 'You are a research assistant. Return ONLY valid JSON arrays as instructed. No markdown fences, no prose.' },
          { role: 'user',   content: prompt }
        ],
        tools: [{
          type: 'x_search',
          filters: {
            from_date: from4h.toISOString().replace(/\.\d{3}Z$/, 'Z'),
            to_date:   now.toISOString().replace(/\.\d{3}Z$/, 'Z')
          }
        }]
      });

      const resp = await httpsPost({
        hostname: 'api.x.ai',
        path:     '/v1/responses',
        method:   'POST',
        headers: {
          'Content-Type':   'application/json',
          'Authorization':  `Bearer ${env.XAI_API_KEY}`,
          'Content-Length': Buffer.byteLength(body)
        }
      }, body);

      const usage = resp.usage || {};
      _logCost('grok-4-1-fast-non-reasoning', usage.input_tokens || 0, usage.output_tokens || 0, 'content-radar.js:x');

      // Extract text from Grok response
      let text = '';
      for (const item of (resp.output || [])) {
        if (item.type === 'message') {
          for (const c of (item.content || [])) {
            if (c.type === 'output_text') { text = c.text; break; }
          }
        }
      }

      // Parse JSON array from response
      const jsonMatch = text.match(/\[[\s\S]*?\]/);
      if (jsonMatch) {
        const posts = JSON.parse(jsonMatch[0]);
        results.push(...posts.map(p => ({ ...p, source: 'x' })));
        log(`  X batch ${Math.floor(i / X_BATCH_SIZE) + 1}: got ${posts.length} posts`);
      } else {
        log(`  WARN X batch ${Math.floor(i / X_BATCH_SIZE) + 1}: no JSON in response`);
      }
    } catch (e) {
      log(`  WARN X batch ${Math.floor(i / X_BATCH_SIZE) + 1} failed: ${e.message}`);
    }

    // Throttle between batches
    if (i + X_BATCH_SIZE < accounts.length) {
      await new Promise(r => setTimeout(r, 3000));
    }
  }

  log(`X: collected ${results.length} candidate posts from ${accounts.length} accounts`);
  return results;
}

// ─── Source 2: Reddit ──────────────────────────────────────────────────────
async function fetchRedditPosts(subreddits) {
  const results = [];
  const nowSec  = Date.now() / 1000;

  for (const sub of subreddits) {
    try {
      const data  = await httpsGetJson(`https://www.reddit.com/r/${sub}/hot.json?limit=15&raw_json=1`);
      const posts = data?.data?.children || [];

      let count = 0;
      for (const post of posts) {
        const d       = post.data;
        const ageHrs  = (nowSec - d.created_utc) / 3600;

        if (ageHrs > REDDIT_MAX_AGE_H) continue;
        if (d.score < REDDIT_MIN_SCORE) continue;
        if (d.is_self && !d.selftext) continue; // empty self-posts

        results.push({
          source:     'reddit',
          author:     `r/${sub}`,
          text:       d.title + (d.selftext ? ` — ${d.selftext.slice(0, 100)}` : ''),
          url:        `https://www.reddit.com${d.permalink}`,
          engagement: d.score > 500 ? 'high' : 'medium',
          topic:      sub,
          score_raw:  d.score
        });
        if (++count >= 5) break;
      }
    } catch (e) {
      log(`  WARN Reddit r/${sub}: ${e.message}`);
    }
  }

  log(`Reddit: collected ${results.length} posts`);
  return results;
}

// ─── Source 3: Brave Web Search ────────────────────────────────────────────
async function fetchBravePosts(env, queries) {
  const results = [];
  // Rotate query by current hour so each run uses a different query
  const query = queries[new Date().getHours() % queries.length];

  try {
    const url = `https://api.search.brave.com/res/v1/web/search?q=${encodeURIComponent(query)}&count=5&freshness=pd&text_decorations=false&result_filter=news`;
    const data = await httpsGetJson(url, {
      'Accept':               'application/json',
      'Accept-Encoding':      'identity',
      'X-Subscription-Token': env.BRAVE_API_KEY
    });

    const items = data?.news?.results || data?.results || [];
    for (const item of items.slice(0, 5)) {
      if (!item.title) continue;
      results.push({
        source:     'brave',
        author:     item.meta_url?.hostname || 'news',
        text:       item.title + (item.description ? ` — ${item.description.slice(0, 120)}` : ''),
        url:        item.url,
        engagement: 'medium',
        topic:      'news'
      });
    }
  } catch (e) {
    log(`  WARN Brave search: ${e.message}`);
  }

  log(`Brave: collected ${results.length} items (query: "${query}")`);
  return results;
}

// ─── Scoring via Gemini Flash ──────────────────────────────────────────────
async function scoreCandidates(env, candidates, pillars) {
  if (candidates.length === 0) return [];

  const list = candidates.map((c, i) =>
    `${i + 1}. [${c.source.toUpperCase()}] ${c.author}: "${c.text.slice(0, 200)}" | ${c.url || 'no url'}`
  ).join('\n');

  const prompt = `You are scoring content items for a B2B LinkedIn content strategy targeting Series A+ startup founders and tech execs.

Score each item 1–10 on relevance to these pillars:
${pillars.map(p => `• ${p}`).join('\n')}

Scoring guide:
8–10 = Viral/trending NOW, creates immediate posting opportunity, strong founder angle
6–7  = Relevant but evergreen or not urgent  
1–5  = Low relevance, B2C, healthcare, or not founder-relevant

Deduct for: generic corporate news, non-founder content, healthcare, celebrity, B2C.
Boost for: contrarian take + specific numbers, AI + business impact, fundraising news, founder lessons.

For each item also write a one-line draft hook (Nicolas Cole style: bold short claim, contradiction, or specific number).

Return ONLY valid JSON array, no prose:
[{"index":1,"score":8,"reason":"one sentence","hook":"the hook line"},...]

Items:
${list}`;

  const geminiModel = 'gemini-3-flash-preview';

  try {
    const body = JSON.stringify({
      contents: [{ role: 'user', parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.3, maxOutputTokens: 2048 }
    });

    const resp = await httpsPost({
      hostname: 'generativelanguage.googleapis.com',
      path:     `/v1beta/models/${geminiModel}:generateContent?key=${env.GEMINI_API_KEY}`,
      method:   'POST',
      headers: {
        'Content-Type':   'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    }, body);

    const usage = resp.usageMetadata || {};
    _logCost(geminiModel, usage.promptTokenCount || 0, usage.candidatesTokenCount || 0, 'content-radar.js:score');

    const text = resp?.candidates?.[0]?.content?.parts?.[0]?.text || '';

    // Strip markdown fences if Gemini wrapped JSON anyway
    const clean = text.replace(/```json?\n?/g, '').replace(/```/g, '').trim();
    const jsonMatch = clean.match(/\[[\s\S]*\]/);

    if (!jsonMatch) {
      log(`WARN: Gemini returned no JSON array. Response: ${text.slice(0, 200)}`);
      return [];
    }

    const scores = JSON.parse(jsonMatch[0]);

    const scored = scores
      .filter(s => typeof s.score === 'number' && s.score >= MIN_SCORE && s.index >= 1 && s.index <= candidates.length)
      .map(s => ({
        ...candidates[s.index - 1],
        ai_score:  s.score,
        ai_reason: s.reason,
        ai_hook:   s.hook
      }))
      .sort((a, b) => b.ai_score - a.ai_score);

    log(`Gemini: ${scored.length}/${candidates.length} candidates scored ≥ ${MIN_SCORE}`);
    return scored;

  } catch (e) {
    log(`ERROR Gemini scoring: ${e.message}`);
    return [];
  }
}

// ─── Slack Alert ───────────────────────────────────────────────────────────
function sanitize(text) {
  return (text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function postAlert(env, item) {
  const sourceLabel = { x: 'X/Twitter', reddit: 'Reddit', brave: 'News' }[item.source] || item.source;
  const authorLabel = item.author || '';
  const snippet     = sanitize(item.text.slice(0, 250) + (item.text.length > 250 ? '...' : ''));
  const hookLine    = sanitize(item.ai_hook || '');
  const reasonLine  = sanitize(item.ai_reason || '');

  const linkText = item.url ? `<${item.url}|View original>` : '';

  const text = [
    `🔥 *Content Radar* [${sourceLabel}] · Score: ${item.ai_score}/10`,
    ``,
    `*${snippet}*`,
    authorLabel ? `_${sanitize(authorLabel)}_` : '',
    linkText,
    ``,
    `*Why this is relevant:* ${reasonLine}`,
    ``,
    `*Draft hook for your take:*`,
    `_${hookLine}_`,
    ``,
    `Reply *"develop this"* to get the full post drafted.`
  ].filter(l => l !== null && l !== undefined).join('\n');

  if (DRY_RUN) {
    console.log('\n──────────────────────────────────────');
    console.log('[DRY RUN] Would post to Slack:');
    console.log(text);
    console.log('──────────────────────────────────────\n');
    return { ok: true, dry_run: true };
  }

  const body    = JSON.stringify({ channel: CHANNEL_ID, text });
  const resp    = await httpsPost({
    hostname: 'slack.com',
    path:     '/api/chat.postMessage',
    method:   'POST',
    headers: {
      'Content-Type':   'application/json',
      'Authorization':  `Bearer ${env.SLACK_BOT_TOKEN}`,
      'Content-Length': Buffer.byteLength(body)
    }
  }, body);

  if (!resp.ok) log(`WARN Slack post failed: ${JSON.stringify(resp)}`);
  return resp;
}

// ─── Main ──────────────────────────────────────────────────────────────────
async function main() {
  log(`=== Content Radar run started (${DRY_RUN ? 'DRY RUN' : 'LIVE'}) ===`);

  const env    = loadEnv();
  const config = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
  const state  = loadState();

  // Flatten all X account handles from all categories
  const allAccounts = Object.values(config.x_accounts)
    .flat()
    .map(a => a.handle)
    .filter(Boolean);

  log(`Monitoring ${allAccounts.length} X accounts, ${config.reddit_subreddits.length} subreddits`);

  // Collect from all 3 sources (Reddit + Brave in parallel, X sequential/batched)
  let xPosts = [], redditPosts = [], bravePosts = [];

  const [rPosts, bPosts] = await Promise.all([
    fetchRedditPosts(config.reddit_subreddits),
    fetchBravePosts(env, config.brave_search_queries)
  ]);
  redditPosts = rPosts;
  bravePosts  = bPosts;

  // X runs sequentially to respect API rate limits
  xPosts = await fetchXPosts(env, allAccounts);

  const allCandidates = [...xPosts, ...redditPosts, ...bravePosts];
  log(`Total candidates: ${allCandidates.length}`);

  // Deduplicate against seen state
  const fresh = allCandidates.filter(c => {
    const key = c.url || `${c.source}:${c.text.slice(0, 60)}`;
    return !state.seen[key];
  });
  log(`Fresh (not seen before): ${fresh.length}`);

  if (fresh.length === 0) {
    log('No new candidates — nothing to score');
    saveState(state);
    log('=== Run complete: 0 alerts ===');
    return;
  }

  // Score with Gemini Flash
  const scored = await scoreCandidates(env, fresh, config.scoring.pillars);

  // Post top N
  const toPost = scored.slice(0, MAX_ALERTS_PER_RUN);

  if (toPost.length === 0) {
    log(`No candidates scored ≥ ${MIN_SCORE} — no alerts sent`);
  }

  for (const item of toPost) {
    const key = item.url || `${item.source}:${item.text.slice(0, 60)}`;
    await postAlert(env, item);
    state.seen[key] = Date.now();
    log(`Posted: [${item.source}] score=${item.ai_score} — "${item.text.slice(0, 60)}..."`);
  }

  // Mark all fresh items as seen (even non-posted ones, to avoid re-scoring)
  for (const c of fresh) {
    const key = c.url || `${c.source}:${c.text.slice(0, 60)}`;
    if (!state.seen[key]) state.seen[key] = Date.now();
  }

  saveState(state);
  log(`=== Run complete: ${toPost.length} alert(s) posted ===`);
}

main().catch(e => {
  log(`FATAL: ${e.message}\n${e.stack}`);
  process.exit(1);
});
