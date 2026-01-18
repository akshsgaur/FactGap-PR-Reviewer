#!/usr/bin/env python3
"""
factgap-eval-smoke CLI

Smoke test for RAG pipeline evaluation.
Runs test queries and displays retrieval/reranking statistics.
"""

import asyncio
import argparse
import logging
import os
import sys
import time

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from openai import OpenAI
from supabase import create_client

from app.services.rag.retrieval import ScopedRetriever
from app.services.rag.reranker import Reranker
from app.services.rag.embeddings import EmbedFunction
from app.services.rag.logging import RAGLogger


# Default test queries covering different intents
DEFAULT_TEST_QUERIES = [
    # Standards/Policy intent
    "What are our naming conventions for variables?",
    "What is our code style guide?",

    # Implementation/Debug intent
    "How does the authentication function work?",
    "Where is the error handling for API requests?",

    # Process intent
    "What is our deployment process?",
    "How do we handle incidents?",

    # General intent
    "Tell me about this repository",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Smoke test for RAG pipeline evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default test queries
  factgap-eval-smoke --user-id <uuid>

  # Run with custom queries
  factgap-eval-smoke --user-id <uuid> --query "How does X work?"

  # Run with specific repo context
  factgap-eval-smoke --user-id <uuid> --repo "owner/repo" --query "Where is the auth code?"

  # Verbose output
  factgap-eval-smoke --user-id <uuid> --verbose
""",
    )

    parser.add_argument(
        "--user-id",
        required=True,
        help="User ID for scoped retrieval",
    )

    parser.add_argument(
        "--repo",
        help="Repository (owner/repo) to filter by",
    )

    parser.add_argument(
        "--pr-number",
        type=int,
        help="PR number to include PR overlay",
    )

    parser.add_argument(
        "--head-sha",
        help="Head SHA for PR context",
    )

    parser.add_argument(
        "--query", "-q",
        action="append",
        dest="queries",
        help="Custom query to test (can be specified multiple times)",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="Number of final results (default: 8)",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    return parser.parse_args()


async def run_eval(
    retriever: ScopedRetriever,
    reranker: Reranker,
    rag_log: RAGLogger,
    query: str,
    user_id: str,
    repo: str | None = None,
    pr_number: int | None = None,
    head_sha: str | None = None,
    top_k: int = 8,
) -> dict:
    """Run a single eval query and return results"""
    start_time = time.time()

    # Retrieve candidates
    candidates, intent_result, retrieval_stats = await retriever.retrieve(
        query=query,
        user_id=user_id,
        repo=repo,
        pr_number=pr_number,
        head_sha=head_sha,
        top_k=40,
    )

    # Rerank
    rerank_result = await reranker.rerank(
        query=query,
        candidates=candidates,
        top_k=top_k,
        head_sha=head_sha,
    )

    latency_ms = (time.time() - start_time) * 1000

    # Log
    log_entry = rag_log.log_retrieval(
        query=query,
        intent_result=intent_result,
        retrieval_stats=retrieval_stats,
        rerank_result=rerank_result,
        latency_ms=latency_ms,
    )

    chunk_entries = rag_log.log_chunks(
        chunks=rerank_result.chunks,
        rerank_scores=rerank_result.rerank_scores,
        rerank_reasons=rerank_result.rerank_reasons,
    )

    return {
        "query": query,
        "intent": intent_result.intent.value,
        "intent_confidence": intent_result.confidence,
        "matched_keywords": list(intent_result.matched_keywords),
        "retrieval_stats": retrieval_stats,
        "rerank_method": rerank_result.method,
        "rerank_stats": rerank_result.stats,
        "final_count": len(rerank_result.chunks),
        "latency_ms": latency_ms,
        "log_entry": log_entry,
        "chunk_entries": chunk_entries,
        "chunks": [
            {
                "source_type": c.source_type,
                "doc_key": c.doc_key,
                "weighted_score": c.weighted_score,
            }
            for c in rerank_result.chunks
        ],
    }


def print_result(result: dict, verbose: bool = False):
    """Print a single result in human-readable format"""
    print("=" * 70)
    print(f"Query: {result['query']}")
    print(f"Intent: {result['intent']} (confidence: {result['intent_confidence']:.2f})")
    if result['matched_keywords']:
        print(f"Matched: {', '.join(result['matched_keywords'])}")
    print(f"Latency: {result['latency_ms']:.0f}ms")
    print("-" * 70)

    stats = result['retrieval_stats']
    print(f"Candidates: {stats.get('total_candidates', 0)} total → {stats.get('merged_candidates', 0)} merged → {result['final_count']} final")
    print(f"Rerank method: {result['rerank_method']}")

    # Source distribution
    source_counts = {}
    for chunk in result['chunks']:
        st = chunk['source_type']
        source_counts[st] = source_counts.get(st, 0) + 1
    print(f"Sources: {source_counts}")

    if verbose:
        print("-" * 70)
        print("Top chunks:")
        for i, chunk in enumerate(result['chunks'][:10]):
            print(f"  [{i+1}] {chunk['source_type']:10} | {chunk['doc_key'][:50]:50} | score={chunk['weighted_score']:.3f}")

    print()


def main():
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Check environment
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not all([supabase_url, supabase_key, openai_key]):
        print("Error: Missing environment variables", file=sys.stderr)
        print("Required: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENAI_API_KEY", file=sys.stderr)
        sys.exit(1)

    # Type narrowing after validation
    assert supabase_url is not None
    assert supabase_key is not None
    assert openai_key is not None

    # Initialize clients
    supabase = create_client(supabase_url, supabase_key)
    openai_client = OpenAI(api_key=openai_key)

    # Initialize RAG components
    embed_fn = EmbedFunction(openai_client)
    retriever = ScopedRetriever(supabase, embed_fn.embed)
    reranker = Reranker(openai_client)
    rag_log = RAGLogger(log_level="DEBUG" if args.verbose else "INFO")

    # Get queries
    queries = args.queries if args.queries else DEFAULT_TEST_QUERIES

    print(f"\n🔍 Running RAG eval with {len(queries)} queries\n")
    print(f"User ID: {args.user_id}")
    if args.repo:
        print(f"Repo: {args.repo}")
    if args.pr_number:
        print(f"PR: #{args.pr_number}")
    print()

    # Run queries
    results = []

    async def run_all():
        for query in queries:
            result = await run_eval(
                retriever=retriever,
                reranker=reranker,
                rag_log=rag_log,
                query=query,
                user_id=args.user_id,
                repo=args.repo,
                pr_number=args.pr_number,
                head_sha=args.head_sha,
                top_k=args.top_k,
            )
            results.append(result)

            if not args.json:
                print_result(result, verbose=args.verbose)

    asyncio.run(run_all())

    # JSON output
    if args.json:
        import json
        # Remove non-serializable log entries
        for r in results:
            r.pop("log_entry", None)
            r.pop("chunk_entries", None)
        print(json.dumps(results, indent=2))
    else:
        # Summary
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)

        total_latency = sum(r["latency_ms"] for r in results)
        avg_latency = total_latency / len(results)

        intent_counts = {}
        for r in results:
            intent = r["intent"]
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

        print(f"Total queries: {len(results)}")
        print(f"Avg latency: {avg_latency:.0f}ms")
        print(f"Intent distribution: {intent_counts}")

        # Check diversity
        low_diversity = 0
        for r in results:
            source_types = set(c["source_type"] for c in r["chunks"])
            if len(source_types) < 2:
                low_diversity += 1

        if low_diversity > 0:
            print(f"⚠️  Low diversity warnings: {low_diversity}/{len(results)}")
        else:
            print("✓ All queries have diverse sources")


if __name__ == "__main__":
    main()
