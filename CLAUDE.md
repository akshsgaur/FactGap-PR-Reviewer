# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

FactGap PR Reviewer is an intelligent GitHub PR analysis and chat system that uses RAG (Retrieval-Augmented Generation) over multiple context sources. It enforces a "Fact Gap" philosophy: hard claims must be backed by citations with evidence.

## Quick Commands

```bash
# Install
pip install -e .            # Production
pip install -e ".[dev]"     # Development with test/lint tools

# Test
pytest                      # Run all tests
pytest tests/test_chunking.py  # Run specific test

# Code Quality
black factgap/ tests/       # Format
ruff check factgap/ tests/  # Lint
mypy factgap/               # Type check

# Run locally
factgap-mcp                 # Start MCP server
factgap-pr-analyze          # Run PR analysis (needs env vars)
factgap-pr-chat             # Run PR chat (needs env vars)
```

## Architecture

```
GitHub Actions → CLI (factgap/cli/) → MCP Server → Supabase (pgvector)
                                          ↓
                                    OpenAI Embeddings
```

**Key components:**
- `factgap/cli/` - Entry points: mcp.py, pr_analyze.py, pr_chat.py
- `factgap/mcp_server/server.py` - FastMCP server with 8 tools
- `factgap/reviewer/analyzer.py` - PRAnalyzer orchestrates analysis
- `factgap/db/supabase_client.py` - SupabaseManager for vector storage
- `factgap/chunking/splitters.py` - LangChain-based code chunkers
- `factgap/notion/client.py` - Notion API integration

## Key Patterns

### Fact Gap Rules
- Hard claims (using "must", "violates", "policy") require citations
- Repo citations: `path:line-line @ sha`
- Notion citations: `url (edited: timestamp)`

### MCP Tools
Indexing: `pr_index_build`, `repo_docs_build`, `notion_index`
Searching: `pr_index_search`, `repo_docs_search`, `notion_search`
Utility: `snippet_get_repo`, `snippet_get_notion`, `review_verify_citations`, `redact`

### Database
- Table: `rag_chunks` with pgvector embeddings (1536 dimensions)
- Content hashing for idempotent upserts
- Function: `match_chunks` for vector similarity search

### Chunking Sizes
- Code: 1200 chars, 150 overlap
- Diff: 800 chars, 100 overlap
- Docs: 1000 chars, 150 overlap

## Environment Variables

Required in `.env`:
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `OPENAI_API_KEY`
- `NOTION_TOKEN`, `NOTION_PAGE_IDS`
- `GITHUB_TOKEN`, `GITHUB_REPOSITORY`, `GITHUB_PR_NUMBER` (for CLI)

## Code Style

- Python 3.9+
- Line length: 88 (black/ruff)
- Type hints required (mypy strict)
- Pydantic v2 for data validation
