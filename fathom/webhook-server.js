#!/usr/bin/env node
/**
 * Fathom Webhook Server
 * Receives call transcripts from Fathom and routes them to the appropriate processor.
 * Runs on port 8001; Caddy proxies /fathom-webhook → here.
 */

const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');

const PORT = 8001;
const WEBHOOK_SECRET = process.env.FATHOM_WEBHOOK_SECRET || '';
if (!WEBHOOK_SECRET) {
  process.stderr.write('[FATAL] FATHOM_WEBHOOK_SECRET not set — refusing to start\n');
  process.exit(1);
}
const QUEUE_DIR = path.join(__dirname, 'queue');
const LOG_FILE = path.join(__dirname, 'webhook.log');

// Ensure queue directory exists
if (!fs.existsSync(QUEUE_DIR)) fs.mkdirSync(QUEUE_DIR, { recursive: true });

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  process.stdout.write(line);
  fs.appendFileSync(LOG_FILE, line);
}

/**
 * Verify Fathom webhook signature.
 * Fathom sends: fathom-signature: t=<timestamp>,v1=<hmac>
 * HMAC is computed over: `${timestamp}.${rawBody}`
 */
function verifySignature(rawBody, signatureHeader) {
  // Always require the secret — never accept unsigned requests
  if (!WEBHOOK_SECRET) return false;
  if (!signatureHeader) return false;

  const parts = Object.fromEntries(
    signatureHeader.split(',').map(p => p.split('='))
  );
  const timestamp = parts['t'];
  const v1 = parts['v1'];
  if (!timestamp || !v1) return false;

  // Replay attack protection: reject requests older than 5 minutes
  const age = Math.abs(Date.now() / 1000 - Number(timestamp));
  if (isNaN(age) || age > 300) {
    log(`Rejected: webhook timestamp too old (age=${Math.round(age)}s)`);
    return false;
  }

  const expected = crypto
    .createHmac('sha256', WEBHOOK_SECRET)
    .update(`${timestamp}.${rawBody}`)
    .digest('hex');

  return crypto.timingSafeEqual(Buffer.from(v1), Buffer.from(expected));
}

/**
 * Save payload to queue and trigger processor.
 */
function enqueue(payload) {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const file = path.join(QUEUE_DIR, `${id}.json`);
  fs.writeFileSync(file, JSON.stringify(payload, null, 2));
  log(`Queued: ${file}`);

  // Fire-and-forget: trigger processor
  const processor = path.join(__dirname, 'processor.js');
  execFile('node', [processor, file], { env: process.env }, (err, stdout, stderr) => {
    if (err) log(`Processor error for ${id}: ${err.message}\n${stderr}`);
    else log(`Processor done for ${id}: ${stdout.trim()}`);
  });
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost`);

  // Health check
  if (req.method === 'GET' && url.pathname === '/fathom-webhook') {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('Fathom webhook server OK');
    return;
  }

  // Webhook endpoint
  if (req.method === 'POST' && url.pathname === '/fathom-webhook') {
    let rawBody = '';
    req.on('data', chunk => { rawBody += chunk; });
    req.on('end', () => {
      const sigHeader = req.headers['fathom-signature'] || '';

      if (!verifySignature(rawBody, sigHeader)) {
        log(`Signature verification failed`);
        res.writeHead(401, { 'Content-Type': 'text/plain' });
        res.end('Unauthorized');
        return;
      }

      let payload;
      try {
        payload = JSON.parse(rawBody);
      } catch (e) {
        log(`JSON parse error: ${e.message}`);
        res.writeHead(400, { 'Content-Type': 'text/plain' });
        res.end('Bad Request');
        return;
      }

      log(`Received webhook: meeting="${payload?.title || payload?.meeting_title}" id=${payload?.recording_id}`);

      // Respond immediately (Fathom expects quick 200)
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ received: true }));

      // Enqueue for async processing
      enqueue(payload);
    });
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, '127.0.0.1', () => {
  log(`Fathom webhook server listening on port ${PORT}`);
});
