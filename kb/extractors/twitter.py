#!/usr/bin/env python3
"""
twitter.py - X/Twitter post extraction for the knowledge base.

Uses xAI Grok API (same pattern as scripts/xread.py).
Auto-detects linked articles and returns them for separate ingestion.
"""

import os
import json
import re
import requests
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv("/home/openclaw/.openclaw/.env")

XAI_API_URL = "https://api.x.ai/v1/responses"

def _load_grok_model() -> str:
    from pathlib import Path
    config_path = Path(__file__).parent.parent.parent / "config" / "models.json"
    try:
        import json as _json
        return _json.loads(config_path.read_text()).get("grok_default", "grok-4-1-fast-non-reasoning")
    except Exception:
        return "grok-4-1-fast-non-reasoning"

XAI_MODEL = _load_grok_model()


def _get_xai_key() -> str:
    key = os.environ.get("XAI_API_KEY")
    if not key:
        raise ValueError("XAI_API_KEY not found in /home/openclaw/.openclaw/.env")
    return key


def extract_twitter(url: str, verbose: bool = False) -> Tuple[Dict, List[str]]:
    """
    Extract X/Twitter post content using Grok API.
    
    Returns:
      - (result_dict, linked_urls) where:
        - result_dict has: title, content, metadata
        - linked_urls: list of article URLs found in the tweet (to ingest separately)
    
    Raises RuntimeError on failure.
    """
    if verbose:
        print(f"  🐦 Extracting X/Twitter post: {url}")

    api_key = _get_xai_key()

    prompt = (
        f"Please read this X/Twitter post and provide:\n"
        f"1. The full text of the tweet(s) / thread\n"
        f"2. Author's username and display name\n"
        f"3. A summary of the key points\n"
        f"4. Any URLs or links mentioned in the tweet (especially article links)\n"
        f"5. Any notable context (is this a thread? does it reference other posts?)\n\n"
        f"Format your response as JSON with these fields:\n"
        f"- tweet_text: string (full verbatim tweet text)\n"
        f"- author: string (username and display name)\n"
        f"- summary: string (key points summary)\n"
        f"- linked_urls: array of strings (any URLs found in the tweet)\n"
        f"- thread_context: string (thread summary if applicable)\n\n"
        f"Post URL: {url}"
    )

    payload = {
        "model": XAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a research assistant. When given an X/Twitter URL, "
                    "use your x_search tool to read the full post and thread. "
                    "Always respond with valid JSON as requested."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "tools": [
            {"type": "x_search"},
            {"type": "web_search"}
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    try:
        resp = requests.post(
            XAI_API_URL,
            headers=headers,
            json=payload,
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"xAI API request failed: {e}") from e

    # Extract response text
    output = data.get("output", [])
    result_text = ""
    for item in output:
        if item.get("type") == "message":
            for content_item in item.get("content", []):
                if content_item.get("type") == "output_text":
                    result_text = content_item.get("text", "")
                    break

    if not result_text:
        raise RuntimeError(f"No response text from Grok API for: {url}")

    # Parse JSON response
    parsed = _parse_grok_response(result_text, url, verbose=verbose)
    
    tweet_text = parsed.get("tweet_text", "")
    author = parsed.get("author", "")
    summary = parsed.get("summary", "")
    linked_urls = parsed.get("linked_urls", [])
    thread_context = parsed.get("thread_context", "")

    # Build content: tweet text + summary + thread context
    content_parts = []
    if tweet_text:
        content_parts.append(f"Tweet: {tweet_text}")
    if thread_context:
        content_parts.append(f"Thread context: {thread_context}")
    if summary:
        content_parts.append(f"Summary: {summary}")
    if not content_parts:
        content_parts.append(result_text)

    content = "\n\n".join(content_parts)

    # Generate title
    title = _generate_title(tweet_text or summary, author)

    result = {
        "title": title,
        "content": content,
        "metadata": {
            "author": author,
            "tweet_text": tweet_text[:500] if tweet_text else "",
            "extractor": "grok-xai",
        }
    }

    # Filter linked URLs to only article/web URLs (not other tweets, not images)
    article_urls = _filter_article_urls(linked_urls, url)

    return result, article_urls


def _parse_grok_response(text: str, url: str, verbose: bool = False) -> Dict:
    """Try to parse JSON from Grok's response."""
    # Strip markdown code blocks
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned

    # Try direct JSON parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find JSON block within text
    json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    if verbose:
        print(f"  ⚠️  Could not parse Grok JSON response, using raw text")

    # Return raw text as content
    return {
        "tweet_text": "",
        "author": "",
        "summary": text,
        "linked_urls": _extract_urls_from_text(text),
        "thread_context": "",
    }


def _extract_urls_from_text(text: str) -> List[str]:
    """Extract URLs from plain text."""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    return re.findall(url_pattern, text)


def _filter_article_urls(urls: List[str], original_tweet_url: str) -> List[str]:
    """Filter linked URLs to only include article URLs worth ingesting."""
    skip_patterns = [
        r'twitter\.com',
        r'x\.com',
        r't\.co',  # We'll let the caller resolve t.co links if needed
        r'pic\.twitter',
        r'instagram\.com',
        r'linkedin\.com/posts',
        r'youtube\.com/watch',
        r'youtu\.be',
    ]

    article_urls = []
    for url in urls:
        if url == original_tweet_url:
            continue
        if any(re.search(p, url, re.IGNORECASE) for p in skip_patterns):
            continue
        if url.startswith("http"):
            article_urls.append(url)

    return list(set(article_urls))  # deduplicate


def _generate_title(text: str, author: str) -> str:
    """Generate a short title for a tweet."""
    if not text:
        return "X/Twitter Post"

    # Use first 80 chars of text
    excerpt = text[:80].strip()
    if len(text) > 80:
        excerpt += "..."

    if author:
        return f"@{author.lstrip('@')}: {excerpt}"
    return excerpt
