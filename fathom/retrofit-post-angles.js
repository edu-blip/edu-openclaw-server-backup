#!/usr/bin/env node
/**
 * One-off: add edu_post_angle to existing week-W09 ideas
 * Usage: node fathom/retrofit-post-angles.js
 */

const fs = require('fs');
const https = require('https');
const path = require('path');

const WEEK_FILE = path.join(__dirname, 'content-ideas', 'week-2026-W09.json');

function callClaude(systemPrompt, userContent) {
  return new Promise((resolve, reject) => {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    const body = JSON.stringify({
      model: 'claude-sonnet-4-5',
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
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'Content-Length': Buffer.byteLength(body)
      }
    }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(d);
          resolve(parsed.content?.[0]?.text || '');
        } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

async function main() {
  const data = JSON.parse(fs.readFileSync(WEEK_FILE));
  const ideas = data.ideas;

  const system = `You are generating personalized LinkedIn post angles for Edu Mussali.

## Who Edu Is
- 4x founder, 2 companies acquired
- Runs Rethoric: ghostwrites LinkedIn content for Series A+ B2B tech founders (raised $10M+, not healthcare)
- Currently building AI operations into Rethoric — deploying an AI agent (Tony) as a kind of "AI COO"
- Not technical, but leading AI adoption from the top — hands-on, learning in public
- Sells to and deeply understands his ICP because he IS a founder
- Believes LinkedIn content must be personal to convert
- Pipeline goal: 8–10 meetings/month → 30+/month

For each idea, write a 2–4 sentence "edu_post_angle": the specific post concept tailored to Edu.
Reference his actual experience — running Rethoric, being a repeat founder, building AI into his agency, his clients (B2B founders), his content strategy work.
Make it so specific it could ONLY be Edu posting it. Not generic founder content.

Return ONLY a JSON array (one object per idea):
[
  { "index": 0, "edu_post_angle": "..." },
  { "index": 1, "edu_post_angle": "..." },
  ...
]`;

  const userContent = `Here are the ${ideas.length} content ideas to add angles for:\n\n` +
    ideas.map((idea, i) => `${i}. Idea: ${idea.idea}\n   Hook: ${idea.hook_angle}`).join('\n\n');

  console.log('Calling Claude to generate personalized angles...');
  const result = await callClaude(system, userContent);

  let angles;
  try {
    angles = JSON.parse(result.replace(/```json|```/g, '').trim());
  } catch (e) {
    console.error('Failed to parse Claude response:', result);
    process.exit(1);
  }

  // Apply angles to ideas
  angles.forEach(({ index, edu_post_angle }) => {
    if (ideas[index]) {
      ideas[index].edu_post_angle = edu_post_angle;
      console.log(`✓ Idea ${index + 1}: angle added`);
    }
  });

  fs.writeFileSync(WEEK_FILE, JSON.stringify(data, null, 2));
  console.log(`\nUpdated ${WEEK_FILE}`);
}

main().catch(err => { console.error('FATAL:', err.message); process.exit(1); });
