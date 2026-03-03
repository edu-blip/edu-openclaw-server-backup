# Tony Knowledge Base (RAG System)

A personal retrieval-augmented generation (RAG) knowledge base for Rethoric / Edu. Drop any URL into Slack, and Tony ingests, chunks, and embeds it for semantic search.

---

## Architecture

```
URL dropped in Slack #knowledge-base
        ↓
   ingest.py
        ↓
   Type detection (web / youtube / twitter / pdf)
        ↓
   Extractor (trafilatura / youtube-transcript-api / Grok API / pdfplumber)
        ↓
   Chunking (500-word chunks, 50-word overlap)
        ↓
   Embeddings (OpenAI text-embedding-3-small)
        ↓
   Entity extraction (Claude claude-haiku-4-5)
        ↓
   SQLite (kb.db) — sources, chunks, entities tables
        ↓
   Ready for search
```

**Search flow:**
```
@tony search: <query>
        ↓
   search.py — embed query → cosine similarity over all chunks
        ↓
   Rank by: (0.8 × cosine_sim + 0.2 × time_decay) × source_weight
        ↓
   Return top-N sources with snippets + entities
```

---

## File Structure

```
kb/
├── README.md           ← this file
├── config.json         ← chunk size, weights, decay settings
├── kb.db               ← SQLite database (auto-created)
├── ingest.py           ← ingestion CLI
├── search.py           ← search CLI
├── store.py            ← SQLite operations
├── embedder.py         ← OpenAI embeddings + chunking
├── entities.py         ← Claude entity extraction
└── extractors/
    ├── __init__.py
    ├── web.py           ← trafilatura + BeautifulSoup fallback
    ├── youtube.py       ← youtube-transcript-api + yt-dlp fallback
    ├── twitter.py       ← xAI Grok API
    └── pdf.py           ← pdfplumber
```

---

## Setup

### Requirements
All dependencies are installed globally:
```
trafilatura, youtube-transcript-api, yt-dlp, pdfplumber,
beautifulsoup4, numpy, openai, anthropic, python-dotenv, requests
```

### API Keys (in `/home/openclaw/.openclaw/.env`)
```
OPENAI_API_KEY=...      # for embeddings (text-embedding-3-small)
ANTHROPIC_API_KEY=...   # for entity extraction (claude-haiku-4-5)
XAI_API_KEY=...         # for Twitter/X post reading (Grok)
```

### First Run
The database initializes automatically on first use:
```bash
python3 kb/ingest.py --stats
```

---

## Usage

### Ingestion

```bash
# Ingest a web article
python3 kb/ingest.py https://example.com/article

# Ingest a YouTube video
python3 kb/ingest.py https://youtube.com/watch?v=...

# Ingest a tweet/thread
python3 kb/ingest.py https://x.com/someone/status/123

# Ingest a PDF (URL or local path)
python3 kb/ingest.py https://example.com/paper.pdf
python3 kb/ingest.py /path/to/local.pdf

# Force source type
python3 kb/ingest.py https://... --type web

# Verbose debug output
python3 kb/ingest.py https://... --verbose

# List all ingested sources
python3 kb/ingest.py --list

# Database stats
python3 kb/ingest.py --stats
```

### Search

```bash
# Basic search
python3 kb/search.py "what is retrieval augmented generation"

# Limit results
python3 kb/search.py "LinkedIn outreach strategies" --limit 10

# Filter by source type
python3 kb/search.py "startup funding" --type web
python3 kb/search.py "product demo" --type youtube

# JSON output (for programmatic use)
python3 kb/search.py "query" --json
```

---

## Ranking Formula

```
final_score = (0.8 × cosine_similarity + 0.2 × time_score) × source_weight

time_score = exp(-days_old / 90)  # exponential decay over 90 days
```

**Source weights** (configurable in `config.json`):
- PDF: 1.5x (usually high-quality, dense content)
- Web: 1.0x
- YouTube: 0.9x
- Twitter: 0.7x (shorter, less dense)

---

## How Tony Integrates (Slack Flow)

### 1. Ingestion Trigger
Channel: `#knowledge-base`  
Pattern: Any URL dropped in the channel triggers ingestion.

Tony's Slack listener should call:
```python
from kb.ingest import ingest_url
result = ingest_url(url)
```
Then reply in thread: `✅ Ingested: [Title] (web, 12 chunks)`

### 2. Search Trigger
Pattern: `@tony search: <query>` in any channel.

Tony's handler should call:
```python
from kb.search import search
results = search(query, limit=5)
```
Then format results and reply in thread.

### 3. Automatic Article Expansion
When a tweet containing an article link is ingested, the extractor returns `linked_urls`. Ingest those too automatically.

---

## Supported Source Types

| Type | Extractor | Fallback |
|------|-----------|----------|
| Web articles | trafilatura | requests + BeautifulSoup |
| YouTube videos | youtube-transcript-api | yt-dlp --write-auto-sub |
| X/Twitter posts | xAI Grok API | — |
| PDFs | pdfplumber | — |

---

## Pending Items

### 🔴 Browser Paywall Extraction
Function `extract_with_browser(url)` in `extractors/web.py` is a placeholder.  
Requires: Chrome extension relay active + Playwright implementation.  
Current behavior: raises `NotImplementedError` with helpful message.  
TODO: Implement via subprocess → Playwright with Chrome user profile.

### 🟡 Twitter Rate Limits
The xAI Grok API call costs ~$5/1k requests (currently in beta pricing).  
No additional Twitter/X API key needed — Grok handles it.

### 🟡 Slack #knowledge-base Channel
Slack trigger (listening to URLs in the channel) needs to be wired up in Tony's main Slack handler. The KB system itself is standalone — just call `ingest_url(url)` from the message handler.

### 🟡 PDF OCR
pdfplumber handles text-layer PDFs only. Scanned PDFs (image-only) will fail.  
TODO: Add OCR fallback via `pytesseract` or `pdf2image` + `tesseract`.

---

## Configuration (`config.json`)

```json
{
  "chunk_size": 500,          // words per chunk
  "chunk_overlap": 50,        // word overlap between chunks
  "source_weights": {
    "pdf": 1.5,
    "web": 1.0,
    "youtube": 0.9,
    "twitter": 0.7
  },
  "time_decay_days": 90,      // half-life for time decay scoring
  "time_decay_weight": 0.2,   // weight of time score in final ranking
  "similarity_weight": 0.8,   // weight of cosine similarity in final ranking
  "default_limit": 5          // default search results limit
}
```

---

## Database Schema

```sql
-- Ingested sources
sources (id, url, title, content, source_type, source_weight, extracted_at, metadata)

-- Text chunks with vector embeddings
chunks (id, source_id, content, chunk_index, embedding)

-- Named entities (person, company, concept, product)
entities (id, source_id, entity_type, entity_value)
```

Database location: `/home/openclaw/.openclaw/workspace/kb/kb.db`

---

*Built for Rethoric / Edu — Tony KB v1.0*
