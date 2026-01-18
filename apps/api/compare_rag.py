#!/usr/bin/env python3
"""Compare OLD vs NEW RAG pipeline to see the difference

Uses the original match_chunks function (no user_id needed).
"""

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from supabase import create_client

from app.services.rag.intent import IntentClassifier
from app.services.rag.reranker import Reranker


def get_clients():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not all([supabase_url, supabase_key, openai_key]):
        print("ERROR: Missing environment variables")
        print("Required: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENAI_API_KEY")
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)
    openai_client = OpenAI(api_key=openai_key)
    return supabase, openai_client


def embed_query(openai_client, query: str) -> List[float]:
    """Embed a query"""
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    )
    return response.data[0].embedding


@dataclass
class ScoredChunk:
    """Minimal scored chunk for reranker compatibility"""
    chunk: Dict[str, Any]
    raw_score: float
    normalized_score: float
    weighted_score: float

    @property
    def source_type(self) -> str:
        return self.chunk.get("source_type", "")

    @property
    def doc_key(self) -> str:
        return self.chunk.get("path", self.chunk.get("url", "unknown"))


async def old_pipeline(supabase, openai_client, query: str, repo: str = None):
    """OLD: Simple vector search, no intent routing, no reranking"""
    start = time.time()

    query_embedding = embed_query(openai_client, query)

    # Simple search - just vector similarity, top 8
    params = {
        "p_query_embedding": query_embedding,
        "p_k": 8,
        "p_min_score": 0.3,  # Lower threshold
    }
    if repo:
        params["p_repo"] = repo

    result = supabase.rpc("match_chunks", params).execute()

    latency = (time.time() - start) * 1000
    return result.data or [], latency


async def new_pipeline(supabase, openai_client, query: str, repo: str = None):
    """NEW: Intent routing + weighted retrieval + reranking + diversity"""
    start = time.time()

    # 1. Classify intent
    classifier = IntentClassifier()
    intent_result = classifier.classify(query)

    # 2. Get more candidates (40 instead of 8)
    query_embedding = embed_query(openai_client, query)

    params = {
        "p_query_embedding": query_embedding,
        "p_k": 40,
        "p_min_score": 0.3,  # Lower threshold
    }
    if repo:
        params["p_repo"] = repo

    result = supabase.rpc("match_chunks", params).execute()
    raw_chunks = result.data or []

    if not raw_chunks:
        return [], (time.time() - start) * 1000, intent_result, "no_results"

    # 3. Normalize scores (min-max within result set)
    scores = [c.get("score", 0) for c in raw_chunks]
    min_score, max_score = min(scores), max(scores)
    score_range = max_score - min_score if max_score > min_score else 1.0

    # 4. Apply intent weights
    weights = intent_result.scope_weights
    scored_chunks = []

    for chunk in raw_chunks:
        raw = chunk.get("score", 0)
        normalized = (raw - min_score) / score_range if score_range > 0 else 1.0
        source_type = chunk.get("source_type", "code")
        weight = weights.get(source_type, 1.0)
        weighted = normalized * weight

        scored_chunks.append(ScoredChunk(
            chunk=chunk,
            raw_score=raw,
            normalized_score=normalized,
            weighted_score=weighted,
        ))

    # 5. Sort by weighted score
    scored_chunks.sort(key=lambda x: x.weighted_score, reverse=True)

    # 6. Rerank with diversity
    reranker = Reranker(openai_client)
    rerank_result = await reranker.rerank(
        query=query,
        candidates=scored_chunks[:20],  # Top 20 for reranking
        top_k=8,
    )

    latency = (time.time() - start) * 1000
    chunks = [sc.chunk for sc in rerank_result.chunks]

    return chunks, latency, intent_result, rerank_result.method


def print_results(title: str, chunks: list, latency: float, extra: dict = None):
    print(f"\n{'=' * 60}")
    print(f"{title}")
    print(f"{'=' * 60}")
    print(f"Latency: {latency:.0f}ms | Results: {len(chunks)}")

    if extra:
        for k, v in extra.items():
            print(f"{k}: {v}")

    print("-" * 60)

    source_counts = {}
    doc_counts = {}

    for i, chunk in enumerate(chunks[:8]):
        source_type = chunk.get("source_type", "?")
        path = chunk.get("path", chunk.get("url", "?")) or "?"
        path_short = path[:40]
        score = chunk.get("score", 0)
        content = (chunk.get("content", "") or "")[:80].replace("\n", " ")

        source_counts[source_type] = source_counts.get(source_type, 0) + 1
        doc_counts[path] = doc_counts.get(path, 0) + 1

        print(f"[{i+1}] {source_type:8} | {path_short:40} | {score:.3f}")
        print(f"    {content}...")

    print("-" * 60)
    print(f"Source distribution: {source_counts}")
    print(f"Unique docs: {len(doc_counts)}")


async def compare(queries: list, repo: str = None):
    supabase, openai_client = get_clients()

    for query in queries:
        print(f"\n\n{'#' * 70}")
        print(f"QUERY: {query}")
        if repo:
            print(f"REPO: {repo}")
        print(f"{'#' * 70}")

        # Run OLD pipeline
        old_chunks, old_latency = await old_pipeline(supabase, openai_client, query, repo)
        print_results("OLD PIPELINE (simple vector search)", old_chunks, old_latency)

        # Run NEW pipeline
        new_chunks, new_latency, intent, method = await new_pipeline(
            supabase, openai_client, query, repo
        )
        print_results(
            "NEW PIPELINE (intent + rerank + diversity)",
            new_chunks,
            new_latency,
            {
                "Intent": f"{intent.intent.value} (confidence: {intent.confidence:.2f})",
                "Matched keywords": list(intent.matched_keywords),
                "Rerank method": method,
            }
        )

        # Summary
        print(f"\n📊 COMPARISON:")

        old_sources = set(c.get("source_type") for c in old_chunks[:8])
        new_sources = set(c.get("source_type") for c in new_chunks[:8])

        old_docs = set((c.get("path") or c.get("url") or "?")[:40] for c in old_chunks[:8])
        new_docs = set((c.get("path") or c.get("url") or "?")[:40] for c in new_chunks[:8])

        print(f"  Source types: OLD={len(old_sources)} → NEW={len(new_sources)}")
        print(f"  Unique docs:  OLD={len(old_docs)} → NEW={len(new_docs)}")
        print(f"  Latency:      OLD={old_latency:.0f}ms → NEW={new_latency:.0f}ms")

        if len(new_sources) > len(old_sources):
            print("  ✅ NEW has more diverse sources")
        if len(new_docs) > len(old_docs):
            print("  ✅ NEW has more diverse documents")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Compare OLD vs NEW RAG pipeline")
    parser.add_argument("--repo", "-r", help="Filter by repo (optional)")
    parser.add_argument("--query", "-q", action="append", dest="queries",
                        help="Custom query (can repeat)")
    args = parser.parse_args()

    queries = args.queries or [
        "How does the code work?",
        "What does the README say?",
        "How to use this project?",
    ]

    asyncio.run(compare(queries, args.repo))


if __name__ == "__main__":
    main()
