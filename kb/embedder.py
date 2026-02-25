#!/usr/bin/env python3
"""
embedder.py - OpenAI embedding + text chunking for the knowledge base.
"""

import os
import json
import numpy as np
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv("/root/.openclaw/.env")

# Lazy import openai to avoid slow startup
_openai_client = None


def _get_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in /root/.openclaw/.env")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """
    Split text into overlapping chunks by word count.
    Returns list of text chunks.
    """
    if not text or not text.strip():
        return []

    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        if end >= len(words):
            break
        start += chunk_size - chunk_overlap  # slide with overlap

    return chunks


def embed_texts(texts: List[str], model: str = "text-embedding-3-small") -> List[np.ndarray]:
    """
    Get embeddings for a list of texts using OpenAI API.
    Batches requests for efficiency.
    Returns list of numpy float32 arrays.
    """
    if not texts:
        return []

    client = _get_client()

    # OpenAI supports up to 2048 inputs per request; batch in groups of 100 to be safe
    batch_size = 100
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        # Clean texts
        batch = [t.replace("\n", " ").strip() for t in batch]
        batch = [t for t in batch if t]  # remove empty

        if not batch:
            continue

        try:
            response = client.embeddings.create(
                model=model,
                input=batch,
            )
            for item in response.data:
                all_embeddings.append(np.array(item.embedding, dtype=np.float32))
        except Exception as e:
            raise RuntimeError(f"OpenAI embedding API error: {e}") from e

    return all_embeddings


def embed_single(text: str, model: str = "text-embedding-3-small") -> np.ndarray:
    """Embed a single text string."""
    results = embed_texts([text], model=model)
    if not results:
        raise ValueError("Embedding returned empty result")
    return results[0]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def prepare_chunks_with_embeddings(text: str, chunk_size: int = 500,
                                    chunk_overlap: int = 50) -> List[Dict[str, Any]]:
    """
    Chunk text and compute embeddings for all chunks.
    Returns list of dicts: {'content', 'chunk_index', 'embedding'}
    """
    chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not chunks:
        return []

    embeddings = embed_texts(chunks)

    result = []
    for i, (chunk_text_content, emb) in enumerate(zip(chunks, embeddings)):
        result.append({
            "content": chunk_text_content,
            "chunk_index": i,
            "embedding": emb,
        })

    return result
