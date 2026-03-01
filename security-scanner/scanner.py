#!/usr/bin/env python3
"""
Tony's Automated Security Review System v1.1
Spec: security-review-spec-v1.1.docx
Targets: /root/.openclaw/workspace + /usr/lib/node_modules/openclaw
Schedule: Nightly diff 3:30 AM Mon-Sat (Gemini 3 Flash) | Weekly full 3:30 AM Sunday (Sonnet 4.6)
On-demand: --deep-dive FIND-001
"""

import os, sys, json, subprocess, datetime, re, time, argparse
import urllib.request, urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
SCAN_HISTORY_FILE = SCRIPT_DIR / "scan_history.json"
SUPPRESSIONS_FILE = SCRIPT_DIR / ".security-suppressions.json"

# ─── DEFAULT CONFIG ────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "scan_targets": [
        "/root/.openclaw/workspace",
        "/usr/lib/node_modules/openclaw"
    ],
    "models": {
        "nightly_diff": "gemini-2.0-flash-exp",
        "weekly_full": "claude-sonnet-4-6",
        "deep_dive": "claude-opus-4-6"
    },
    "slack_channel_alerts": "C0AHBCJQJKS",
    "monthly_budget_alert": 20.0,
    "max_tokens_per_chunk": 150000
}

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            merged = dict(DEFAULT_CONFIG)
            merged.update(cfg)
            if "models" in cfg:
                merged["models"] = {**DEFAULT_CONFIG["models"], **cfg["models"]}
            return merged
        except Exception as e:
            print(f"[WARN] config.json parse error: {e}. Using defaults.")
    return dict(DEFAULT_CONFIG)

# ─── API KEYS ─────────────────────────────────────────────────────────────────

def load_env() -> dict:
    env_file = Path("/root/.openclaw/.env")
    env = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

_ENV = load_env()
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY') or _ENV.get('ANTHROPIC_API_KEY', '')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') or _ENV.get('GEMINI_API_KEY', '')
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN') or _ENV.get('SLACK_BOT_TOKEN', '')

# ─── FILE COLLECTION ──────────────────────────────────────────────────────────

ALWAYS_EXCLUDE_DIRS = {
    'node_modules', '.git', 'dist', 'build', '.next', 'coverage',
    '__pycache__', '.pytest_cache', '.mypy_cache', 'tmp', '.tmp',
    'venv', '.venv', '.env', 'env'
}
EXCLUDE_EXTENSIONS = {
    '.min.js', '.min.css', '.map', '.lock', '.lockb',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp',
    '.woff', '.woff2', '.ttf', '.eot', '.pdf', '.zip', '.tar', '.gz',
    '.pyc', '.pyo', '.class', '.o', '.so', '.dylib', '.exe', '.bin',
    '.xlsx', '.xls', '.docx', '.doc', '.db', '.sqlite', '.sqlite3'
}
EXCLUDE_FILES = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock',
    'Pipfile.lock', 'composer.lock', 'Gemfile.lock', 'CHANGELOG.md'
}
HIGH_PRIORITY_NAMES = {
    '.env', '.env.local', '.env.production', '.env.development',
    'Dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
    'package.json', '.htaccess', 'nginx.conf', 'sshd_config'
}
HIGH_PRIORITY_DIRS = {'auth', 'middleware', 'api', 'routes', 'migrations', 'security', 'scripts'}
HIGH_PRIORITY_EXTENSIONS = {'.env', '.key', '.pem', '.cert', '.sql', '.yml', '.yaml'}
MAX_FILE_SIZE_BYTES = 300_000  # Skip files > 300KB

def should_exclude(path: Path) -> bool:
    for part in path.parts:
        if part in ALWAYS_EXCLUDE_DIRS:
            return True
    if path.suffix.lower() in EXCLUDE_EXTENSIONS:
        return True
    if path.name in EXCLUDE_FILES:
        return True
    try:
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return True
    except:
        return True
    return False

def get_priority(path: Path) -> str:
    if path.name in HIGH_PRIORITY_NAMES:
        return 'HIGH'
    if path.suffix in HIGH_PRIORITY_EXTENSIONS:
        return 'HIGH'
    if any(d in path.parts for d in HIGH_PRIORITY_DIRS):
        return 'HIGH'
    return 'NORMAL'

def read_file_safe(path: Path) -> str | None:
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
        sample = content[:1000]
        non_print = sum(1 for c in sample if ord(c) < 9 or (10 < ord(c) < 32 and ord(c) != 13))
        if non_print > 80:
            return None  # Looks binary
        return content
    except:
        return None

def sanitize_env_content(content: str) -> str:
    """Redact actual values in .env files; keep keys for pattern analysis."""
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            key = stripped.split('=', 1)[0]
            lines.append(f"{key}=[REDACTED]")
        else:
            lines.append(line)
    return '\n'.join(lines)

def has_git(path: Path) -> bool:
    return (path / '.git').exists()

def get_current_commit(repo_path: Path) -> str | None:
    try:
        r = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo_path,
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except:
        return None

def get_diff_files(repo_path: Path, last_commit: str) -> list[str]:
    try:
        r = subprocess.run(['git', 'diff', '--name-only', last_commit, 'HEAD'],
                           cwd=repo_path, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return [f for f in r.stdout.strip().split('\n') if f]
    except:
        pass
    return []

def collect_files_full(targets: list[str]) -> dict:
    """Collect all files from targets. Returns {target: [file_dict]}"""
    result = {}
    for target in targets:
        tp = Path(target)
        if not tp.exists():
            print(f"  [WARN] Target not found: {target}")
            continue
        files = []
        for p in sorted(tp.rglob('*')):
            if not p.is_file():
                continue
            if should_exclude(p):
                continue
            content = read_file_safe(p)
            if content is None:
                continue
            # Sanitize .env files before sending to AI
            rel = str(p.relative_to(tp))
            if p.name.startswith('.env'):
                content = sanitize_env_content(content)
            files.append({
                'path': str(p),
                'rel_path': rel,
                'content': content,
                'priority': get_priority(p)
            })
        files.sort(key=lambda x: (0 if x['priority'] == 'HIGH' else 1, x['rel_path']))
        result[target] = files
        print(f"  [INFO] {target}: {len(files)} files")
    return result

def collect_files_diff(targets: list[str], last_commits: dict) -> dict:
    """Collect only changed files since last scan. Falls back to full if no git."""
    result = {}
    for target in targets:
        tp = Path(target)
        if not tp.exists():
            continue
        if not has_git(tp):
            # No git — full scan for this target
            full = collect_files_full([target])
            result.update(full)
            continue
        last_commit = last_commits.get(target)
        if not last_commit:
            # First time — full scan for this target
            full = collect_files_full([target])
            result.update(full)
            continue
        changed = get_diff_files(tp, last_commit)
        if not changed:
            print(f"  [INFO] No changes in {target} since last scan")
            continue
        files = []
        for rel in changed:
            p = tp / rel
            if not p.exists() or not p.is_file():
                continue
            if should_exclude(p):
                continue
            content = read_file_safe(p)
            if content is None:
                continue
            if p.name.startswith('.env'):
                content = sanitize_env_content(content)
            files.append({
                'path': str(p),
                'rel_path': rel,
                'content': content,
                'priority': get_priority(p)
            })
        if files:
            result[target] = files
            print(f"  [INFO] {target}: {len(files)} changed files")
    return result

def build_codebase_text(files_by_target: dict) -> tuple[str, str, int]:
    """Returns (content_text, file_manifest, total_file_count)"""
    content_parts, manifest_lines = [], []
    total = 0
    for target, files in files_by_target.items():
        content_parts.append(f"\n\n## TARGET: {target}\n")
        manifest_lines.append(f"\n### {target}")
        for f in files:
            snippet = f['content'][:40000]  # Cap per-file to keep costs reasonable
            content_parts.append(f"\n### {f['rel_path']} [Priority: {f['priority']}]\n```\n{snippet}\n```\n")
            manifest_lines.append(f"  - {f['rel_path']}")
            total += 1
    return ''.join(content_parts), '\n'.join(manifest_lines), total

def estimate_tokens(text: str) -> int:
    return len(text) // 4

def chunk_files(files_by_target: dict, max_tokens: int) -> list[dict]:
    """Split files into chunks fitting max_tokens. Returns list of files_by_target dicts."""
    chunks = [{}]
    current_tokens = 0
    for target, files in files_by_target.items():
        for f in files:
            ftok = estimate_tokens(f['content']) + 50
            if current_tokens + ftok > max_tokens and current_tokens > 0:
                chunks.append({})
                current_tokens = 0
            chunks[-1].setdefault(target, []).append(f)
            current_tokens += ftok
    return [c for c in chunks if c]

# ─── HYBRID PRE-SCAN ──────────────────────────────────────────────────────────

def tool_available(name: str) -> bool:
    return subprocess.run(['which', name], capture_output=True).returncode == 0

def run_prescan(targets: list[str]) -> dict:
    results = {'gitleaks': [], 'semgrep': [], 'npm_audit': [], 'trivy': [],
               'tools_run': [], 'tools_skipped': []}

    # gitleaks
    if tool_available('gitleaks'):
        findings = []
        for t in targets:
            try:
                r = subprocess.run(
                    ['gitleaks', 'detect', '--source', t, '--report-format', 'json', '--no-banner', '-q'],
                    capture_output=True, text=True, timeout=90)
                if r.stdout.strip():
                    try:
                        data = json.loads(r.stdout)
                        if isinstance(data, list):
                            findings.extend(data[:20])
                    except:
                        pass
            except Exception as e:
                print(f"  [WARN] gitleaks: {e}")
        results['gitleaks'] = findings
        results['tools_run'].append('gitleaks')
    else:
        results['tools_skipped'].append('gitleaks')

    # semgrep
    if tool_available('semgrep'):
        findings = []
        for t in targets:
            try:
                r = subprocess.run(
                    ['semgrep', 'scan', '--config', 'auto', '--json', '--quiet', t],
                    capture_output=True, text=True, timeout=180)
                if r.stdout.strip():
                    try:
                        data = json.loads(r.stdout)
                        findings.extend(data.get('results', [])[:30])
                    except:
                        pass
            except Exception as e:
                print(f"  [WARN] semgrep: {e}")
        results['semgrep'] = findings
        results['tools_run'].append('semgrep')
    else:
        results['tools_skipped'].append('semgrep')

    # npm audit
    npm_ran = False
    npm_findings = []
    for t in targets:
        pkg = Path(t) / 'package.json'
        if pkg.exists():
            try:
                r = subprocess.run(['npm', 'audit', '--json'], cwd=t,
                                   capture_output=True, text=True, timeout=60)
                if r.stdout.strip():
                    try:
                        data = json.loads(r.stdout)
                        for pkg_name, info in list(data.get('vulnerabilities', {}).items())[:20]:
                            npm_findings.append({
                                'package': pkg_name,
                                'severity': info.get('severity', 'unknown'),
                                'fixAvailable': info.get('fixAvailable', False)
                            })
                        npm_ran = True
                    except:
                        pass
            except Exception as e:
                print(f"  [WARN] npm audit: {e}")
    results['npm_audit'] = npm_findings
    results['tools_run' if npm_ran else 'tools_skipped'].append('npm audit')

    # trivy
    if tool_available('trivy'):
        findings = []
        for t in targets:
            try:
                r = subprocess.run(
                    ['trivy', 'fs', t, '--format', 'json',
                     '--scanners', 'vuln,secret,misconfig', '-q'],
                    capture_output=True, text=True, timeout=180)
                if r.stdout.strip():
                    try:
                        data = json.loads(r.stdout)
                        for res in data.get('Results', [])[:5]:
                            findings.extend(res.get('Vulnerabilities', [])[:10])
                            findings.extend(res.get('Secrets', [])[:10])
                    except:
                        pass
            except Exception as e:
                print(f"  [WARN] trivy: {e}")
        results['trivy'] = findings
        results['tools_run'].append('trivy')
    else:
        results['tools_skipped'].append('trivy')

    return results

def format_prescan(prescan: dict) -> str:
    lines = [f"Tools run: {', '.join(prescan['tools_run']) or 'none'}"]
    if prescan['tools_skipped']:
        lines.append(f"Tools skipped: {', '.join(prescan['tools_skipped'])}")

    if prescan['gitleaks']:
        lines.append(f"\n### gitleaks — {len(prescan['gitleaks'])} secret(s) detected:")
        for f in prescan['gitleaks'][:10]:
            lines.append(f"  [{f.get('RuleID','?')}] {f.get('File','?')}:{f.get('StartLine','?')} — {f.get('Description','')}")

    if prescan['semgrep']:
        lines.append(f"\n### semgrep — {len(prescan['semgrep'])} finding(s):")
        for f in prescan['semgrep'][:15]:
            msg = f.get('extra', {}).get('message', '')[:100]
            sev = f.get('extra', {}).get('severity', '?')
            lines.append(f"  [{sev}] {f.get('path','?')}:{f.get('start',{}).get('line','?')} — {msg}")

    if prescan['npm_audit']:
        lines.append(f"\n### npm audit — {len(prescan['npm_audit'])} vulnerability/vulnerabilities:")
        for f in prescan['npm_audit'][:10]:
            fix = " (fix available)" if f.get('fixAvailable') else ""
            lines.append(f"  [{f.get('severity','?')}] {f.get('package','?')}{fix}")

    if prescan['trivy']:
        lines.append(f"\n### trivy — {len(prescan['trivy'])} finding(s):")
        for f in prescan['trivy'][:10]:
            vid = f.get('VulnerabilityID', f.get('RuleID', '?'))
            sev = f.get('Severity', f.get('severity', '?'))
            title = f.get('Title', f.get('Match', ''))[:80]
            lines.append(f"  [{sev}] {vid}: {title}")

    if not any([prescan['gitleaks'], prescan['semgrep'], prescan['npm_audit'], prescan['trivy']]):
        lines.append("No findings from static analysis tools.")

    return '\n'.join(lines)

# ─── API CALLS ────────────────────────────────────────────────────────────────

def call_anthropic(model: str, system_prompt: str, user_prompt: str,
                   max_tokens: int = 8192) -> tuple[str | None, dict]:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}]
    }
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
                return data['content'][0]['text'], data.get('usage', {})
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:300]
            print(f"  [ERROR] Anthropic {e.code} (attempt {attempt+1}): {body_text}")
            if attempt < 2:
                time.sleep(2 ** attempt * 5)
        except Exception as e:
            print(f"  [ERROR] Anthropic call failed (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt * 5)
    return None, {}

def call_gemini(model: str, system_prompt: str, user_prompt: str,
                max_tokens: int = 8192) -> tuple[str | None, dict]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    headers = {"content-type": "application/json"}
    body = {
        "contents": [{"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1}
    }
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
                text = data['candidates'][0]['content']['parts'][0]['text']
                return text, data.get('usageMetadata', {})
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:300]
            print(f"  [ERROR] Gemini {e.code} (attempt {attempt+1}): {body_text}")
            if attempt < 2:
                time.sleep(2 ** attempt * 5)
        except Exception as e:
            print(f"  [ERROR] Gemini call failed (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt * 5)
    return None, {}

# ─── COST TRACKING ────────────────────────────────────────────────────────────

PRICING = {
    'gemini-2.0-flash-exp':     {'input': 0.50,  'output': 3.00},
    'gemini-3-flash-preview':   {'input': 0.50,  'output': 3.00},
    'claude-sonnet-4-6':        {'input': 3.00,  'output': 15.00},
    'claude-opus-4-6':          {'input': 5.00,  'output': 25.00},
}

def calculate_cost(model: str, usage: dict) -> float:
    p = PRICING.get(model, {'input': 3.00, 'output': 15.00})
    inp = usage.get('input_tokens', usage.get('promptTokenCount', 0))
    out = usage.get('output_tokens', usage.get('candidatesTokenCount', 0))
    return round((inp / 1_000_000 * p['input']) + (out / 1_000_000 * p['output']), 5)

# ─── PROMPTS ──────────────────────────────────────────────────────────────────

DIFF_SYSTEM = """You are a security-focused code reviewer analyzing recent changes to a production
codebase. Your job is to identify security regressions or new vulnerabilities
introduced by these changes. Be precise and avoid false positives. Only flag issues
that represent real, exploitable risks."""

def diff_prompt(diff_content: str, prescan: str) -> str:
    return f"""## Changed Files Since Last Scan
{diff_content}

## Pre-Scan Tool Results
{prescan}

Analyze these changes for security issues. Validate pre-scan findings and look for
additional issues that static tools miss (business logic flaws, authorization gaps,
data flow issues).

CRITICAL severity ONLY for: exposed credentials, auth bypasses, SQL injection, RCE, active data leaks.
If no issues found, return empty findings array.

Respond in EXACT JSON:
{{
  "scan_date": "{datetime.datetime.utcnow().isoformat()}Z",
  "files_analyzed": 0,
  "prescan_findings_validated": 0,
  "findings": [
    {{
      "id": "DIFF-001",
      "severity": "HIGH",
      "perspective": "OFFENSIVE",
      "source": "ai",
      "file": "path/to/file.py",
      "lines": "42-58",
      "title": "Short descriptive title",
      "risk": "One sentence risk description.",
      "fix": "One sentence fix suggestion."
    }}
  ],
  "summary": "One paragraph overall assessment."
}}"""

OFFENSIVE_SYSTEM = """You are an offensive security researcher performing a white-box penetration test
review. Think like an attacker who has read the source code. Find exploitable
vulnerabilities, not theoretical weaknesses."""

def offensive_prompt(codebase: str, manifest: str, prescan: str) -> str:
    return f"""## Codebase
{codebase}

## File Manifest
{manifest}

## Pre-Scan Tool Results
{prescan}

Focus on: auth/authz bypasses, injection vectors, IDOR, business logic flaws, missing
input validation, race conditions, privilege escalation, supply chain risks.

For each finding ask: "Could I actually exploit this with reasonable effort?"
Rate exploitation likelihood: CONFIRMED / LIKELY / POSSIBLE / UNLIKELY

Respond in JSON:
{{
  "perspective": "OFFENSIVE",
  "findings": [
    {{
      "id": "OFF-001",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "title": "...",
      "file": "...",
      "lines": "...",
      "attack_scenario": "How an attacker exploits this (2-3 sentences).",
      "exploitation_likelihood": "CONFIRMED|LIKELY|POSSIBLE|UNLIKELY",
      "risk": "Impact if exploited.",
      "fix": "Recommended remediation."
    }}
  ]
}}"""

DEFENSIVE_SYSTEM = """You are a defensive security architect reviewing a codebase for adequate
protections. Identify missing or insufficient security controls."""

def defensive_prompt(codebase: str, manifest: str, prescan: str) -> str:
    return f"""## Codebase
{codebase}

## File Manifest
{manifest}

## Pre-Scan Tool Results
{prescan}

Focus on: input validation, output encoding, auth strength, authz coverage, rate limiting,
error handling (info leakage), security logging, CORS/CSP/headers, session management,
crypto correctness.

Respond in JSON:
{{
  "perspective": "DEFENSIVE",
  "findings": [
    {{
      "id": "DEF-001",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "title": "...",
      "file": "...",
      "lines": "...",
      "missing_control": "What protection is absent.",
      "recommended_control": "What the defense should look like.",
      "risk": "Impact of the gap.",
      "fix": "Recommended remediation."
    }}
  ]
}}"""

PRIVACY_SYSTEM = """You are a data privacy specialist reviewing source code for proper handling of
sensitive information. Consider GDPR, CCPA, and general data protection principles."""

def privacy_prompt(codebase: str, manifest: str, prescan: str) -> str:
    return f"""## Codebase
{codebase}

## File Manifest
{manifest}

## Pre-Scan Tool Results
{prescan}

Focus on: PII encryption (rest/transit), data minimization, secrets management,
logging of sensitive data, retention/deletion mechanisms, third-party data sharing, consent gating.

Classify data type: CREDENTIALS, PII, FINANCIAL, HEALTH, BUSINESS_SENSITIVE

Respond in JSON:
{{
  "perspective": "PRIVACY",
  "findings": [
    {{
      "id": "PRV-001",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "title": "...",
      "file": "...",
      "lines": "...",
      "data_type": "CREDENTIALS|PII|FINANCIAL|HEALTH|BUSINESS_SENSITIVE",
      "risk": "Privacy impact.",
      "fix": "Recommended remediation."
    }}
  ]
}}"""

OPERATIONAL_SYSTEM = """You are a pragmatic security operations lead. Evaluate whether security measures
are practical, maintainable, and real — or security theater providing false confidence."""

def operational_prompt(codebase: str, manifest: str, prescan: str) -> str:
    return f"""## Codebase
{codebase}

## File Manifest
{manifest}

## Pre-Scan Tool Results
{prescan}

Focus on: are configs enforced or just defined? Would a small team maintain these?
Are monitoring gaps going to miss real incidents? Single points of failure?
Could security measures be accidentally disabled in deployment?

Categorize each: THEATER (looks secure, isn't) | GAP (missing something practical) |
FRAGILE (works now, will break) | OVERKILL (more than threat model warrants)

KEY QUESTION per finding: "Would a reasonable attacker pursue this given a B2B SaaS target?"

Respond in JSON:
{{
  "perspective": "OPERATIONAL",
  "findings": [
    {{
      "id": "OPS-001",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "title": "...",
      "file": "...",
      "lines": "...",
      "category": "THEATER|GAP|FRAGILE|OVERKILL",
      "risk": "Operational impact.",
      "fix": "Recommended remediation."
    }}
  ]
}}"""

DEEP_DIVE_SYSTEM = """You are a senior security engineer conducting a deep investigation into a specific
security finding. Provide thorough evidence, realistic attack scenarios, and
actionable remediation with code examples. Be definitive, not hedge-y."""

def deep_dive_prompt(finding: dict, files_content: str, config_content: str) -> str:
    return f"""## Finding Under Investigation
{json.dumps(finding, indent=2)}

## Relevant Source Code
{files_content}

## Related Configuration
{config_content}

Provide a comprehensive deep dive:

1. **EVIDENCE**: Show exact vulnerable code with line numbers. Explain WHY it's vulnerable.
2. **ATTACK SCENARIO**: Step-by-step exploitation walkthrough. Include example payloads/requests.
3. **BLAST RADIUS**: Worst-case impact. What data/systems compromised? Can this chain?
4. **REMEDIATION**: Specific code changes. Before/after code. Recommend best approach.
5. **VERIFICATION**: How to confirm the fix works. Suggest a test case.
6. **EFFORT ESTIMATE**: Quick (<1hr) | Moderate (1-4hrs) | Significant (4hrs-2days) | Major (2+ days)
7. **PRIORITY**: Fix now / this sprint / this quarter / accept risk — justify.

Format as structured markdown."""

# ─── RESPONSE PARSING ─────────────────────────────────────────────────────────

def parse_json_response(text: str) -> dict | None:
    if not text:
        return None
    # Direct parse
    try:
        return json.loads(text.strip())
    except:
        pass
    # Extract from code block
    for pattern in [r'```json\s*(.*?)\s*```', r'```\s*(\{.*?\})\s*```', r'(\{.*\})']:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except:
                pass
    return None

# ─── SCAN HISTORY ─────────────────────────────────────────────────────────────

def load_history() -> dict:
    if SCAN_HISTORY_FILE.exists():
        try:
            return json.loads(SCAN_HISTORY_FILE.read_text())
        except:
            pass
    return {
        "last_scan_commit": {},
        "last_scan_date": None,
        "last_scan_type": None,
        "findings": [],
        "scan_log": [],
        "monthly_cost": {}
    }

def save_history(history: dict):
    SCAN_HISTORY_FILE.write_text(json.dumps(history, indent=2, default=str))

def load_suppressions() -> dict:
    if SUPPRESSIONS_FILE.exists():
        try:
            return json.loads(SUPPRESSIONS_FILE.read_text())
        except:
            pass
    return {"suppressions": []}

def is_suppressed(finding: dict, suppressions: dict) -> bool:
    today = datetime.date.today().isoformat()
    for s in suppressions.get('suppressions', []):
        if s.get('expires') and s['expires'] < today:
            continue
        pattern = s.get('finding_pattern', '*')
        fid = finding.get('id', '')
        file_match = not s.get('file') or s.get('file', '') in finding.get('file', '')
        id_match = (fid.startswith(pattern[:-1]) if pattern.endswith('*')
                    else fid == pattern or pattern == '*')
        if id_match and file_match:
            return True
    return False

def assign_global_ids(findings_from_perspectives: list[list]) -> list:
    """Merge findings from multiple perspectives, deduplicate, assign global IDs."""
    seen = set()
    merged = []
    counter = 1
    # Sort perspectives: process by severity first
    all_f = []
    for findings in findings_from_perspectives:
        all_f.extend(findings)
    sev_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
    all_f.sort(key=lambda x: sev_order.get(x.get('severity', 'LOW'), 4))
    for f in all_f:
        key = f"{f.get('file','')}|{f.get('lines','')}|{f.get('title','')}"
        if key not in seen:
            seen.add(key)
            f['global_id'] = f"FIND-{counter:03d}"
            merged.append(f)
            counter += 1
    return merged

def update_history(history: dict, findings: list, scan_type: str, cost: float) -> dict:
    today = datetime.date.today().isoformat()
    month_key = today[:7]

    # Mark stale open findings as resolved
    new_keys = {f.get('title','') + '|' + f.get('file','') for f in findings}
    for f in history['findings']:
        if f.get('status') == 'open' and f.get('title','') + '|' + f.get('file','') not in new_keys:
            f['status'] = 'resolved'
            f['resolved_date'] = today

    # Add new findings
    existing_keys = {f.get('title','') + '|' + f.get('file','') for f in history['findings']}
    for f in findings:
        key = f.get('title','') + '|' + f.get('file','')
        if key in existing_keys:
            for existing in history['findings']:
                if existing.get('title','') + '|' + existing.get('file','') == key:
                    existing['last_detected'] = today
                    break
        else:
            history['findings'].append({
                'id': f.get('global_id', f.get('id', 'UNK')),
                'first_detected': today,
                'last_detected': today,
                'status': 'open',
                'severity': f.get('severity', 'LOW'),
                'perspective': f.get('perspective', ''),
                'title': f.get('title', ''),
                'file': f.get('file', ''),
                'lines': f.get('lines', ''),
                'risk': f.get('risk', ''),
                'fix': f.get('fix', '')
            })

    # Cost tracking
    history.setdefault('monthly_cost', {})
    history['monthly_cost'][month_key] = round(
        history['monthly_cost'].get(month_key, 0) + cost, 5)

    # Scan log
    history.setdefault('scan_log', [])
    history['scan_log'].append({
        'date': datetime.datetime.now().isoformat(),
        'type': scan_type,
        'findings_count': len(findings),
        'cost': cost
    })
    history['scan_log'] = history['scan_log'][-100:]

    return history

# ─── SLACK DELIVERY ───────────────────────────────────────────────────────────

def post_slack(channel: str, text: str, thread_ts: str = None) -> str | None:
    url = "https://slack.com/api/chat.postMessage"
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"}
    body = {"channel": channel, "text": text, "mrkdwn": True}
    if thread_ts:
        body["thread_ts"] = thread_ts
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if data.get('ok'):
                return data.get('ts')
            else:
                print(f"  [ERROR] Slack error: {data.get('error')}")
    except Exception as e:
        print(f"  [ERROR] Slack post failed: {e}")
    return None

def post_slack_chunked(channel: str, text: str, thread_ts: str = None) -> str | None:
    """Post text, splitting into chunks if > 3800 chars."""
    MAX = 3800
    if len(text) <= MAX:
        return post_slack(channel, text, thread_ts)
    parts = [text[i:i+MAX] for i in range(0, len(text), MAX)]
    ts = None
    for i, part in enumerate(parts):
        suffix = f"\n_[part {i+1}/{len(parts)}]_" if len(parts) > 1 else ""
        result_ts = post_slack(channel, part + suffix, thread_ts)
        if i == 0:
            ts = result_ts
    return ts

# ─── REPORT FORMATTING ────────────────────────────────────────────────────────

SEV_EMOJI = {'CRITICAL': '🔴', 'HIGH': '🟠', 'MEDIUM': '🟡', 'LOW': '🟢'}

def format_report(scan_type: str, files_analyzed: int, model: str,
                  prescan_tools: list, cost: float, monthly_cost: float,
                  findings: list, summary: str, history: dict) -> str:
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-8))).strftime('%Y-%m-%d %H:%M PST')
    type_label = {'diff': 'Nightly Diff', 'full': 'Weekly Full', 'baseline': 'Initial Baseline'}.get(scan_type, scan_type)

    sev_counts = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    for f in findings:
        sev_counts[f.get('severity', 'LOW')] = sev_counts.get(f.get('severity', 'LOW'), 0) + 1

    lines = [
        f"*🔒 Security Scan Report — {now}*",
        f"*Scan Type:* {type_label}  |  *Files:* {files_analyzed}  |  *Model:* `{model}`",
        f"*Pre-Scan Tools:* {', '.join(prescan_tools) if prescan_tools else 'none'}",
        f"*Estimated Cost:* ${cost:.4f}",
        "",
        f"*Summary*\n{summary or 'No issues found.'}",
        "",
        f"*Findings by Severity*",
        (f"🔴 CRITICAL: {sev_counts['CRITICAL']}  |  🟠 HIGH: {sev_counts['HIGH']}  |  "
         f"🟡 MEDIUM: {sev_counts['MEDIUM']}  |  🟢 LOW: {sev_counts['LOW']}"),
    ]

    if findings:
        lines.append("")
        lines.append("*Findings*")
        for f in findings[:20]:
            sev = f.get('severity', 'LOW')
            emoji = SEV_EMOJI.get(sev, '⚪')
            fid = f.get('global_id', f.get('id', 'UNK'))
            persp = f.get('perspective', f.get('category', ''))
            title = f.get('title', 'Unknown')
            file_ref = f.get('file', '')
            lines_ref = f.get('lines', '')
            risk = f.get('risk', '')
            fix = f.get('fix', '')

            lines.append(f"*#{fid}* {emoji} [{sev}] [{persp}] {title}")
            if file_ref:
                lines.append(f"  📄 `{file_ref}`{':'+lines_ref if lines_ref else ''}")
            if risk:
                lines.append(f"  ⚠️ {risk}")
            if fix:
                lines.append(f"  💡 {fix}")
            lines.append(f"  → Reply `deep dive #{fid}` in this thread for full analysis")
            lines.append("")

        if len(findings) > 20:
            lines.append(f"_...and {len(findings) - 20} more. Ask me for the full list._\n")
    else:
        lines += ["", "✅ *No security findings detected.*"]

    # Trend for weekly/baseline
    if scan_type in ('full', 'baseline') and history:
        open_f = [f for f in history.get('findings', []) if f.get('status') == 'open']
        resolved_f = [f for f in history.get('findings', []) if f.get('status') == 'resolved']
        today = datetime.date.today().isoformat()
        new_today = [f for f in open_f if f.get('first_detected') == today]
        lines += [
            "",
            f"*Trend*  —  Open: {len(open_f)}  |  New today: {len(new_today)}  |  Resolved: {len(resolved_f)}"
        ]

    lines += ["", f"_Scan cost: ${cost:.4f}  |  Monthly total: ${monthly_cost:.2f}_"]

    if monthly_cost > 20:
        lines.append(f"⚠️ *Budget alert:* Monthly spend (${monthly_cost:.2f}) exceeds $20 threshold.")

    return '\n'.join(lines)

def format_critical_alert(finding: dict) -> str:
    fid = finding.get('global_id', finding.get('id', 'UNK'))
    return (
        f"🚨 *CRITICAL SECURITY ALERT*\n"
        f"{'=' * 30}\n"
        f"*Finding:* #{fid} — {finding.get('title','')}\n"
        f"*File:* `{finding.get('file','?')}`:{finding.get('lines','')}\n"
        f"*Risk:* {finding.get('risk','')}\n"
        f"*Immediate Action Required:* {finding.get('fix','')}\n"
        f"→ Reply `deep dive #{fid}` for full investigation"
    )

# ─── SCAN RUNNERS ─────────────────────────────────────────────────────────────

def run_diff_scan(config: dict, history: dict):
    print(f"\n[{datetime.datetime.now().isoformat()}] Starting nightly diff scan...")
    targets = config['scan_targets']
    model = config['models']['nightly_diff']
    channel = config['slack_channel_alerts']

    last_commits = history.get('last_scan_commit', {})
    files_by_target = collect_files_diff(targets, last_commits)
    total_files = sum(len(v) for v in files_by_target.values())

    # Update commit hashes regardless
    for t in targets:
        tp = Path(t)
        if has_git(tp):
            commit = get_current_commit(tp)
            if commit:
                history.setdefault('last_scan_commit', {})[t] = commit

    if total_files == 0:
        print("  No changed files. Skipping.")
        post_slack(channel, "🔒 *Nightly Diff Scan* — No changes since last scan. ✅")
        history['last_scan_date'] = datetime.datetime.now().isoformat()
        history['last_scan_type'] = 'diff'
        save_history(history)
        return

    print(f"  Running pre-scan on {total_files} changed files...")
    prescan = run_prescan(targets)
    prescan_text = format_prescan(prescan)

    diff_content, _, file_count = build_codebase_text(files_by_target)
    token_est = estimate_tokens(diff_content)
    print(f"  Token estimate: {token_est:,}")

    # Gemini supports 1M context — no chunking needed for diffs
    prompt = diff_prompt(diff_content[:800000], prescan_text)
    print(f"  Calling {model}...")
    response, usage = call_gemini(model, DIFF_SYSTEM, prompt, max_tokens=4096)
    cost = calculate_cost(model, usage)
    print(f"  Cost: ${cost:.5f}")

    month_key = datetime.date.today().strftime('%Y-%m')
    monthly_cost = history.get('monthly_cost', {}).get(month_key, 0) + cost

    if not response:
        post_slack(channel, "⚠️ *Nightly Diff Scan Failed* — API returned no response. Check `/var/log/security-scanner.log`.")
        return

    result = parse_json_response(response)
    if not result:
        post_slack(channel, f"⚠️ *Nightly Diff Scan* — Could not parse AI response.\n```\n{response[:800]}\n```")
        return

    findings = result.get('findings', [])
    summary = result.get('summary', 'Scan complete.')

    for i, f in enumerate(findings, 1):
        f['global_id'] = f"DIFF-{i:03d}"
        f.setdefault('perspective', 'GENERAL')

    suppressions = load_suppressions()
    findings = [f for f in findings if not is_suppressed(f, suppressions)]

    # Critical alerts immediately
    for f in findings:
        if f.get('severity') == 'CRITICAL':
            post_slack(channel, format_critical_alert(f))

    history = update_history(history, findings, 'diff', cost)
    history['last_scan_date'] = datetime.datetime.now().isoformat()
    history['last_scan_type'] = 'diff'
    save_history(history)

    report = format_report('diff', file_count, model, prescan['tools_run'],
                           cost, monthly_cost, findings, summary, history)
    post_slack_chunked(channel, report)
    print(f"  Done. {len(findings)} findings. Report posted.")

def run_full_scan(config: dict, history: dict, scan_type: str = 'full'):
    print(f"\n[{datetime.datetime.now().isoformat()}] Starting {scan_type} scan...")
    targets = config['scan_targets']
    model = config['models']['weekly_full']
    channel = config['slack_channel_alerts']
    max_tokens = config.get('max_tokens_per_chunk', 150000)

    print("  Collecting all files...")
    files_by_target = collect_files_full(targets)
    total_files = sum(len(v) for v in files_by_target.values())

    if total_files == 0:
        post_slack(channel, "⚠️ *Full Security Scan* — No files found to scan.")
        return

    print(f"  Running pre-scan on {total_files} files...")
    prescan = run_prescan(targets)
    prescan_text = format_prescan(prescan)

    codebase_text, manifest, file_count = build_codebase_text(files_by_target)
    print(f"  Files: {file_count} | Token estimate: {estimate_tokens(codebase_text):,}")

    # 4 perspective scans
    perspectives = [
        ('OFFENSIVE',   OFFENSIVE_SYSTEM,   offensive_prompt),
        ('DEFENSIVE',   DEFENSIVE_SYSTEM,   defensive_prompt),
        ('PRIVACY',     PRIVACY_SYSTEM,     privacy_prompt),
        ('OPERATIONAL', OPERATIONAL_SYSTEM, operational_prompt),
    ]

    all_findings_by_perspective = []
    total_cost = 0.0

    for persp_name, sys_prompt, prompt_fn in perspectives:
        print(f"  [{persp_name}] scanning...")
        chunks = chunk_files(files_by_target, max_tokens)
        persp_findings = []

        for idx, chunk in enumerate(chunks):
            chunk_text, chunk_manifest, _ = build_codebase_text(chunk)
            # Safety truncation
            if len(chunk_text) > 600000:
                chunk_text = chunk_text[:600000] + "\n[...TRUNCATED]"
            user_prompt = prompt_fn(chunk_text, manifest, prescan_text)
            response, usage = call_anthropic(model, sys_prompt, user_prompt, max_tokens=8192)
            cost = calculate_cost(model, usage)
            total_cost += cost
            print(f"    Chunk {idx+1}/{len(chunks)}: ${cost:.5f}")
            if response:
                parsed = parse_json_response(response)
                if parsed:
                    chunk_findings = parsed.get('findings', [])
                    # Tag perspective
                    for f in chunk_findings:
                        f.setdefault('perspective', persp_name)
                    persp_findings.extend(chunk_findings)

        all_findings_by_perspective.append(persp_findings)
        time.sleep(2)

    # Merge and assign global IDs
    all_findings = assign_global_ids(all_findings_by_perspective)

    suppressions = load_suppressions()
    filtered = [f for f in all_findings if not is_suppressed(f, suppressions)]

    # Summarize
    sev = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    for f in filtered:
        sev[f.get('severity', 'LOW')] = sev.get(f.get('severity', 'LOW'), 0) + 1
    summary = (f"Full scan of {file_count} files across {len(targets)} targets. "
               f"Found {len(filtered)} findings: {sev['CRITICAL']} critical, {sev['HIGH']} high, "
               f"{sev['MEDIUM']} medium, {sev['LOW']} low.")

    # Critical alerts
    for f in filtered:
        if f.get('severity') == 'CRITICAL':
            post_slack(channel, format_critical_alert(f))

    # Update commit hashes
    for t in targets:
        tp = Path(t)
        if has_git(tp):
            commit = get_current_commit(tp)
            if commit:
                history.setdefault('last_scan_commit', {})[t] = commit

    month_key = datetime.date.today().strftime('%Y-%m')
    monthly_cost = history.get('monthly_cost', {}).get(month_key, 0) + total_cost

    history = update_history(history, filtered, scan_type, total_cost)
    history['last_scan_date'] = datetime.datetime.now().isoformat()
    history['last_scan_type'] = scan_type
    save_history(history)

    report = format_report(scan_type, file_count, model, prescan['tools_run'],
                           total_cost, monthly_cost, filtered, summary, history)
    post_slack_chunked(channel, report)
    print(f"  Done. {len(filtered)} findings. Cost: ${total_cost:.5f}. Report posted.")

def run_deep_dive(finding_id: str, config: dict, history: dict) -> str:
    print(f"\n[{datetime.datetime.now().isoformat()}] Deep dive: {finding_id}")
    model = config['models']['deep_dive']
    targets = config['scan_targets']

    # Look up finding — match by global_id or by suffix number
    finding = None
    fid_upper = finding_id.upper()
    fid_num = finding_id.split('-')[-1].lstrip('0') if '-' in finding_id else finding_id.lstrip('0')
    for f in history.get('findings', []):
        stored_id = f.get('id', '')
        if stored_id.upper() == fid_upper:
            finding = f
            break
        if stored_id.split('-')[-1].lstrip('0') == fid_num:
            finding = f
            break

    if not finding:
        return f"Finding `{finding_id}` not found in scan history. Run a scan first."

    target_file = finding.get('file', '')
    file_content = ""
    config_content = ""

    for t in targets:
        tp = Path(t)
        # Find the relevant file
        for candidate in [tp / target_file, Path(target_file)]:
            if candidate.exists() and candidate.is_file():
                content = read_file_safe(candidate)
                if content:
                    file_content += f"### {candidate}\n```\n{content[:50000]}\n```\n\n"

        # Collect config files (sanitized)
        for pattern in ['**/.env*', '**/config.*', '**/*.config.js', '**/*.config.ts',
                        '**/docker-compose.yml', '**/nginx.conf']:
            for cfg in tp.glob(pattern):
                if cfg.is_file() and not should_exclude(cfg):
                    content = read_file_safe(cfg)
                    if content:
                        if '.env' in cfg.name:
                            content = sanitize_env_content(content)
                        config_content += f"### {cfg.relative_to(tp)}\n```\n{content[:3000]}\n```\n\n"

    if not file_content:
        file_content = f"File `{target_file}` not found in scan targets. Finding details above."

    prompt = deep_dive_prompt(finding, file_content[:80000], config_content[:15000])
    response, usage = call_anthropic(model, DEEP_DIVE_SYSTEM, prompt, max_tokens=8192)
    cost = calculate_cost(model, usage)
    print(f"  Deep dive cost: ${cost:.5f}")

    month_key = datetime.date.today().strftime('%Y-%m')
    history.setdefault('monthly_cost', {})
    history['monthly_cost'][month_key] = round(
        history['monthly_cost'].get(month_key, 0) + cost, 5)
    history.setdefault('scan_log', []).append({
        'date': datetime.datetime.now().isoformat(),
        'type': 'deep_dive',
        'finding': finding_id,
        'cost': cost
    })
    save_history(history)

    return response or "Deep dive failed — API returned no response."

# ─── CRON SETUP ───────────────────────────────────────────────────────────────

def setup_cron(script_path: str):
    cron_full = f"30 3 * * 0 /usr/bin/python3 {script_path} --full >> /var/log/security-scanner.log 2>&1"
    cron_diff = f"30 3 * * 1-6 /usr/bin/python3 {script_path} --diff >> /var/log/security-scanner.log 2>&1"

    r = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    existing = r.stdout if r.returncode == 0 else ""
    lines = [l for l in existing.splitlines() if 'security-scanner' not in l and l.strip()]
    lines.extend([cron_full, cron_diff])
    new_crontab = '\n'.join(lines) + '\n'

    proc = subprocess.run(['crontab', '-'], input=new_crontab, capture_output=True, text=True)
    if proc.returncode == 0:
        print("  ✓ Cron installed:")
        print(f"    {cron_full}")
        print(f"    {cron_diff}")
    else:
        print(f"  [ERROR] Crontab failed: {proc.stderr}")

# ─── STATUS ───────────────────────────────────────────────────────────────────

def show_status(history: dict):
    month_key = datetime.date.today().strftime('%Y-%m')
    monthly_cost = history.get('monthly_cost', {}).get(month_key, 0)
    open_f = [f for f in history.get('findings', []) if f.get('status') == 'open']
    resolved_f = [f for f in history.get('findings', []) if f.get('status') == 'resolved']

    print(f"Last scan:     {history.get('last_scan_date', 'never')}")
    print(f"Scan type:     {history.get('last_scan_type', 'n/a')}")
    print(f"Open findings: {len(open_f)}")
    print(f"Resolved:      {len(resolved_f)}")
    print(f"Monthly cost:  ${monthly_cost:.4f}")
    print(f"\nRecent scans:")
    for log in history.get('scan_log', [])[-5:]:
        print(f"  {log.get('date','?')[:19]} [{log.get('type','?'):12}] "
              f"{log.get('findings_count', log.get('findings', 0)):3} findings  ${log.get('cost',0):.5f}")
    if open_f:
        print(f"\nOpen findings (top 10):")
        for f in open_f[:10]:
            emoji = SEV_EMOJI.get(f.get('severity','LOW'), '⚪')
            print(f"  {emoji} [{f.get('severity','?'):8}] {f.get('id','?'):10} {f.get('title','?')}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tony's Security Scanner v1.1")
    parser.add_argument('--full',       action='store_true', help='Weekly full scan (4 perspectives, Sonnet 4.6)')
    parser.add_argument('--diff',       action='store_true', help='Nightly diff scan (changed files, Gemini Flash)')
    parser.add_argument('--baseline',   action='store_true', help='Initial baseline full scan')
    parser.add_argument('--deep-dive',  metavar='ID',        help='Deep dive on finding ID (e.g. FIND-003)')
    parser.add_argument('--setup-cron', action='store_true', help='Install cron jobs')
    parser.add_argument('--run',        action='store_true', help='Auto-detect: Sunday=full, else=diff')
    parser.add_argument('--status',     action='store_true', help='Show scan history summary')
    args = parser.parse_args()

    config  = load_config()
    history = load_history()

    if args.setup_cron:
        setup_cron(str(Path(__file__).resolve()))
        return

    if args.status:
        show_status(history)
        return

    if args.deep_dive:
        channel = config['slack_channel_alerts']
        result = run_deep_dive(args.deep_dive, config, history)
        header = f"*🔍 Deep Dive: #{args.deep_dive}*\n\n"
        post_slack_chunked(channel, header + (result or "No response."))
        return

    if args.run:
        if datetime.datetime.now().weekday() == 6:  # Sunday
            run_full_scan(config, history)
        else:
            run_diff_scan(config, history)
        return

    if args.full:
        run_full_scan(config, history)
    elif args.diff:
        run_diff_scan(config, history)
    elif args.baseline:
        run_full_scan(config, history, scan_type='baseline')
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
