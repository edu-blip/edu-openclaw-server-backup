'use strict';
/**
 * models.js — Shared model name loader for Fathom scripts.
 * Reads from workspace/config/models.json so changing a model name
 * in that one file propagates everywhere automatically.
 */

const fs   = require('fs');
const path = require('path');

const MODELS_PATH = path.join(__dirname, '..', 'config', 'models.json');

const DEFAULTS = {
  claude_default: 'claude-sonnet-4-6',
  claude_opus:    'claude-opus-4-6',
  claude_haiku:   'claude-haiku-4-6',
  gemini_default: 'gemini-3-flash-preview',
  grok_default:   'grok-4-1-fast-non-reasoning',
};

try {
  const loaded = JSON.parse(fs.readFileSync(MODELS_PATH, 'utf8'));
  module.exports = { ...DEFAULTS, ...loaded };
} catch (e) {
  process.stderr.write(`[models] Could not load config/models.json, using defaults: ${e.message}\n`);
  module.exports = { ...DEFAULTS };
}
