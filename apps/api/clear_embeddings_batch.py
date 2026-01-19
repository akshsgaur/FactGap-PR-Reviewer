#!/usr/bin/env python3
"""Batch delete embeddings from Supabase to avoid timeouts."""

import os
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from app.database import get_db
from app.config import get_settings


def batch_delete_embeddings(batch_size=1000, delay=1.0):
    """Delete embeddings in batches to avoid timeouts."""
    settings = get_settings()
    db = get_db()
    
    print("⚠️  WARNING: This will delete ALL embeddings in the rag_chunks table!")
    print(f"   Supabase URL: {settings.supabase_url}")
    print(f"   Batch size: {batch_size}")
    print(f"   Delay between batches: {delay}s")
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
    
    print("\n🗑️  Deleting embeddings in batches...")
    
    deleted_total = 0
    batch_num = 0
    
    while deleted_total < total_count:
        batch_num += 1
        print(f"\n📦 Batch {batch_num}: Deleting up to {batch_size} embeddings...")
        
        try:
            # Delete a batch using a simple filter
            # We'll delete by any valid filter that matches all rows
            delete_result = db.client.table('rag_chunks').delete().gte('created_at', '1970-01-01').limit(batch_size).execute()
            
            # Count how many were deleted by checking remaining count
            count_result = db.client.table('rag_chunks').select('id', count='exact').execute()
            remaining = count_result.count if count_result.count else 0
            batch_deleted = total_count - deleted_total - remaining
            
            if batch_deleted <= 0:
                print("   🏁 No more embeddings to delete")
                break
            
            deleted_total += batch_deleted
            print(f"   ✅ Deleted {batch_deleted} embeddings (total: {deleted_total})")
            
            # Check if we're done
            if remaining == 0:
                print("   🏁 All embeddings deleted")
                break
            
            # Delay to avoid overwhelming the database
            if delay > 0:
                time.sleep(delay)
                
        except Exception as e:
            print(f"   ❌ Error in batch {batch_num}: {e}")
            break
    
    # Verify final count
    try:
        count_result = db.client.table('rag_chunks').select('id', count='exact').execute()
        remaining = count_result.count if count_result.count else 0
        
        print(f"\n📊 FINAL RESULTS:")
        print(f"   Total deleted: {deleted_total}")
        print(f"   Remaining: {remaining}")
        
        if remaining == 0:
            print("🎉 All embeddings cleared successfully!")
        else:
            print(f"⚠️  {remaining} embeddings remain")
            
    except Exception as e:
        print(f"❌ Error verifying final count: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Batch delete embeddings from Supabase')
    parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for deletion')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay between batches (seconds)')
    
    args = parser.parse_args()
    
    batch_delete_embeddings(batch_size=args.batch_size, delay=args.delay)
