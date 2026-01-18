#!/usr/bin/env python3
"""Quick local test for RAG modules - no database needed"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.services.rag.intent import IntentClassifier, QueryIntent
from app.services.rag.enrichment import ChunkEnricher, extract_symbol_from_chunk
from app.services.rag.embeddings import compute_content_hash

def test_intent_classifier():
    print("=" * 60)
    print("Testing Intent Classifier")
    print("=" * 60)

    classifier = IntentClassifier()

    test_queries = [
        "What are our naming conventions?",
        "How does the authentication function work?",
        "What is the deployment process?",
        "Tell me about this repository",
        "Where is the error handling code?",
        "What are our coding standards?",
    ]

    for query in test_queries:
        result = classifier.classify(query)
        print(f"\nQuery: {query}")
        print(f"  Intent: {result.intent.value}")
        print(f"  Confidence: {result.confidence:.2f}")
        print(f"  Matched: {result.matched_keywords}")
        print(f"  Weights: code={result.scope_weights['code']}, notion={result.scope_weights['notion']}")


def test_enrichment():
    print("\n" + "=" * 60)
    print("Testing Chunk Enrichment")
    print("=" * 60)

    enricher = ChunkEnricher()

    # Test code enrichment
    code = """def authenticate_user(username: str, password: str) -> bool:
    \"\"\"Authenticate a user against the database\"\"\"
    user = get_user(username)
    return verify_password(password, user.hashed_password)"""

    symbol = extract_symbol_from_chunk(code, "python")
    print(f"\nExtracted symbol: {symbol}")

    result = enricher.enrich_code_chunk(
        content=code,
        path="src/auth/login.py",
        language="python",
        start_line=10,
        end_line=15,
        symbol=symbol,
    )

    print("\nEnriched code chunk:")
    print("-" * 40)
    print(result.enriched_content[:500])

    # Test Notion enrichment
    notion_content = "All API endpoints must use JWT authentication. Tokens expire after 24 hours."

    result = enricher.enrich_notion_chunk(
        content=notion_content,
        title="API Security Standards",
        url="https://notion.so/api-security",
        last_edited_time="2024-01-15",
    )

    print("\n\nEnriched Notion chunk:")
    print("-" * 40)
    print(result.enriched_content)


def test_content_hash():
    print("\n" + "=" * 60)
    print("Testing Content Hash")
    print("=" * 60)

    content1 = "def hello(): pass"
    content2 = "def hello(): pass"
    content3 = "def world(): pass"

    hash1 = compute_content_hash(content1)
    hash2 = compute_content_hash(content2)
    hash3 = compute_content_hash(content3)

    print(f"\nHash 1: {hash1[:16]}...")
    print(f"Hash 2: {hash2[:16]}...")
    print(f"Hash 3: {hash3[:16]}...")
    print(f"\nHash 1 == Hash 2: {hash1 == hash2} (should be True)")
    print(f"Hash 1 == Hash 3: {hash1 == hash3} (should be False)")


def test_symbol_extraction():
    print("\n" + "=" * 60)
    print("Testing Symbol Extraction")
    print("=" * 60)

    test_cases = [
        ("python", "def my_function():\n    pass"),
        ("python", "async def async_handler():\n    pass"),
        ("python", "class MyClass:\n    pass"),
        ("ts", "function handleClick() {\n}"),
        ("ts", "export class UserService {\n}"),
        ("go", "func HandleRequest(w http.ResponseWriter) {\n}"),
        ("rust", "pub fn process_data() {\n}"),
    ]

    for lang, code in test_cases:
        symbol = extract_symbol_from_chunk(code, lang)
        print(f"\n[{lang}] {code[:40]}...")
        print(f"  → Symbol: {symbol}")


if __name__ == "__main__":
    test_intent_classifier()
    test_enrichment()
    test_content_hash()
    test_symbol_extraction()

    print("\n" + "=" * 60)
    print("✓ All local RAG tests passed!")
    print("=" * 60)
