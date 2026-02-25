#!/usr/bin/env python3
"""
web.py - Web article extraction for the knowledge base.

Primary: trafilatura
Fallback: requests + BeautifulSoup
Paywall: placeholder (requires Chrome relay)
"""

import re
import requests
from typing import Dict, Optional
from urllib.parse import urlparse


def detect_type(url: str) -> str:
    """
    Detect the source type from a URL.
    Returns: 'youtube', 'twitter', 'pdf', or 'web'
    """
    url_lower = url.lower()
    parsed = urlparse(url_lower)
    hostname = parsed.hostname or ""

    # YouTube
    if any(h in hostname for h in ["youtube.com", "youtu.be"]):
        return "youtube"

    # Twitter / X
    if any(h in hostname for h in ["twitter.com", "x.com", "t.co"]):
        return "twitter"

    # PDF
    if url_lower.endswith(".pdf") or "application/pdf" in url_lower:
        return "pdf"

    # Try HEAD request to check content type
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; KBBot/1.0)"})
        ct = resp.headers.get("Content-Type", "")
        if "application/pdf" in ct:
            return "pdf"
    except Exception:
        pass

    return "web"


def extract_web(url: str, verbose: bool = False) -> Dict:
    """
    Extract article content from a URL.
    
    Returns dict with:
      - title: str
      - content: str
      - metadata: dict (author, date, description, etc.)
    
    Raises:
      - RuntimeError if extraction fails
      - PaywallError (subclass of RuntimeError) if content seems paywalled
    """
    if verbose:
        print(f"  🌐 Extracting web content from: {url}")

    # Try trafilatura first
    result = _extract_with_trafilatura(url, verbose=verbose)
    if result and result.get("content") and len(result["content"]) > 200:
        return result

    if verbose:
        print("  ⚠️  trafilatura failed or got too little content, trying BeautifulSoup fallback...")

    # Fallback: requests + BeautifulSoup
    result = _extract_with_bs4(url, verbose=verbose)
    if result and result.get("content") and len(result["content"]) > 100:
        return result

    # If both fail, check for paywall
    raise RuntimeError(
        f"Could not extract content from {url}. "
        "The page may be paywalled, JavaScript-heavy, or blocked. "
        "Hint: try with Chrome relay session."
    )


def _extract_with_trafilatura(url: str, verbose: bool = False) -> Optional[Dict]:
    """Extract using trafilatura."""
    try:
        import trafilatura
        from trafilatura.settings import use_config

        config = use_config()
        config.set("DEFAULT", "TIMEOUT", "30")

        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            if verbose:
                print("  ⚠️  trafilatura: failed to download URL")
            return None

        # Extract with metadata using bare_extraction (returns dict)
        result = trafilatura.bare_extraction(
            downloaded,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )

        if result is None:
            # Try plain text extraction as fallback
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            if text:
                result = {"text": text}
            else:
                return None

        # Handle dict result from bare_extraction
        if isinstance(result, dict):
            content = result.get("text", "") or result.get("raw_text", "") or ""
            title = result.get("title", "") or ""
            author = result.get("author", "") or ""
            date = result.get("date", "") or ""
            description = result.get("description", "") or result.get("excerpt", "") or ""
        else:
            content = str(result)
            title = ""
            author = ""
            date = ""
            description = ""

        # Try to get title from raw HTML if trafilatura didn't find one
        if not title:
            import re as _re
            title_match = _re.search(r'<title[^>]*>([^<]+)</title>', downloaded, _re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()

        return {
            "title": title or _url_to_title(url),
            "content": content,
            "metadata": {
                "author": author,
                "date": date,
                "description": description,
                "extractor": "trafilatura",
            }
        }

    except ImportError:
        if verbose:
            print("  ⚠️  trafilatura not installed")
        return None
    except Exception as e:
        if verbose:
            print(f"  ⚠️  trafilatura error: {e}")
        return None


def _extract_with_bs4(url: str, verbose: bool = False) -> Optional[Dict]:
    """Extract using requests + BeautifulSoup fallback."""
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise
        for tag in soup(["script", "style", "nav", "footer", "header",
                          "aside", "advertisement", "noscript", "iframe"]):
            tag.decompose()

        # Get title
        title = ""
        if soup.title:
            title = soup.title.string or ""
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)

        # Try article tag first, then main, then body
        for selector in ["article", "main", '[role="main"]', ".post-content",
                          ".article-content", ".entry-content", "body"]:
            container = soup.select_one(selector)
            if container:
                content = container.get_text(separator="\n", strip=True)
                if len(content) > 200:
                    break
        else:
            content = soup.get_text(separator="\n", strip=True)

        # Clean up extra whitespace
        content = re.sub(r'\n{3,}', '\n\n', content)

        return {
            "title": title.strip() or _url_to_title(url),
            "content": content,
            "metadata": {
                "extractor": "beautifulsoup",
            }
        }

    except ImportError:
        if verbose:
            print("  ⚠️  beautifulsoup4 not installed")
        return None
    except Exception as e:
        if verbose:
            print(f"  ⚠️  BeautifulSoup error: {e}")
        return None


def extract_with_browser(url: str) -> Dict:
    """
    Placeholder for browser-based extraction (for paywalled content).
    Requires the Chrome extension relay to be active.
    
    TODO: Implement using Playwright with Chrome profile via subprocess.
    """
    raise NotImplementedError(
        "Browser extraction requires Chrome relay — run manually. "
        "Activate the OpenClaw Browser Relay toolbar button in Chrome, "
        "then re-run with the browser flag."
    )


def _url_to_title(url: str) -> str:
    """Generate a title from URL as fallback."""
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path:
            # Get last path segment, clean it up
            slug = path.split("/")[-1]
            slug = re.sub(r'[-_]', ' ', slug)
            slug = re.sub(r'\.[^.]+$', '', slug)  # remove extension
            return slug.title() or parsed.hostname or url
        return parsed.hostname or url
    except Exception:
        return url
