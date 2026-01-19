#!/usr/bin/env python3
"""Test script to debug simple_reindex.py issues."""

import sys
import os
from pathlib import Path

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

print("Starting test script...")

try:
    from app.config import get_settings
    print("✓ Imported get_settings")
    settings = get_settings()
    print(f"✓ Got settings, has OpenAI key: {'✓' if settings.openai_api_key else '✗'}")
except Exception as e:
    print(f"✗ Error importing/using get_settings: {e}")
    sys.exit(1)

try:
    from app.database import get_db
    print("✓ Imported get_db")
    db = get_db()
    print("✓ Got database")
except Exception as e:
    print(f"✗ Error importing/using get_db: {e}")
    sys.exit(1)

try:
    from app.services.rag.enrichment import ChunkEnricher
    print("✓ Imported ChunkEnricher")
    enricher = ChunkEnricher()
    print("✓ Got enricher")
except Exception as e:
    print(f"✗ Error importing/using ChunkEnricher: {e}")
    sys.exit(1)

try:
    import openai
    print("✓ Imported openai")
    client = openai.OpenAI(api_key=settings.openai_api_key)
    print("✓ Got OpenAI client")
except Exception as e:
    print(f"✗ Error with OpenAI: {e}")
    sys.exit(1)

try:
    from app.services.rag.embeddings import BatchEmbedder, compute_content_hash
    print("✓ Imported BatchEmbedder")
    embedder = BatchEmbedder(client, db.client)
    print("✓ Got BatchEmbedder")
except Exception as e:
    print(f"✗ Error with BatchEmbedder: {e}")
    sys.exit(1)

print("\n✓ All imports successful!")
print("Testing a simple embedding...")

try:
    test_text = "This is a test chunk"
    embedding = embedder.embed_single(test_text)
    print(f"✓ Generated embedding with {len(embedding)} dimensions")
except Exception as e:
    print(f"✗ Error generating embedding: {e}")
    sys.exit(1)

print("\n✓ All tests passed!")
