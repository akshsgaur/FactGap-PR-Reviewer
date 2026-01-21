#!/usr/bin/env python3
"""Debug version of compare_rag.py with full data flow tracing"""

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

def print_separator(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

def get_clients():
    print("🔗 INITIALIZING CLIENTS")
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    print(f"   Supabase URL: {supabase_url}")
    print(f"   OpenAI API Key: {openai_key[:20]}...")
    
    supabase = create_client(supabase_url, supabase_key)
    openai_client = OpenAI(api_key=openai_key)
    return supabase, openai_client

def embed_query(openai_client, query: str) -> List[float]:
    print(f"\n📝 EMBEDDING QUERY")
    print(f"   Query: '{query}'")
    print(f"   Model: text-embedding-3-small")
    
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    )
    
    embedding = response.data[0].embedding
    print(f"   Embedding dimensions: {len(embedding)}")
    print(f"   First 5 values: {embedding[:5]}")
    return embedding

async def old_pipeline_search(supabase, query_embedding, query: str, repo: str = None):
    print_separator("OLD PIPELINE - VECTOR SEARCH")
    
    params = {
        "p_query_embedding": query_embedding,
        "p_k": 8,
        "p_min_score": 0.3,
        "p_repo": repo,
        "p_source_types": ["code", "repo_doc", "notion"],
        "p_filters": {}
    }
    
    print(f"📊 SEARCH PARAMS:")
    print(f"   k: {params['p_k']}")
    print(f"   min_score: {params['p_min_score']}")
    print(f"   repo: {params['p_repo']}")
    print(f"   source_types: {params['p_source_types']}")
    
    start_time = time.time()
    response = supabase.rpc("match_chunks", params).execute()
    latency = (time.time() - start_time) * 1000
    
    results = response.data or []
    print(f"\n⚡ SEARCH RESULTS:")
    print(f"   Latency: {latency:.0f}ms")
    print(f"   Results count: {len(results)}")
    
    return results, latency

async def new_pipeline_search(supabase, openai_client, query_embedding, query: str, repo: str = None):
    print_separator("NEW PIPELINE - INTENT + RETRIEVAL + RERANK")
    
    # Intent Classification
    print(f"\n🎯 INTENT CLASSIFICATION")
    intent_classifier = IntentClassifier()
    intent_result = intent_classifier.classify(query)
    print(f"   Query: '{query}'")
    print(f"   Intent: {intent_result.intent}")
    print(f"   Confidence: {intent_result.confidence}")
    print(f"   Matched keywords: {intent_result.matched_keywords}")
    
    # Scoped Retrieval
    print(f"\n🔍 SCOPED RETRIEVAL")
    from app.services.rag.retrieval import ScopedRetriever
    from app.services.rag.embeddings import EmbedFunction
    
    embed_fn = EmbedFunction(openai_client)
    retriever = ScopedRetriever(supabase, embed_fn.embed)
    
    start_time = time.time()
    candidates, intent_result2, stats = await retriever.retrieve(
        query=query,
        user_id=None,  # No user_id for comparison
        repo=repo,
        pr_number=None,
        head_sha=None,
        top_k=40,
    )
    retrieval_latency = (time.time() - start_time) * 1000
    
    print(f"   Retrieval latency: {retrieval_latency:.0f}ms")
    print(f"   Candidates found: {len(candidates)}")
    print(f"   Stats: {stats}")
    
    # Reranking
    print(f"\n🔄 RERANKING")
    reranker = Reranker(openai_client)
    
    start_time = time.time()
    rerank_result = await reranker.rerank(
        query=query,
        candidates=candidates,
        top_k=8,
    )
    rerank_latency = (time.time() - start_time) * 1000
    
    print(f"   Rerank latency: {rerank_latency:.0f}ms")
    print(f"   Rerank method: {rerank_result.method}")
    print(f"   Final results: {len(rerank_result.chunks)}")
    
    total_latency = retrieval_latency + rerank_latency
    
    return rerank_result.chunks, total_latency, intent_result, rerank_result.method

def format_results(results, title):
    print(f"\n📋 {title}")
    for i, chunk in enumerate(results[:8], 1):
        score = chunk.get('score', 0.0)
        source_type = chunk.get('source_type', 'unknown')
        path = chunk.get('path', 'N/A')
        
        if source_type == 'code':
            language = chunk.get('language', 'unknown')
            info = f"File: {path} Language: {language}"
        else:
            info = f"Doc: {path}"
        
        content_preview = chunk.get('content', '')[:100].replace('\n', ' ')
        print(f"[{i}] {source_type:9} | {path:35} | {score:.3f}")
        print(f"    {info} --- {content_preview}...")

def analyze_results(old_results, new_results):
    print_separator("ANALYSIS")
    
    old_sources = {}
    new_sources = {}
    
    for chunk in old_results:
        source_type = chunk.get('source_type', 'unknown')
        old_sources[source_type] = old_sources.get(source_type, 0) + 1
    
    for chunk in new_results:
        source_type = chunk.get('source_type', 'unknown')
        new_sources[source_type] = new_sources.get(source_type, 0) + 1
    
    print(f"📊 SOURCE DISTRIBUTION:")
    print(f"   OLD: {old_sources}")
    print(f"   NEW: {new_sources}")
    
    old_unique = len(set(chunk.get('path', '') for chunk in old_results))
    new_unique = len(set(chunk.get('path', '') for chunk in new_results))
    
    print(f"\n📈 UNIQUE DOCUMENTS:")
    print(f"   OLD: {old_unique}")
    print(f"   NEW: {new_unique}")

async def main():
    print_separator("DEBUG RAG PIPELINE COMPARISON")
    
    # Parse arguments
    query = "How does authentication work?"  # Default query
    repo = None
    user_id = "test-user-12345"  # Test user ID for demonstration
    
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:]):
            if arg == "-q" and i + 1 < len(sys.argv) - 1:
                query = sys.argv[i + 2]
            elif arg == "--repo" and i + 1 < len(sys.argv) - 1:
                repo = sys.argv[i + 2]
            elif arg == "--user-id" and i + 1 < len(sys.argv) - 1:
                user_id = sys.argv[i + 2]
    
    print(f"🎯 QUERY: {query}")
    if repo:
        print(f"📁 REPO: {repo}")
    
    # Initialize clients
    supabase, openai_client = get_clients()
    
    # Embed query
    query_embedding = embed_query(openai_client, query)
    
    # Run old pipeline
    old_results, old_latency = await old_pipeline_search(supabase, query_embedding, query, repo)
    
    # Run new pipeline
    new_results, new_latency, intent_result, rerank_method = await new_pipeline_search(
        supabase, openai_client, query_embedding, query, repo
    )
    
    # Format results
    format_results(old_results, "OLD PIPELINE RESULTS")
    format_results(new_results, "NEW PIPELINE RESULTS")
    
    # Analysis
    analyze_results(old_results, new_results)
    
    # Performance comparison
    print_separator("PERFORMANCE COMPARISON")
    print(f"   Latency: OLD={old_latency:.0f}ms → NEW={new_latency:.0f}ms")
    print(f"   Results: OLD={len(old_results)} → NEW={len(new_results)}")
    
    if new_latency > old_latency:
        print(f"   ⚠️  NEW is {new_latency/old_latency:.1f}x slower")
    else:
        print(f"   ✅ NEW is {old_latency/new_latency:.1f}x faster")
    
    # Show rerank prompt if available
    if 'rerank_result' in locals() and hasattr(rerank_result, 'prompt') and rerank_result.prompt:
        print_separator("RERANK PROMPT SENT TO OPENAI")
        print(f"   Prompt: {rerank_result.prompt}")
    elif 'rerank_result' in locals():
        print_separator("RERANK RESULTS")
        print(f"   Method: {getattr(rerank_result, 'method', 'unknown')}")
        print(f"   Chunks returned: {len(getattr(rerank_result, 'chunks', []))}")

if __name__ == "__main__":
    asyncio.run(main())
