#!/usr/bin/env python3
"""Debug version of PR chat with full data flow tracing"""

import os
import sys
import asyncio
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from factgap.cli.pr_chat import PRChat

def print_separator(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

async def debug_pr_chat():
    """Debug PR chat with full data flow tracing"""
    print_separator("DEBUG PR CHAT")
    
    # Get environment variables
    pr_number = int(os.getenv("GITHUB_PR_NUMBER", "0"))
    repo_root = os.getenv("GITHUB_WORKSPACE", ".")
    comment_id = os.getenv("GITHUB_COMMENT_ID", "")
    
    print(f"🔧 ENVIRONMENT:")
    print(f"   PR Number: {pr_number}")
    print(f"   Repo Root: {repo_root}")
    print(f"   Comment ID: {comment_id}")
    
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
                
                # Create chat handler
                print(f"\n💬 CREATING PR CHAT")
                chat = PRChat(session)
                print(f"   Chat handler created")
                
                # Get comment context
                print(f"\n📝 GETTING COMMENT CONTEXT")
                if comment_id:
                    print(f"   Processing comment ID: {comment_id}")
                    # In a real scenario, you'd fetch the specific comment
                    comment_body = "How does this authentication flow work?"  # Example question
                    print(f"   Comment body: {comment_body}")
                else:
                    print("   No specific comment ID, using default question")
                    comment_body = "How does authentication work in this system?"
                
                # Process the question
                print(f"\n🤖 PROCESSING QUESTION")
                print(f"   Question: {comment_body}")
                
                # Generate response
                print(f"\n📊 GENERATING RESPONSE")
                response = await chat.answer_question(comment_body, pr_number, repo_root)
                
                print(f"\n💬 RESPONSE RESULTS:")
                if isinstance(response, dict):
                    print(f"   Response type: {type(response)}")
                    print(f"   Keys: {list(response.keys())}")
                    
                    if 'answer' in response:
                        answer = response['answer']
                        print(f"   Answer length: {len(answer)} chars")
                        preview = answer[:300].replace('\n', '\n   ')
                        print(f"   Answer preview: {preview}...")
                        
                        # Check for citations
                        if 'citations' in response:
                            citations = response['citations']
                            print(f"   Citations: {len(citations)}")
                            for i, citation in enumerate(citations[:3], 1):
                                print(f"   [{i}] {citation}")
                        
                        # Check for sources used
                        if 'sources_used' in response:
                            sources = response['sources_used']
                            print(f"   Sources used: {sources}")
                    
                    # Check for metadata
                    if 'metadata' in response:
                        metadata = response['metadata']
                        print(f"   Metadata: {metadata}")
                
                # Post response to GitHub
                print(f"\n📤 POSTING RESPONSE TO GITHUB")
                from factgap.reviewer.github_api import GitHubClient
                
                github_client = GitHubClient()
                
                # In debug mode, don't actually post
                debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
                if debug_mode:
                    print(f"   🐛 DEBUG MODE: Would post response")
                    if 'answer' in response:
                        answer = response['answer'][:200]
                        print(f"   Response preview: {answer}...")
                else:
                    # Post the response
                    if 'answer' in response:
                        comment_body = response['answer']
                        github_client.create_comment_reply(
                            comment_id,
                            comment_body
                        )
                        print(f"   ✅ Reply posted successfully")
                    else:
                        print(f"   ❌ No answer to post")
                
                print(f"\n🎉 PR CHAT COMPLETED")
                
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_pr_chat())
