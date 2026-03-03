#!/usr/bin/env python3
"""
store.py - SQLite operations for the knowledge base.
"""

import sqlite3
import json
import os
import numpy as np
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

DB_PATH = "/home/openclaw/.openclaw/workspace/kb/kb.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize the database schema if not already present."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT,
                content TEXT,
                source_type TEXT,
                source_weight REAL DEFAULT 1.0,
                extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata JSON
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                chunk_index INTEGER,
                embedding BLOB
            );

            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
                entity_type TEXT,
                entity_value TEXT,
                UNIQUE(source_id, entity_type, entity_value)
            );

            CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
            CREATE INDEX IF NOT EXISTS idx_entities_source ON entities(source_id);
        """)
    conn.close()


def source_exists(url: str) -> Optional[int]:
    """Check if a URL is already ingested. Returns source_id or None."""
    conn = get_connection()
    row = conn.execute("SELECT id FROM sources WHERE url = ?", (url,)).fetchone()
    conn.close()
    return row["id"] if row else None


def insert_source(url: str, title: str, content: str, source_type: str,
                  source_weight: float, metadata: Optional[Dict] = None) -> int:
    """Insert a new source and return its ID."""
    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO sources (url, title, content, source_type, source_weight, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (url, title, content, source_type, source_weight, json.dumps(metadata or {}))
        )
        source_id = cur.lastrowid

        # Clean up old chunks/entities if replacing
        conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
        conn.execute("DELETE FROM entities WHERE source_id = ?", (source_id,))

    conn.close()
    return source_id


def insert_chunks(source_id: int, chunks: List[Dict[str, Any]]):
    """Insert chunks with embeddings for a source.
    
    chunks: list of {'content': str, 'chunk_index': int, 'embedding': np.ndarray}
    """
    conn = get_connection()
    with conn:
        for chunk in chunks:
            embedding_blob = None
            if chunk.get("embedding") is not None:
                embedding_blob = chunk["embedding"].astype(np.float32).tobytes()
            conn.execute(
                """INSERT INTO chunks (source_id, content, chunk_index, embedding)
                   VALUES (?, ?, ?, ?)""",
                (source_id, chunk["content"], chunk["chunk_index"], embedding_blob)
            )
    conn.close()


def insert_entities(source_id: int, entities: List[Dict[str, str]]):
    """Insert entities for a source.
    
    entities: list of {'entity_type': str, 'entity_value': str}
    """
    conn = get_connection()
    with conn:
        for entity in entities:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO entities (source_id, entity_type, entity_value)
                       VALUES (?, ?, ?)""",
                    (source_id, entity["entity_type"], entity["entity_value"])
                )
            except sqlite3.IntegrityError:
                pass
    conn.close()


def get_all_chunks_with_embeddings() -> List[Dict]:
    """Fetch all chunks that have embeddings, with source metadata."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT 
            c.id AS chunk_id,
            c.source_id,
            c.content AS chunk_content,
            c.chunk_index,
            c.embedding,
            s.url,
            s.title,
            s.source_type,
            s.source_weight,
            s.extracted_at,
            s.metadata
        FROM chunks c
        JOIN sources s ON c.source_id = s.id
        WHERE c.embedding IS NOT NULL
    """).fetchall()
    conn.close()

    results = []
    for row in rows:
        embedding = np.frombuffer(row["embedding"], dtype=np.float32)
        results.append({
            "chunk_id": row["chunk_id"],
            "source_id": row["source_id"],
            "chunk_content": row["chunk_content"],
            "chunk_index": row["chunk_index"],
            "embedding": embedding,
            "url": row["url"],
            "title": row["title"],
            "source_type": row["source_type"],
            "source_weight": row["source_weight"],
            "extracted_at": row["extracted_at"],
            "metadata": json.loads(row["metadata"] or "{}"),
        })
    return results


def get_entities_for_source(source_id: int) -> List[Dict]:
    """Get all entities for a source."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT entity_type, entity_value FROM entities WHERE source_id = ?",
        (source_id,)
    ).fetchall()
    conn.close()
    return [{"entity_type": r["entity_type"], "entity_value": r["entity_value"]} for r in rows]


def list_sources(source_type: Optional[str] = None) -> List[Dict]:
    """List all ingested sources."""
    conn = get_connection()
    if source_type:
        rows = conn.execute(
            "SELECT id, url, title, source_type, extracted_at FROM sources WHERE source_type = ? ORDER BY extracted_at DESC",
            (source_type,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, url, title, source_type, extracted_at FROM sources ORDER BY extracted_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> Dict:
    """Get database statistics."""
    conn = get_connection()
    stats = {
        "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "chunks_with_embeddings": conn.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0],
        "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
        "by_type": {},
    }
    rows = conn.execute("SELECT source_type, COUNT(*) FROM sources GROUP BY source_type").fetchall()
    for row in rows:
        stats["by_type"][row[0]] = row[1]
    conn.close()
    return stats
