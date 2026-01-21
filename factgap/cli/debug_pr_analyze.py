#!/usr/bin/env python3
"""Debug version of PR analysis with full data flow tracing"""

import os
import sys
import asyncio
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from factgap.cli.pr_analyze import PRAnalyzer
from factgap.cli.mcp import create_mcp_server

def print_separator(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

async def debug_pr_analysis():
    """Debug PR analysis with full data flow tracing"""
    print_separator("DEBUG PR ANALYSIS")
    
    # Get environment variables
    pr_number = int(os.getenv("GITHUB_PR_NUMBER", "0"))
    repo_root = os.getenv("GITHUB_WORKSPACE", ".")
    
    print(f"🔧 ENVIRONMENT:")
    print(f"   PR Number: {pr_number}")
    print(f"   Repo Root: {repo_root}")
    
    if not pr_number:
        print("❌ ERROR: GITHUB_PR_NUMBER environment variable is required")
        sys.exit(1)
    
    # Connect to MCP server
    print(f"\n🔗 CONNECTING TO MCP SERVER")
    server_params = {
        "command": sys.executable,
        "args": ["-m", "factgap.cli.mcp"],
    }
    print(f"   Server command: {server_params['command']}")
    print(f"   Server args: {server_params['args']}")
    
    try:
        from mcp import stdio_client, ClientSession
        
        async with stdio_client(server_params) as (read, write):
            print(f"✅ MCP Server connected")
            
            async with ClientSession(read, write) as session:
                print(f"🔧 INITIALIZING SESSION")
                await session.initialize()
                print(f"   Session initialized")
                
                # Create analyzer
                print(f"\n🤖 CREATING PR ANALYZER")
                analyzer = PRAnalyzer(session)
                print(f"   Analyzer created")
                
                # Generate PR analysis
                print(f"\n📊 GENERATING PR ANALYSIS")
                print(f"   Analyzing PR #{pr_number}")
                print(f"   Repo root: {repo_root}")
                
                analysis = await analyzer.analyze_pr(pr_number, repo_root)
                
                print(f"\n📋 ANALYSIS RESULTS:")
                if isinstance(analysis, dict):
                    print(f"   Type: {type(analysis)}")
                    print(f"   Keys: {list(analysis.keys())}")
                    
                    # Try to pretty print the analysis
                    if 'analysis' in analysis:
                        print(f"\n📝 ANALYSIS CONTENT:")
                        analysis_content = analysis['analysis']
                        print(f"   Length: {len(analysis_content)} chars")
                        
                        # Show first 500 chars
                        preview = analysis_content[:500].replace('\n', '\n   ')
                        print(f"   Preview: {preview}...")
                        
                        # Check for citations
                        if 'citations' in analysis:
                            citations = analysis['citations']
                            print(f"\n📚 CITATIONS:")
                            print(f"   Count: {len(citations)}")
                            for i, citation in enumerate(citations[:5], 1):
                                print(f"   [{i}] {citation}")
                        
                        # Check for metadata
                        if 'metadata' in analysis:
                            metadata = analysis['metadata']
                            print(f"\n📊 METADATA:")
                            for key, value in metadata.items():
                                print(f"   {key}: {value}")
                    
                    # Show raw analysis if it's a string
                    elif isinstance(analysis, str):
                        print(f"   Length: {len(analysis)} chars")
                        preview = analysis[:500].replace('\n', '\n   ')
                        print(f"   Content: {preview}...")
                else:
                    print(f"   Unexpected type: {type(analysis)}")
                
                # Post to GitHub
                print(f"\n📤 POSTING TO GITHUB")
                from factgap.reviewer.github_api import GitHubClient
                
                github_client = GitHubClient()
                marker = "<!-- FACTGAP_PR_ANALYSIS -->"
                comment_body = f"{marker}\n\n{analysis}"
                
                print(f"   Comment marker: {marker}")
                print(f"   Comment length: {len(comment_body)} chars")
                
                # In debug mode, don't actually post
                debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
                if debug_mode:
                    print(f"   🐛 DEBUG MODE: Would post comment")
                    print(f"   Comment preview: {comment_body[:300]}...")
                else:
                    github_client.create_or_update_comment(
                        pr_number,
                        comment_body,
                        marker
                    )
                    print(f"   ✅ Comment posted successfully")
                
                print(f"\n🎉 PR ANALYSIS COMPLETED")
                
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_pr_analysis())
