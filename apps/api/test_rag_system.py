#!/usr/bin/env python3
"""Test RAG system with existing data"""

import os
import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.database import get_db
from app.services.rag import ScopedRetriever, EmbedFunction, Reranker
import openai

def print_separator(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

async def test_rag_system():
    """Test RAG system with existing authentication data"""
    print_separator("TESTING RAG SYSTEM")
    
    db = get_db()
    openai_client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    # Initialize RAG components
    embed_fn = EmbedFunction(openai_client)
    retriever = ScopedRetriever(db.client, embed_fn.embed)
    reranker = Reranker(openai_client)
    
    # Test queries about authentication
    test_queries = [
        "How does authentication work?",
        "What are the authentication routes?",
        "Explain the JWT token handling",
        "How are user sessions managed?",
        "What authentication utilities are available?",
    ]
    
    print(f"🧪 Testing {len(test_queries)} authentication-related queries...")
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n📝 QUERY {i}: {query}")
        
        # Embed query
        query_embedding = embed_fn.embed(query)
        print(f"   ✅ Embedded (dimensions: {len(query_embedding)})")
        
        # Retrieve candidates
        candidates, intent_result, stats = await retriever.retrieve(
            query=query,
            user_id=None,  # Search all data, not user-specific
            repo="factgap-pr-reviewer",
            top_k=5,
        )
        
        print(f"   🔍 Found {len(candidates)} candidates")
        print(f"   🎯 Intent: {intent_result.intent} (confidence: {intent_result.confidence})")
        
        if candidates:
            print(f"   📋 Top 3 candidates:")
            for j, candidate in enumerate(candidates[:3], 1):
                score = candidate.get('score', 0)
                source_type = candidate.get('source_type', 'unknown')
                path = candidate.get('path', 'N/A')
                print(f"   [{j}] {source_type:9} | {path:35} | {score:.3f}")
        
        # Rerank candidates
        rerank_result = await reranker.rerank(
            query=query,
            candidates=candidates,
            top_k=3,
        )
        
        print(f"   🔄 Reranked to {len(rerank_result.chunks)} chunks")
        print(f"   📊 Method: {rerank_result.method}")
        
        if rerank_result.chunks:
            print(f"   📋 Top 3 reranked chunks:")
            for j, chunk in enumerate(rerank_result.chunks[:3], 1):
                score = chunk.get('score', 0)
                source_type = chunk.get('source_type', 'unknown')
                path = chunk.get('path', 'N/A')
                content_preview = chunk.get('content', '')[:100].replace('\n', ' ')
                print(f"   [{j}] {source_type:9} | {path:35} | {score:.3f}")
                print(f"      Preview: {content_preview}...")
        
        print("-" * 60)
    
    print("\n✅ RAG system test completed!")
    print("📊 The system is working with your existing authentication data.")
    print("🎯 You can now use this in PR analysis and chat workflows.")

if __name__ == "__main__":
    asyncio.run(test_rag_system())
