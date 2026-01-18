#!/usr/bin/env python3
"""Check what data exists in rag_chunks"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(supabase_url, supabase_key)

# Count total chunks
result = supabase.table("rag_chunks").select("id", count="exact").limit(1).execute()
print(f"Total chunks: {result.count}")

# Get sample of source types
result = supabase.table("rag_chunks").select("source_type, repo").limit(20).execute()

if result.data:
    print("\nSample data:")
    source_types = set()
    repos = set()
    for row in result.data:
        source_types.add(row.get("source_type"))
        repos.add(row.get("repo"))

    print(f"Source types: {source_types}")
    print(f"Repos: {repos}")

    # Show first chunk content
    print("\nFirst chunk preview:")
    sample = supabase.table("rag_chunks").select("content, source_type, repo, path").limit(1).execute()
    if sample.data:
        chunk = sample.data[0]
        print(f"  Type: {chunk.get('source_type')}")
        print(f"  Repo: {chunk.get('repo')}")
        print(f"  Path: {chunk.get('path')}")
        print(f"  Content: {chunk.get('content', '')[:200]}...")
else:
    print("\nNo data found in rag_chunks table!")
