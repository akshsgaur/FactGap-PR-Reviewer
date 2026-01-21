#!/usr/bin/env python3
"""Simple cleanup script using actual table structure"""

import os
import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.database import get_db

def print_separator(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

async def cleanup_user_data():
    """Clean up user-related data and dependencies"""
    print_separator("CLEANING USER DATA")
    
    db = get_db()
    
    try:
        # 1. Clear source_id based embeddings (Notion pages, user-specific data)
        print("🗑️  Clearing source_id-scoped embeddings...")
        
        # Delete all source_id-scoped chunks (Notion pages, user-specific data)
        delete_result = db.client.table('rag_chunks').delete().ne('source_id', '00000000-0000-0000-0000-000000001').execute()
        
        if delete_result.data:
            deleted_count = len(delete_result.data)
            print(f"   ✅ Deleted {deleted_count} source_id-scoped chunks")
        else:
            print("   ℹ️  No source_id-scoped chunks found")
        
        # 2. Test RAG functionality after cleanup
        print("\n🧪 TESTING RAG AFTER CLEANUP")
        
        # Test with a simple query using existing data
        from app.services.rag import ScopedRetriever, EmbedFunction, Reranker
        import openai
        
        openai_client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        embed_fn = EmbedFunction(openai_client)
        retriever = ScopedRetriever(db.client, embed_fn.embed)
        
        test_query = "How does authentication work?"
        print(f"   📝 Test query: {test_query}")
        
        # Embed query
        query_embedding = embed_fn.embed(test_query)
        print(f"   ✅ Query embedded (dimensions: {len(query_embedding)})")
        
        # Test retrieval without user_id (should find repo docs)
        candidates, intent_result, stats = await retriever.retrieve(
            query=test_query,
            user_id=None,  # No user filtering
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
        
        print("\n✅ RAG functionality test completed successfully!")
        
    except Exception as e:
        print(f"\n❌ ERROR during cleanup: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(cleanup_user_data())
