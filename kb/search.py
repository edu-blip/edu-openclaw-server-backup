#!/usr/bin/env python3
"""
search.py - Query the knowledge base using semantic search.

Usage:
  python3 kb/search.py "your natural language query"
  python3 kb/search.py "query" --limit 10
  python3 kb/search.py "query" --type web
  python3 kb/search.py "query" --json         # output as JSON
"""

import sys
import os
import json
import math
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Ensure kb/ is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv("/root/.openclaw/.env")

import store
import embedder

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)


def time_score(extracted_at: str, decay_days: float) -> float:
    """
    Compute time decay score.
    time_score = exp(-days_old / decay_days)
    Returns value between 0 and 1 (1 = just ingested, approaches 0 = very old)
    """
    try:
        extracted = datetime.fromisoformat(extracted_at)
        if extracted.tzinfo is None:
            extracted = extracted.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        days_old = max(0, (now - extracted).total_seconds() / 86400)
        return math.exp(-days_old / decay_days)
    except Exception:
        return 0.5  # Default if we can't parse


def compute_final_score(cosine_sim: float, t_score: float, source_weight: float,
                         sim_weight: float, decay_weight: float) -> float:
    """
    final_score = (similarity_weight * cosine_sim + time_decay_weight * time_score) * source_weight
    """
    return (sim_weight * cosine_sim + decay_weight * t_score) * source_weight


def search(query: str, limit: int = None, source_type: str = None) -> List[Dict]:
    """
    Search the knowledge base for chunks matching the query.
    
    Returns list of result dicts sorted by final_score (descending).
    """
    store.init_db()

    limit = limit or CONFIG["default_limit"]
    sim_weight = CONFIG["similarity_weight"]
    decay_weight = CONFIG["time_decay_weight"]
    decay_days = CONFIG["time_decay_days"]

    # Embed the query
    query_embedding = embedder.embed_single(query)

    # Get all chunks with embeddings
    all_chunks = store.get_all_chunks_with_embeddings()

    if not all_chunks:
        return []

    # Filter by source type if specified
    if source_type:
        all_chunks = [c for c in all_chunks if c["source_type"] == source_type]

    # Score all chunks
    scored = []
    for chunk in all_chunks:
        cosine_sim = embedder.cosine_similarity(query_embedding, chunk["embedding"])
        t_score = time_score(chunk["extracted_at"], decay_days)
        final = compute_final_score(
            cosine_sim, t_score, chunk["source_weight"],
            sim_weight, decay_weight
        )
        scored.append({
            **chunk,
            "cosine_sim": cosine_sim,
            "time_score": t_score,
            "final_score": final,
        })

    # Sort by final score descending
    scored.sort(key=lambda x: x["final_score"], reverse=True)

    # Deduplicate by source — keep best chunk per source, up to limit
    seen_sources = {}
    results = []
    for item in scored:
        source_id = item["source_id"]
        if source_id not in seen_sources:
            seen_sources[source_id] = item
            results.append(item)
        # Also add secondary chunks from same source if score is high enough
        elif item["final_score"] > 0.5 and len(results) < limit * 2:
            results.append(item)

        if len(results) >= limit * 3:
            break

    # Re-sort and take top results
    results.sort(key=lambda x: x["final_score"], reverse=True)

    # Get entities for each unique source
    seen = set()
    final_results = []
    for item in results:
        if len(final_results) >= limit:
            break
        source_id = item["source_id"]
        if source_id in seen:
            continue
        seen.add(source_id)

        # Get entities for this source
        item_entities = store.get_entities_for_source(source_id)
        item["entities"] = item_entities
        final_results.append(item)

    return final_results


def format_age(extracted_at: str) -> str:
    """Format age string from extracted_at timestamp."""
    try:
        extracted = datetime.fromisoformat(extracted_at)
        if extracted.tzinfo is None:
            extracted = extracted.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        delta = now - extracted
        days = delta.days
        hours = int(delta.total_seconds() / 3600)
        
        if hours < 1:
            return "just now"
        elif hours < 24:
            return f"{hours}h ago"
        elif days == 1:
            return "1 day ago"
        elif days < 30:
            return f"{days} days ago"
        elif days < 365:
            months = days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"
        else:
            years = days // 365
            return f"{years} year{'s' if years > 1 else ''} ago"
    except Exception:
        return extracted_at or "unknown"


def format_snippet(content: str, max_len: int = 200) -> str:
    """Extract a clean snippet from chunk content."""
    # Clean up whitespace
    snippet = " ".join(content.split())
    if len(snippet) > max_len:
        snippet = snippet[:max_len].rsplit(" ", 1)[0] + "..."
    return snippet


def format_entities(entities: List[Dict]) -> str:
    """Format entities for display."""
    if not entities:
        return ""
    
    by_type = {}
    for e in entities:
        etype = e["entity_type"].title()
        if etype not in by_type:
            by_type[etype] = []
        by_type[etype].append(e["entity_value"])
    
    parts = []
    for etype, values in sorted(by_type.items()):
        unique_vals = list(dict.fromkeys(values))[:5]  # dedup, max 5 per type
        parts.append(f"{etype}: {', '.join(unique_vals)}")
    
    return " | ".join(parts)


def print_results(query: str, results: List[Dict], as_json: bool = False):
    """Print search results in human-readable or JSON format."""
    if as_json:
        output = {
            "query": query,
            "results": [
                {
                    "rank": i + 1,
                    "title": r["title"],
                    "source_type": r["source_type"],
                    "url": r["url"],
                    "score": round(r["final_score"], 4),
                    "cosine_sim": round(r["cosine_sim"], 4),
                    "snippet": format_snippet(r["chunk_content"]),
                    "age": format_age(r["extracted_at"]),
                    "entities": r.get("entities", []),
                }
                for i, r in enumerate(results)
            ]
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    print(f"\n🔍 Results for: \"{query}\"\n")

    if not results:
        print("   No results found. Try ingesting more content with:")
        print("   python3 kb/ingest.py <url>")
        return

    for i, r in enumerate(results):
        age = format_age(r["extracted_at"])
        score = round(r["final_score"], 4)
        snippet = format_snippet(r["chunk_content"])
        entities_str = format_entities(r.get("entities", []))

        print(f"{i + 1}. {r['title']} ({r['source_type']}, {age}) — score: {score}")
        print(f"   Source: {r['url']}")
        print(f"   Snippet: {snippet}")
        if entities_str:
            print(f"   Entities: {entities_str}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Search the Tony knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--limit", type=int, default=None, help="Max results to return")
    parser.add_argument("--type", choices=["web", "youtube", "twitter", "pdf"],
                        help="Filter by source type")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        sys.exit(1)

    results = search(args.query, limit=args.limit, source_type=args.type)
    print_results(args.query, results, as_json=args.json)


if __name__ == "__main__":
    main()
