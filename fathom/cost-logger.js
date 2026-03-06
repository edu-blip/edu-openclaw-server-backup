/**
 * cost-logger.js - Shared cost logging module for direct API calls.
 *
 * Usage:
 *   const { logCost } = require('./cost-logger');
 *   logCost('claude-sonnet-4-6', 1234, 56, 'fathom/processor.js');
 */

'use strict';

const fs = require('fs');
const path = require('path');

const LOG_FILE = '/home/openclaw/logs/direct-api-costs.jsonl';

/**
 * Append a cost record to the shared direct-API cost log.
 * Silent on any error — never crashes the calling script.
 *
 * @param {string} model        - Model name (e.g. "claude-sonnet-4-6-20251115")
 * @param {number} inputTokens  - Input/prompt token count
 * @param {number} outputTokens - Output/completion token count
 * @param {string} source       - Calling script name (e.g. "fathom/processor.js")
 */
function logCost(model, inputTokens, outputTokens, source) {
  try {
    const ts = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    const record = {
      ts,
      model: String(model || ''),
      input_tokens: inputTokens || 0,
      output_tokens: outputTokens || 0,
      source: String(source || ''),
    };

    // Ensure log directory exists
    const dir = path.dirname(LOG_FILE);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // appendFileSync is atomic on Linux for small writes
    fs.appendFileSync(LOG_FILE, JSON.stringify(record) + '\n');
  } catch (_) {
    // Silent failure — never crash the calling script
  }
}

module.exports = { logCost };
