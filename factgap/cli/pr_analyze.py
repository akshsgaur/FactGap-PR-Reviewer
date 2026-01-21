"""CLI entrypoint for PR analysis"""

import os
import sys
import logging
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
    """Run PR analysis"""
    try:
        # Get environment variables
        pr_number = int(os.getenv("GITHUB_PR_NUMBER", "0"))
        repo_root = os.getenv("GITHUB_WORKSPACE", ".")
        
        if not pr_number:
            logger.error("GITHUB_PR_NUMBER environment variable is required")
            sys.exit(1)
        
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
                
                # Generate PR analysis
                logger.info(f"Analyzing PR #{pr_number}")
                analysis = await analyzer.analyze_pr(pr_number, repo_root)
                
                # Post comment to GitHub
                github_client = GitHubClient()
                marker = "<!-- FACTGAP_PR_ANALYSIS -->"
                comment_body = f"{marker}\n\n{analysis}"
                
                github_client.create_or_update_comment(
                    pr_number,
                    comment_body,
                    marker
                )
                
                logger.info(f"PR analysis completed for #{pr_number}")
                
    except Exception as e:
        logger.error(f"PR analysis failed: {e}")
        sys.exit(1)


def cli():
    """Sync wrapper for CLI entry point"""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    cli()
