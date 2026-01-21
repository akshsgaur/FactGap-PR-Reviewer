#!/usr/bin/env python3
"""Clean up user dependencies and test RAG functionality"""

import os
import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.database import get_db
from app.config import get_settings

def print_separator(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

async def cleanup_user_data():
    """Clean up user-related data and dependencies"""
    print_separator("CLEANING USER DATA")
    
    settings = get_settings()
    db = get_db()
    
    try:
        # 1. Delete all user-scoped chunks
        print("🗑️  Clearing user-scoped embeddings...")
        
        # Delete all user-scoped chunks (Notion pages, user-specific data)
        delete_result = db.client.table('rag_chunks').delete().not_eq('user_id', '00000000-0000-0000-0000-000000000001').execute()
        
        if delete_result.data:
            deleted_count = len(delete_result.data)
            print(f"   ✅ Deleted {deleted_count} user-scoped chunks")
        else:
            print("   ℹ️  No user-scoped chunks found")
        
        # 2. Clear user-related tables if they exist
        tables_to_check = ['users', 'user_repos', 'user_sessions']
        
        for table in tables_to_check:
            try:
                count_result = db.client.table(table).select('id', count='exact').execute()
                count = count_result.count if count_result.count else 0
                
                if count > 0:
                    print(f"   🗑️  Clearing {table} table ({count} records)...")
                    db.client.table(table).delete().ne('user_id', '00000000-0000-0000-0000-000000000001').execute()
                    print(f"   ✅ Deleted {table} table")
                else:
                    print(f"   ℹ️  {table} table is empty")
                    
            except Exception as e:
                print(f"   ❌ Error clearing {table}: {e}")
        
        # 3. Test RAG functionality after cleanup
        print("\n🧪 TESTING RAG AFTER CLEANUP")
        
        # Test with a simple query
        from app.services.rag import ScopedRetriever, EmbedFunction, Reranker
        import openai
        
        openai_client = openai.OpenAI(api_key=settings.openai_api_key)
        embed_fn = EmbedFunction(openai_client)
        retriever = ScopedRetriever(db.client, embed_fn.embed)
        
        test_query = "How does authentication work?"
        print(f"   📝 Test query: {test_query}")
        
        # Embed query
        query_embedding = embed_fn.embed(test_query)
        print(f"   ✅ Query embedded (dimensions: {len(query_embedding)})")
        
        # Test retrieval
        candidates, intent_result, stats = await retriever.retrieve(
            query=test_query,
            user_id="test-user-12345",  # Use test user ID
            repo="factgap-pr-reviewer",
            top_k=5,
        )
        
        print(f"   🔍 Retrieved {len(candidates)} candidates")
        print(f"   🎯 Intent: {intent_result.intent} (confidence: {intent_result.confidence})")
        
        if candidates:
            print(f"   📋 Top 3 candidates:")
            for i, candidate in enumerate(candidates[:3], 1):
                score = candidate.get('score', 0)
                source_type = candidate.get('source_type', 'unknown')
                path = candidate.get('path', 'N/A')
                print(f"   [{i}] {source_type:9} | {path:35} | {score:.3f}")
        
        # Test reranking
        reranker = Reranker(openai_client)
        rerank_result = await reranker.rerank(
            query=test_query,
            candidates=candidates,
            top_k=3,
        )
        
        print(f"   🔄 Reranked to {len(rerank_result.chunks)} chunks")
        print(f"   📊 Method: {rerank_result.method}")
        
        if rerank_result.chunks:
            print(f"   📋 Top 3 reranked chunks:")
            for i, chunk in enumerate(rerank_result.chunks[:3], 1):
                score = chunk.get('score', 0)
                source_type = chunk.get('source_type', 'unknown')
                path = chunk.get('path', 'N/A')
                print(f"   [{i}] {source_type:9} | {path:35} | {score:.3f}")
        
        print("\n✅ RAG functionality test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ ERROR during cleanup: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(cleanup_user_data())
