"""CLI entrypoint for PR chat"""

import os
import sys
import logging
import json
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from factgap.reviewer.github_api import GitHubClient
from factgap.reviewer.analyzer import PRAnalyzer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Run PR chat handler"""
    try:
        # Get environment variables
        pr_number = int(os.getenv("GITHUB_PR_NUMBER", "0"))
        repo_root = os.getenv("GITHUB_WORKSPACE", ".")
        
        # Get comment payload from stdin (GitHub webhook)
        comment_data = json.loads(sys.stdin.read())
        
        if not pr_number:
            logger.error("GITHUB_PR_NUMBER environment variable is required")
            sys.exit(1)
        
        # Extract comment info
        comment_body = comment_data.get("comment", {}).get("body", "")
        comment_id = comment_data.get("comment", {}).get("id")
        
        # Parse @code-reviewer mention
        github_client = GitHubClient()
        question = github_client.parse_comment_mention(comment_body)
        
        if not question:
            logger.info("No @code-reviewer mention found, skipping")
            return
        
        # Connect to MCP server
        server_params = {
            "command": sys.executable,
            "args": ["-m", "factgap.cli.mcp"],
        }
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # Create analyzer
                analyzer = PRAnalyzer(session)
                
                # Generate answer
                logger.info(f"Processing chat question for PR #{pr_number}")
                answer = await analyzer.handle_chat(pr_number, question, repo_root)
                
                # Post reply to GitHub
                reply_body = f"@code-reviewer says:\n\n{answer}"
                
                github_client.reply_to_comment(
                    pr_number,
                    comment_id,
                    reply_body
                )
                
                logger.info(f"Chat reply posted for PR #{pr_number}")
                
    except Exception as e:
        logger.error(f"PR chat failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
