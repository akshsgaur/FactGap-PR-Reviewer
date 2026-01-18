"""MCP server CLI entrypoint"""

import sys
import logging
from factgap.mcp_server.server import mcp

def main():
    """Run the MCP server"""
    # Configure logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    
    # Run the MCP server
    mcp.run()

if __name__ == "__main__":
    main()
