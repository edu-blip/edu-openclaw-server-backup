#!/usr/bin/env python3
"""
youtube.py - YouTube video extraction for the knowledge base.

Primary: youtube-transcript-api
Fallback: yt-dlp --write-auto-sub
"""

import re
import os
import json
import subprocess
import tempfile
from typing import Dict
from urllib.parse import urlparse, parse_qs


def extract_youtube_id(url: str) -> str:
    """Extract YouTube video ID from various URL formats."""
    # Handle youtu.be short URLs
    if "youtu.be/" in url:
        vid_id = url.split("youtu.be/")[1].split("?")[0].split("&")[0]
        return vid_id.strip()

    # Handle youtube.com/watch?v=...
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "v" in qs:
        return qs["v"][0]

    # Handle youtube.com/embed/...
    if "/embed/" in parsed.path:
        return parsed.path.split("/embed/")[1].split("/")[0]

    # Handle youtube.com/shorts/...
    if "/shorts/" in parsed.path:
        return parsed.path.split("/shorts/")[1].split("/")[0]

    raise ValueError(f"Could not extract YouTube video ID from: {url}")


def extract_youtube(url: str, verbose: bool = False) -> Dict:
    """
    Extract YouTube video transcript and metadata.
    
    Returns dict with:
      - title: str
      - content: str (full transcript)
      - metadata: dict (channel, upload_date, description)
    """
    if verbose:
        print(f"  🎬 Extracting YouTube video: {url}")

    video_id = extract_youtube_id(url)
    if verbose:
        print(f"  🎬 Video ID: {video_id}")

    # Try youtube-transcript-api first
    result = _extract_with_transcript_api(video_id, url, verbose=verbose)
    if result:
        return result

    if verbose:
        print("  ⚠️  transcript API failed, trying yt-dlp fallback...")

    # Fallback: yt-dlp
    result = _extract_with_ytdlp(url, verbose=verbose)
    if result:
        return result

    raise RuntimeError(
        f"Could not extract transcript from YouTube video: {url}. "
        "The video may have no captions available."
    )


def _extract_with_transcript_api(video_id: str, url: str, verbose: bool = False) -> Dict:
    """Extract transcript using youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

        # v1.x uses instance methods; v0.x used class methods
        api = YouTubeTranscriptApi()
        
        transcript = None
        entries = None

        # Try fetching English transcript directly (fastest path)
        try:
            entries = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
        except Exception:
            pass

        # Fallback: list all and pick best
        if not entries:
            try:
                transcript_list = api.list(video_id)
                # Try manual transcripts first
                try:
                    transcript = transcript_list.find_manually_created_transcript(["en", "en-US", "en-GB"])
                except Exception:
                    pass
                # Try auto-generated
                if not transcript:
                    try:
                        transcript = transcript_list.find_generated_transcript(["en", "en-US", "en-GB"])
                    except Exception:
                        pass
                # Any available
                if not transcript:
                    try:
                        transcript = next(iter(transcript_list))
                        if transcript.language_code != "en":
                            transcript = transcript.translate("en")
                    except Exception:
                        pass
                if transcript:
                    entries = transcript.fetch()
            except Exception:
                pass

        if not entries:
            return None

        # Build full transcript text — handle both dict-like and object entries
        text_parts = []
        for entry in entries:
            if hasattr(entry, 'text'):
                text = entry.text.strip()
            elif hasattr(entry, 'get'):
                text = entry.get("text", "").strip()
            else:
                text = str(entry).strip()
            if text:
                text_parts.append(text)
        
        full_transcript = " ".join(text_parts)
        
        # Get video metadata via yt-dlp or basic URL parsing
        metadata = _get_video_metadata(url, verbose=verbose)

        return {
            "title": metadata.get("title") or f"YouTube Video ({video_id})",
            "content": full_transcript,
            "metadata": {
                "channel": metadata.get("channel", ""),
                "upload_date": metadata.get("upload_date", ""),
                "description": metadata.get("description", ""),
                "video_id": video_id,
                "extractor": "youtube-transcript-api",
            }
        }

    except ImportError:
        if verbose:
            print("  ⚠️  youtube-transcript-api not installed")
        return None
    except Exception as e:
        if verbose:
            print(f"  ⚠️  youtube-transcript-api error: {e}")
        return None


def _extract_with_ytdlp(url: str, verbose: bool = False) -> Dict:
    """Extract transcript using yt-dlp --write-auto-sub."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, "%(id)s.%(ext)s")
            
            cmd = [
                "yt-dlp",
                "--write-auto-sub",
                "--sub-lang", "en",
                "--skip-download",
                "--no-warnings",
                "--output", output_template,
                "--print-json",
                url,
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            # Parse metadata from JSON output
            metadata = {}
            if result.stdout.strip():
                try:
                    for line in result.stdout.strip().split("\n"):
                        if line.strip().startswith("{"):
                            metadata = json.loads(line.strip())
                            break
                except json.JSONDecodeError:
                    pass
            
            # Find subtitle file
            transcript_text = ""
            for fname in os.listdir(tmpdir):
                if fname.endswith(".vtt") or fname.endswith(".srt"):
                    sub_path = os.path.join(tmpdir, fname)
                    with open(sub_path, "r", encoding="utf-8") as f:
                        raw_sub = f.read()
                    transcript_text = _parse_subtitle(raw_sub)
                    break
            
            if not transcript_text:
                if verbose:
                    print("  ⚠️  yt-dlp: no subtitle file found")
                return None
            
            return {
                "title": metadata.get("title") or metadata.get("fulltitle") or url,
                "content": transcript_text,
                "metadata": {
                    "channel": metadata.get("uploader") or metadata.get("channel", ""),
                    "upload_date": metadata.get("upload_date", ""),
                    "description": (metadata.get("description") or "")[:500],
                    "video_id": metadata.get("id", ""),
                    "extractor": "yt-dlp",
                }
            }
    
    except FileNotFoundError:
        if verbose:
            print("  ⚠️  yt-dlp not found in PATH")
        return None
    except subprocess.TimeoutExpired:
        if verbose:
            print("  ⚠️  yt-dlp timed out")
        return None
    except Exception as e:
        if verbose:
            print(f"  ⚠️  yt-dlp error: {e}")
        return None


def _get_video_metadata(url: str, verbose: bool = False) -> Dict:
    """Get video metadata using yt-dlp --skip-download."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--no-warnings", "--skip-download", "--print-json", url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                if line.strip().startswith("{"):
                    data = json.loads(line.strip())
                    return {
                        "title": data.get("title") or data.get("fulltitle", ""),
                        "channel": data.get("uploader") or data.get("channel", ""),
                        "upload_date": data.get("upload_date", ""),
                        "description": (data.get("description") or "")[:500],
                    }
    except Exception:
        pass
    return {}


def _parse_subtitle(raw: str) -> str:
    """Parse VTT or SRT subtitle file to plain text."""
    lines = raw.split("\n")
    text_lines = []
    
    for line in lines:
        line = line.strip()
        # Skip VTT header, timestamps, IDs, and empty lines
        if not line:
            continue
        if line.startswith("WEBVTT"):
            continue
        if re.match(r'^\d+$', line):  # SRT sequence numbers
            continue
        if re.match(r'^\d{2}:\d{2}', line):  # Timestamps
            continue
        if "-->" in line:  # VTT/SRT timestamp lines
            continue
        # Remove HTML tags from subtitles
        line = re.sub(r'<[^>]+>', '', line)
        if line:
            text_lines.append(line)
    
    # Deduplicate consecutive identical lines (common in auto-subs)
    deduped = []
    prev = None
    for line in text_lines:
        if line != prev:
            deduped.append(line)
            prev = line
    
    return " ".join(deduped)
