#!/usr/bin/env python3
"""
ingest.py - Main CLI for ingesting URLs into the knowledge base.

Usage:
  python3 kb/ingest.py <url>
  python3 kb/ingest.py <url> --type pdf     # force type
  python3 kb/ingest.py <url> --verbose      # debug output
  python3 kb/ingest.py --list               # list all ingested sources
  python3 kb/ingest.py --stats              # show DB stats
"""

import sys
import os
import json
import argparse
from datetime import datetime, timezone

# Ensure kb/ is in path for sibling imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv("/home/openclaw/.openclaw/.env")

import store
import embedder
import entities as entity_extractor

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)


def get_source_weight(source_type: str) -> float:
    return CONFIG["source_weights"].get(source_type, 1.0)


def ingest_url(url: str, force_type: str = None, verbose: bool = False) -> dict:
    """
    Ingest a single URL into the knowledge base.
    
    Returns a result dict with status, title, source_type, chunks, entities, error.
    """
    from extractors import detect_type, extract_web, extract_youtube, extract_twitter, extract_pdf

    # Detect type
    source_type = force_type or detect_type(url)
    if verbose:
        print(f"  🔍 Detected type: {source_type}")

    linked_urls = []  # For twitter auto-linked articles

    try:
        # Extract content based on type
        if source_type == "youtube":
            extracted = extract_youtube(url, verbose=verbose)
            title = extracted["title"]
            content = extracted["content"]
            metadata = extracted["metadata"]

        elif source_type == "twitter":
            extracted, linked_urls = extract_twitter(url, verbose=verbose)
            title = extracted["title"]
            content = extracted["content"]
            metadata = extracted["metadata"]

        elif source_type == "pdf":
            extracted = extract_pdf(url, verbose=verbose)
            title = extracted["title"]
            content = extracted["content"]
            metadata = extracted["metadata"]

        else:  # web (default)
            extracted = extract_web(url, verbose=verbose)
            title = extracted["title"]
            content = extracted["content"]
            metadata = extracted["metadata"]

        if not content or not content.strip():
            return {
                "status": "error",
                "url": url,
                "error": "No content extracted",
                "hint": "Page may be empty, require JavaScript, or be paywalled"
            }

        if verbose:
            print(f"  📝 Extracted {len(content)} chars: {title[:60]}")

    except NotImplementedError as e:
        return {
            "status": "error",
            "url": url,
            "error": str(e),
            "hint": "Browser extraction required — activate Chrome relay"
        }
    except Exception as e:
        hint = ""
        error_str = str(e).lower()
        if "paywall" in error_str or "subscription" in error_str or "401" in error_str or "403" in error_str:
            hint = "Content may be paywalled — try with Chrome relay session"
        elif "timeout" in error_str:
            hint = "Request timed out — try again or check connectivity"
        return {
            "status": "error",
            "url": url,
            "error": str(e),
            "hint": hint
        }

    # Store in DB
    source_weight = get_source_weight(source_type)
    try:
        source_id = store.insert_source(
            url=url,
            title=title,
            content=content,
            source_type=source_type,
            source_weight=source_weight,
            metadata=metadata,
        )
        if verbose:
            print(f"  💾 Source stored with ID: {source_id}")
    except Exception as e:
        return {
            "status": "error",
            "url": url,
            "error": f"DB insert failed: {e}",
            "hint": ""
        }

    # Chunk and embed
    try:
        chunk_list = embedder.prepare_chunks_with_embeddings(
            content,
            chunk_size=CONFIG["chunk_size"],
            chunk_overlap=CONFIG["chunk_overlap"],
        )
        store.insert_chunks(source_id, chunk_list)
        if verbose:
            print(f"  🧮 Embedded {len(chunk_list)} chunks")
    except Exception as e:
        print(f"  ⚠️  Embedding failed: {e}")
        # Still store without embeddings — partial success
        chunk_list = []

    # Extract entities
    entity_list = []
    try:
        entity_list = entity_extractor.extract_entities(content, title=title)
        store.insert_entities(source_id, entity_list)
        if verbose:
            print(f"  🏷️  Extracted {len(entity_list)} entities")
    except Exception as e:
        print(f"  ⚠️  Entity extraction failed: {e}")

    result = {
        "status": "ok",
        "url": url,
        "title": title,
        "source_type": source_type,
        "chunks": len(chunk_list),
        "entities": len(entity_list),
        "linked_urls": linked_urls,
    }

    return result


def cmd_stats():
    """Print DB statistics."""
    stats = store.get_stats()
    print(f"📊 Knowledge Base Stats")
    print(f"   Sources:  {stats['sources']}")
    print(f"   Chunks:   {stats['chunks']} ({stats['chunks_with_embeddings']} with embeddings)")
    print(f"   Entities: {stats['entities']}")
    if stats['by_type']:
        print(f"   By type:")
        for stype, count in stats['by_type'].items():
            print(f"     {stype}: {count}")


def cmd_list(source_type: str = None):
    """Print all ingested sources."""
    sources = store.list_sources(source_type=source_type)
    if not sources:
        print("📭 No sources ingested yet.")
        return
    print(f"📚 Ingested sources ({len(sources)}):\n")
    for s in sources:
        age = ""
        if s.get("extracted_at"):
            try:
                extracted = datetime.fromisoformat(s["extracted_at"])
                if extracted.tzinfo is None:
                    extracted = extracted.replace(tzinfo=timezone.utc)
                delta = datetime.now(tz=timezone.utc) - extracted
                days = delta.days
                if days == 0:
                    age = "today"
                elif days == 1:
                    age = "1 day ago"
                else:
                    age = f"{days} days ago"
            except Exception:
                age = s["extracted_at"]
        print(f"  [{s['source_type']}] {s['title'] or '(no title)'} — {age}")
        print(f"       {s['url']}")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest URLs into the Tony knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("url", nargs="?", help="URL to ingest")
    parser.add_argument("--type", choices=["web", "youtube", "twitter", "pdf"],
                        help="Force source type")
    parser.add_argument("--list", action="store_true", help="List all ingested sources")
    parser.add_argument("--stats", action="store_true", help="Show DB statistics")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose debug output")

    args = parser.parse_args()

    # Initialize DB
    store.init_db()

    if args.stats:
        cmd_stats()
        return

    if args.list:
        cmd_list(source_type=args.type)
        return

    if not args.url:
        parser.print_help()
        sys.exit(1)

    url = args.url.strip()
    print(f"⏳ Ingesting: {url}")
    if args.verbose:
        print()

    result = ingest_url(url, force_type=args.type, verbose=args.verbose)

    if result["status"] == "error":
        print(f"\n❌ Failed: {url}")
        print(f"   Error: {result['error']}")
        if result.get("hint"):
            print(f"   Hint: {result['hint']}")
        sys.exit(1)

    print(f"\n✅ Ingested: {result['title']}")
    print(f"   Type: {result['source_type']} | Chunks: {result['chunks']} | Entities: {result['entities']}")
    print(f"   URL: {url}")

    # Handle linked URLs from tweets
    if result.get("linked_urls"):
        print(f"\n🔗 Found {len(result['linked_urls'])} linked article(s) — ingesting:")
        for linked_url in result["linked_urls"]:
            print(f"\n⏳ Ingesting linked: {linked_url}")
            linked_result = ingest_url(linked_url, verbose=args.verbose)
            if linked_result["status"] == "error":
                print(f"   ❌ Failed: {linked_result['error']}")
            else:
                print(f"   ✅ Ingested: {linked_result['title']}")
                print(f"      Type: {linked_result['source_type']} | Chunks: {linked_result['chunks']}")


if __name__ == "__main__":
    main()
