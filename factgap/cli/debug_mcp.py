#!/usr/bin/env python3
"""Debug version of MCP server with full data flow tracing"""

import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)

def print_separator(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

# Import the actual server functions with debug wrappers
import factgap.mcp_server.server as mcp_server

# Monkey-patch the server functions to add debug output
original_pr_index_build = mcp_server.pr_index_build
original_repo_docs_build = mcp_server.repo_docs_build

async def debug_pr_index_build(request):
    """Debug version of pr_index_build with full tracing"""
    print_separator("DEBUG PR INDEX BUILD")
    print(f"📥 REQUEST:")
    print(f"   PR Number: {request.pr_number}")
    print(f"   Head SHA: {request.head_sha}")
    print(f"   Diff length: {len(request.diff_text)} chars")
    print(f"   Changed files: {len(request.changed_files)}")
    
    # Show first few files
    for i, file_info in enumerate(request.changed_files[:3], 1):
        print(f"   [{i}] {file_info.get('path', 'unknown')}")
    
    print(f"\n🔧 BUILDING INDEX...")
    result = await original_pr_index_build(request)
    
    print(f"\n📊 RESULTS:")
    if isinstance(result, dict):
        print(f"   Upserted: {result.get('upserted_count', 0)}")
        print(f"   Skipped: {result.get('skipped_count', 0)}")
        print(f"   Stats: {result.get('stats', {})}")
    
    return result

async def debug_repo_docs_build(repo_root: str):
    """Debug version of repo_docs_build with full tracing"""
    print_separator("DEBUG REPO DOCS BUILD")
    print(f"📁 REPO ROOT: {repo_root}")
    
    print(f"\n🔧 BUILDING DOCUMENTATION INDEX...")
    result = await original_repo_docs_build(repo_root)
    
    print(f"\n📊 RESULTS:")
    if isinstance(result, dict):
        print(f"   Upserted: {result.get('upserted_count', 0)}")
        print(f"   Skipped: {result.get('skipped_count', 0)}")
        print(f"   Stats: {result.get('stats', {})}")
    
    return result

# Replace the original functions with debug versions
mcp_server.pr_index_build = debug_pr_index_build
mcp_server.repo_docs_build = debug_repo_docs_build

async def main():
    """Debug MCP server with enhanced logging"""
    print_separator("DEBUG MCP SERVER")
    print(f"🚀 Starting debug MCP server...")
    
    # Enable debug logging
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run the actual server
    await stdio_server(main)

if __name__ == "__main__":
    asyncio.run(main())
