#!/usr/bin/env python3
"""
fathom/kb_ingest.py — Ingest Fathom meeting transcripts into Tony's knowledge base.

Usage:
  python3 fathom/kb_ingest.py                    # ingest all un-ingested files in fathom/archive/
  python3 fathom/kb_ingest.py path/to/file.json  # ingest a specific file
  python3 fathom/kb_ingest.py --list             # list all ingested transcripts in KB
  python3 fathom/kb_ingest.py --stats            # show KB stats for fathom_transcript type

Deduplication: uses fathom://transcript/{recording_id} as the source URL.
If two files share the same recording_id, the second is skipped automatically.
"""

import sys
import os
import json
import argparse
from datetime import datetime

# Ensure kb/ and workspace root are in path
WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_DIR = os.path.join(WORKSPACE, "kb")
sys.path.insert(0, KB_DIR)

from dotenv import load_dotenv
load_dotenv("/root/.openclaw/.env")

import store
import embedder
import entities as entity_extractor

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive")
SOURCE_TYPE = "fathom_transcript"
SOURCE_WEIGHT = 1.3
TRANSCRIPT_CHUNK_SIZE = 400   # smaller than default — transcript turns are denser
TRANSCRIPT_CHUNK_OVERLAP = 50


def log(msg: str):
    print(f"[KB_INGEST] {msg}", flush=True)


def fathom_url(recording_id: str) -> str:
    return f"fathom://transcript/{recording_id}"


def format_date(iso_str: str) -> str:
    """Parse ISO datetime string to human-readable date."""
    if not iso_str:
        return "unknown date"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso_str[:10]


def extract_participants(data: dict) -> list:
    """Extract participant list from calendar_invitees or transcript speakers."""
    participants = []
    seen = set()

    # From calendar_invitees
    for inv in data.get("calendar_invitees", []):
        name = inv.get("display_name", "").strip()
        email = inv.get("email", "").strip()
        if name and name not in seen:
            seen.add(name)
            participants.append({"name": name, "email": email})

    # Fallback: unique speakers from transcript
    if not participants:
        for turn in data.get("transcript", []):
            name = (turn.get("speaker") or {}).get("display_name", "").strip()
            if name and name not in seen:
                seen.add(name)
                participants.append({"name": name, "email": ""})

    return participants


def build_summary_chunk(data: dict, title: str, date: str, participants: list) -> str:
    """Build the high-quality summary chunk (from AI-processed summary + action items)."""
    participant_names = ", ".join(p["name"] for p in participants) or "unknown"
    raw_summary = data.get("default_summary") or ""
    if isinstance(raw_summary, dict):
        raw_summary = raw_summary.get("markdown_formatted") or ""
    summary_text = raw_summary.strip()

    action_items = data.get("action_items", [])
    action_text = ""
    if action_items:
        lines = []
        for item in action_items:
            assignee = item.get("assignee_name", "")
            text = item.get("text", "")
            if text:
                lines.append(f"- {assignee}: {text}" if assignee else f"- {text}")
        if lines:
            action_text = "\n\n## Action Items\n" + "\n".join(lines)

    return (
        f"Meeting: {title}\n"
        f"Date: {date}\n"
        f"Participants: {participant_names}\n\n"
        f"{summary_text}"
        f"{action_text}"
    ).strip()


def build_transcript_text(data: dict, title: str, date: str) -> str:
    """Format full transcript as a readable string for chunking."""
    lines = [f"Transcript: {title} ({date})\n"]
    for turn in data.get("transcript", []):
        speaker = (turn.get("speaker") or {}).get("display_name", "Unknown")
        timestamp = turn.get("timestamp", "")
        text = (turn.get("text") or "").strip()
        if text:
            lines.append(f"{speaker} ({timestamp}): {text}")
    return "\n".join(lines)


def ingest_file(filepath: str) -> dict:
    """
    Ingest a single Fathom JSON file into the KB.
    Returns a result dict: {status, title, recording_id, chunks, entities, error}
    """
    filename = os.path.basename(filepath)

    try:
        with open(filepath) as f:
            data = json.load(f)
    except Exception as e:
        return {"status": "error", "file": filename, "error": f"JSON parse failed: {e}"}

    recording_id = str(data.get("recording_id", "")).strip()
    if not recording_id:
        return {"status": "error", "file": filename, "error": "Missing recording_id"}

    url = fathom_url(recording_id)
    title = (data.get("meeting_title") or data.get("title") or "Untitled Meeting").strip()
    date = format_date(data.get("recording_start_time") or data.get("created_at") or "")
    participants = extract_participants(data)

    # Check for duplicate
    if store.source_exists(url):
        return {"status": "skipped", "file": filename, "title": title, "recording_id": recording_id}

    log(f"Ingesting: {filename} — {title} ({date})")

    # Build content chunks
    summary_text = build_summary_chunk(data, title, date, participants)
    transcript_text = build_transcript_text(data, title, date)

    # Chunk and embed: summary first (treated as chunk_index 0), then transcript
    try:
        # Summary as single chunk
        summary_embedding = embedder.embed_texts([summary_text])
        summary_chunk = [{"content": summary_text, "chunk_index": 0, "embedding": summary_embedding[0]}]

        # Transcript chunks
        raw_transcript_chunks = embedder.chunk_text(
            transcript_text,
            chunk_size=TRANSCRIPT_CHUNK_SIZE,
            chunk_overlap=TRANSCRIPT_CHUNK_OVERLAP
        )
        # Prepend context header to each transcript chunk for better search recall
        headed_chunks = [
            f"Transcript excerpt — {title} ({date}):\n\n{c}" for c in raw_transcript_chunks
        ]
        transcript_embeddings = embedder.embed_texts(headed_chunks)
        transcript_chunks = [
            {"content": headed_chunks[i], "chunk_index": i + 1, "embedding": transcript_embeddings[i]}
            for i in range(len(headed_chunks))
        ]

        all_chunks = summary_chunk + transcript_chunks
    except Exception as e:
        return {"status": "error", "file": filename, "title": title, "error": f"Embedding failed: {e}"}

    # Entity extraction from summary (cleaner signal than raw transcript)
    try:
        extracted_entities = entity_extractor.extract_entities(summary_text, title=title)
    except Exception as e:
        log(f"  Entity extraction failed (non-fatal): {e}")
        extracted_entities = []

    # Add participants as explicit entities
    participant_entities = []
    for p in participants:
        if p["name"]:
            participant_entities.append({"entity_type": "person", "entity_value": p["name"]})
        if p["email"]:
            participant_entities.append({"entity_type": "email", "entity_value": p["email"]})

    all_entities = extracted_entities + participant_entities

    # Deduplicate entities
    seen_entities = set()
    deduped_entities = []
    for e in all_entities:
        key = (e["entity_type"], e["entity_value"].lower())
        if key not in seen_entities:
            seen_entities.add(key)
            deduped_entities.append(e)

    # Store in KB
    metadata = {
        "meeting_date": date,
        "participants": [p["name"] for p in participants],
        "share_url": data.get("share_url") or data.get("url") or "",
        "action_items": [i.get("text", "") for i in data.get("action_items", [])],
        "filename": filename,
        "recording_id": recording_id,
    }

    try:
        # Full content = summary + transcript (for any full-text needs)
        full_content = summary_text + "\n\n---\n\n" + transcript_text
        source_id = store.insert_source(
            url=url,
            title=title,
            content=full_content,
            source_type=SOURCE_TYPE,
            source_weight=SOURCE_WEIGHT,
            metadata=metadata,
        )
        store.insert_chunks(source_id, all_chunks)
        store.insert_entities(source_id, deduped_entities)
    except Exception as e:
        return {"status": "error", "file": filename, "title": title, "error": f"DB write failed: {e}"}

    log(f"  ✓ {len(all_chunks)} chunks, {len(deduped_entities)} entities")
    return {
        "status": "ingested",
        "file": filename,
        "title": title,
        "recording_id": recording_id,
        "chunks": len(all_chunks),
        "entities": len(deduped_entities),
    }


def ingest_all_archives() -> list:
    """Ingest all JSON files in the archive directory that aren't already in the KB."""
    if not os.path.isdir(ARCHIVE_DIR):
        log(f"Archive directory not found: {ARCHIVE_DIR}")
        return []

    files = sorted([
        os.path.join(ARCHIVE_DIR, f)
        for f in os.listdir(ARCHIVE_DIR)
        if f.endswith(".json")
    ])

    if not files:
        log("No archive files found.")
        return []

    log(f"Found {len(files)} archive file(s). Processing...")
    return [ingest_file(f) for f in files]


def cmd_list():
    """List all ingested Fathom transcripts."""
    sources = store.list_sources(source_type=SOURCE_TYPE)
    if not sources:
        print("No Fathom transcripts ingested yet.")
        return
    print(f"\n{'Date':<12} {'Title':<50} {'ID'}")
    print("-" * 80)
    for s in sources:
        meta = json.loads(s.get("metadata") or "{}")
        date = meta.get("meeting_date", "?")
        title = (s.get("title") or "")[:48]
        rid = meta.get("recording_id", "?")
        print(f"{date:<12} {title:<50} {rid}")
    print(f"\nTotal: {len(sources)} transcript(s)")


def cmd_stats():
    """Show KB stats for Fathom transcripts."""
    stats = store.get_stats()
    print(f"\nKB total sources: {stats['sources']}")
    print(f"KB total chunks:  {stats['chunks']}")
    print(f"KB by type:")
    for t, count in stats.get("by_type", {}).items():
        marker = " ←" if t == SOURCE_TYPE else ""
        print(f"  {t}: {count}{marker}")


def main():
    store.init_db()

    parser = argparse.ArgumentParser(description="Ingest Fathom transcripts into Tony's KB")
    parser.add_argument("files", nargs="*", help="Specific JSON file(s) to ingest")
    parser.add_argument("--list", action="store_true", help="List ingested transcripts")
    parser.add_argument("--stats", action="store_true", help="Show KB stats")
    args = parser.parse_args()

    if args.list:
        cmd_list()
        return

    if args.stats:
        cmd_stats()
        return

    if args.files:
        results = [ingest_file(f) for f in args.files]
    else:
        results = ingest_all_archives()

    ingested = [r for r in results if r.get("status") == "ingested"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    errors = [r for r in results if r.get("status") == "error"]

    log(f"Done: {len(ingested)} ingested, {len(skipped)} skipped (already in KB), {len(errors)} errors")

    for e in errors:
        log(f"  ERROR {e.get('file')}: {e.get('error')}")

    if ingested:
        total_chunks = sum(r.get("chunks", 0) for r in ingested)
        total_entities = sum(r.get("entities", 0) for r in ingested)
        log(f"Total chunks created: {total_chunks} | Entities: {total_entities}")


if __name__ == "__main__":
    main()
