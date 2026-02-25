#!/usr/bin/env python3
"""
pdf.py - PDF extraction for the knowledge base.

Uses pdfplumber for text extraction.
Handles both local file paths and remote PDF URLs.
"""

import os
import re
import tempfile
import requests
from typing import Dict


def extract_pdf(url_or_path: str, verbose: bool = False) -> Dict:
    """
    Extract text from a PDF file (local path or remote URL).
    
    Returns dict with:
      - title: str
      - content: str (full extracted text)
      - metadata: dict (page_count, etc.)
    """
    import pdfplumber

    if verbose:
        print(f"  📄 Extracting PDF: {url_or_path}")

    # Handle remote URLs
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        pdf_path = _download_pdf(url_or_path, verbose=verbose)
        cleanup = True
    else:
        # Local file
        pdf_path = url_or_path
        cleanup = False
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    try:
        return _extract_from_file(pdf_path, url_or_path, verbose=verbose)
    finally:
        if cleanup and pdf_path and os.path.exists(pdf_path):
            os.unlink(pdf_path)


def _download_pdf(url: str, verbose: bool = False) -> str:
    """Download a PDF from a URL to a temp file. Returns temp file path."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; KBBot/1.0)",
    }
    
    if verbose:
        print(f"  ⬇️  Downloading PDF from: {url}")
    
    try:
        resp = requests.get(url, headers=headers, timeout=60, stream=True)
        resp.raise_for_status()
        
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
            raise ValueError(f"URL does not appear to be a PDF (Content-Type: {content_type})")
        
        # Write to temp file
        suffix = ".pdf"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        for chunk in resp.iter_content(chunk_size=8192):
            tmp.write(chunk)
        tmp.close()
        
        return tmp.name
    
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to download PDF from {url}: {e}") from e


def _extract_from_file(pdf_path: str, source_url: str, verbose: bool = False) -> Dict:
    """Extract text content from a PDF file."""
    import pdfplumber

    try:
        all_text = []
        page_count = 0
        
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            
            if verbose:
                print(f"  📄 PDF has {page_count} pages")
            
            for i, page in enumerate(pdf.pages):
                # Extract text from page
                text = page.extract_text()
                
                if text and text.strip():
                    # Add page marker for multi-page docs
                    if page_count > 1:
                        all_text.append(f"\n[Page {i + 1}]\n{text.strip()}")
                    else:
                        all_text.append(text.strip())
                
                # Also try to extract tables
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        table_text = _table_to_text(table)
                        if table_text:
                            all_text.append(table_text)
        
        if not all_text:
            raise RuntimeError(
                f"No text could be extracted from PDF: {source_url}. "
                "The PDF may be scanned (image-only) or encrypted."
            )
        
        full_text = "\n\n".join(all_text)
        
        # Try to extract title from first page
        title = _extract_title_from_text(full_text, source_url)
        
        # Clean up text
        full_text = _clean_pdf_text(full_text)
        
        return {
            "title": title,
            "content": full_text,
            "metadata": {
                "page_count": page_count,
                "extractor": "pdfplumber",
            }
        }
    
    except ImportError:
        raise RuntimeError("pdfplumber is not installed. Run: pip install pdfplumber")
    except Exception as e:
        raise RuntimeError(f"PDF extraction failed: {e}") from e


def _table_to_text(table) -> str:
    """Convert a pdfplumber table to readable text."""
    if not table:
        return ""
    
    rows = []
    for row in table:
        cells = [str(cell or "").strip() for cell in row]
        if any(cells):
            rows.append(" | ".join(cells))
    
    return "\n".join(rows)


def _extract_title_from_text(text: str, fallback_url: str) -> str:
    """Try to extract document title from the beginning of the text."""
    # Look at first 500 chars for title-like content
    first_part = text[:500].strip()
    lines = [l.strip() for l in first_part.split("\n") if l.strip()]
    
    if lines:
        # First non-empty line is often the title
        candidate = lines[0]
        if 10 < len(candidate) < 200:
            return candidate
    
    # Fallback to URL-based title
    filename = os.path.basename(fallback_url.split("?")[0])
    filename = os.path.splitext(filename)[0]
    if filename:
        return re.sub(r'[-_]', ' ', filename).title()
    
    return "PDF Document"


def _clean_pdf_text(text: str) -> str:
    """Clean up common PDF text extraction artifacts."""
    # Remove excessive whitespace
    text = re.sub(r'[ \t]{3,}', '  ', text)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    
    # Fix hyphenated words across lines (common in PDFs)
    text = re.sub(r'-\n([a-z])', r'\1', text)
    
    # Remove page numbers that appear alone on a line
    text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
    
    return text.strip()
