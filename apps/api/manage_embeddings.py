#!/usr/bin/env python3
"""Simple script to check and clear embeddings using SQL RPC."""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from app.database import get_db
from app.config import get_settings


def check_embeddings():
    """Check current embeddings count."""
    settings = get_settings()
    db = get_db()
    
    try:
        count_result = db.client.table('rag_chunks').select('id', count='exact').execute()
        total_count = count_result.count if count_result.count else 0
        print(f"📊 Current embeddings count: {total_count}")
        return total_count
    except Exception as e:
        print(f"❌ Error counting embeddings: {e}")
        return 0


def clear_all_embeddings():
    """Clear all embeddings using a simple approach."""
    settings = get_settings()
    db = get_db()
    
    print("⚠️  WARNING: This will delete ALL embeddings!")
    print(f"   Supabase URL: {settings.supabase_url}")
    
    count = check_embeddings()
    if count == 0:
        print("✅ No embeddings to delete")
        return
    
    confirm = input(f"\n❓ Delete all {count} embeddings? (yes/no): ")
    if confirm.lower() != 'yes':
        print("❌ Cancelled")
        return
    
    print("\n🗑️  Deleting all embeddings...")
    
    try:
        # Try using a range filter on created_at
        result = db.client.table('rag_chunks').delete().gte('created_at', '1970-01-01T00:00:00Z').execute()
        print("✅ Delete command sent")
        
        # Check remaining
        import time
        time.sleep(2)
        remaining = check_embeddings()
        
        if remaining == 0:
            print("🎉 All embeddings cleared!")
        else:
            print(f"⚠️  {remaining} embeddings remain")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n💡 You may need to clear embeddings manually via Supabase SQL editor:")
        print("   SQL: DELETE FROM rag_chunks WHERE 1=1;")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Manage embeddings in Supabase')
    parser.add_argument('--check', action='store_true', help='Only check count, do not delete')
    parser.add_argument('--clear', action='store_true', help='Clear all embeddings')
    
    args = parser.parse_args()
    
    if args.check:
        check_embeddings()
    elif args.clear:
        clear_all_embeddings()
    else:
        print("Use --check to count or --clear to delete embeddings")
