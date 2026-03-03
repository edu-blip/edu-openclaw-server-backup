#!/usr/bin/env python3
"""
entities.py - Entity extraction via Anthropic Claude for the knowledge base.
"""

import os
import json
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv("/home/openclaw/.openclaw/.env")

def _load_central_models() -> dict:
    config_path = Path(__file__).parent.parent / "config" / "models.json"
    try:
        return json.loads(config_path.read_text())
    except Exception:
        return {}

_MODELS = _load_central_models()

_anthropic_client = None


def _get_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in /home/openclaw/.openclaw/.env")
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


def extract_entities(text: str, title: str = "", max_chars: int = 4000) -> List[Dict[str, str]]:
    """
    Extract named entities from text using Claude Haiku (model loaded from config/models.json).
    Returns list of {'entity_type': str, 'entity_value': str}
    
    Entity types: person, company, concept, product
    """
    if not text or not text.strip():
        return []

    # Truncate text to stay within reasonable token limits
    excerpt = text[:max_chars].strip()
    if len(text) > max_chars:
        excerpt += "..."

    context = f"Title: {title}\n\n" if title else ""
    prompt = f"""{context}Extract all named entities from the following text. Return a JSON array of objects with "entity_type" and "entity_value" fields.

Entity types to extract:
- "person" — named individuals (e.g., Elon Musk, Sam Altman)
- "company" — organizations, startups, enterprises (e.g., OpenAI, Google, Anthropic)
- "concept" — key technical or business concepts (e.g., RAG, reinforcement learning, product-market fit)
- "product" — specific products or tools (e.g., GPT-4, Slack, Salesforce)

Return ONLY a JSON array, no explanation. Example:
[
  {{"entity_type": "person", "entity_value": "Sam Altman"}},
  {{"entity_type": "company", "entity_value": "OpenAI"}},
  {{"entity_type": "concept", "entity_value": "large language models"}}
]

Text:
{excerpt}"""

    try:
        client = _get_client()
        response = client.messages.create(
            model=_MODELS.get("claude_haiku", "claude-haiku-4-6"),
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        raw = response.content[0].text.strip()

        # Strip markdown code blocks if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw

        entities = json.loads(raw)

        # Validate and normalize
        valid = []
        valid_types = {"person", "company", "concept", "product"}
        for e in entities:
            if isinstance(e, dict) and "entity_type" in e and "entity_value" in e:
                etype = e["entity_type"].lower().strip()
                evalue = e["entity_value"].strip()
                if etype in valid_types and evalue:
                    valid.append({"entity_type": etype, "entity_value": evalue})

        return valid

    except json.JSONDecodeError as e:
        print(f"  ⚠️  Entity extraction: JSON parse error — {e}")
        return []
    except Exception as e:
        print(f"  ⚠️  Entity extraction failed — {e}")
        return []
