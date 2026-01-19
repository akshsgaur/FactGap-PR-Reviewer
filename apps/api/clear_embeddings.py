#!/usr/bin/env python3
"""Clear all embeddings from Supabase rag_chunks table."""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from app.database import get_db
from app.config import get_settings


def clear_embeddings():
    """Clear all embeddings from rag_chunks table."""
    settings = get_settings()
    db = get_db()
    
    print("⚠️  WARNING: This will delete ALL embeddings in the rag_chunks table!")
    print(f"   Supabase URL: {settings.supabase_url}")
    print()
    
    # First, count current rows
    try:
        count_result = db.client.table('rag_chunks').select('id', count='exact').execute()
        total_count = count_result.count if count_result.count else 0
        print(f"📊 Current embeddings count: {total_count}")
    except Exception as e:
        print(f"❌ Error counting embeddings: {e}")
        return
    
    if total_count == 0:
        print("✅ No embeddings to delete")
        return
    
    # Confirm deletion
    confirm = input(f"\n❓ Are you sure you want to delete all {total_count} embeddings? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ Cancelled")
        return
    
    print("\n🗑️  Deleting all embeddings...")
    
    try:
        # Delete all rows using a filter that matches everything
        delete_result = db.client.table('rag_chunks').delete().gte('id', '00000000-0000-0000-0000-000000000000').execute()
        
        # Verify deletion
        count_result = db.client.table('rag_chunks').select('id', count='exact').execute()
        remaining = count_result.count if count_result.count else 0
        
        print(f"✅ Deleted {total_count - remaining} embeddings")
        print(f"📊 Remaining embeddings: {remaining}")
        
        if remaining > 0:
            print("⚠️  Some embeddings remain")
        else:
            print("🎉 All embeddings cleared successfully!")
            
    except Exception as e:
        print(f"❌ Error deleting embeddings: {e}")
        # Fallback: try using raw SQL
        try:
            print("🔄 Trying direct SQL deletion...")
            import psycopg2
            from urllib.parse import urlparse
            
            # Parse Supabase URL
            parsed = urlparse(settings.supabase_url)
            dbname = parsed.path[1:]  # Remove leading slash
            
            # Connect directly
            conn = psycopg2.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                database=dbname,
                user='postgres',
                password=settings.supabase_service_role_key
            )
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rag_chunks")
            deleted = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()
            
            print(f"✅ Deleted {deleted} embeddings via direct SQL")
        except Exception as e2:
            print(f"❌ Fallback also failed: {e2}")


if __name__ == "__main__":
    clear_embeddings()
