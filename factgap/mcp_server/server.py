"""FastMCP server for FactGap PR Reviewer - Context Gateway"""

import json
import logging
import os
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from factgap.db.supabase_client import get_supabase_manager, ChunkRecord
from factgap.chunking.splitters import CodeChunker, DiffChunker, DocumentChunker
from factgap.chunking import SemanticChunker, load_config
from factgap.notion.client import NotionClient

# Configure logging to stderr
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create FastMCP server
mcp = FastMCP("factgap-pr-reviewer")


class PRIndexRequest(BaseModel):
    pr_number: int
    head_sha: str
    repo_root: str
    diff_text: str
    changed_files: List[Dict[str, Any]]


class SearchRequest(BaseModel):
    query: str
    k: int = 10
    source_types: Optional[List[str]] = None
    filters: Optional[Dict[str, Any]] = None


class CitationVerifyRequest(BaseModel):
    draft_markdown: str


def get_manager():
    """Get Supabase manager instance"""
    return get_supabase_manager()


def get_notion_client():
    """Get Notion client instance"""
    notion_token = os.getenv("NOTION_TOKEN")
    if not notion_token:
        raise ValueError("NOTION_TOKEN environment variable is required")
    return NotionClient(notion_token)


def redact_secrets(text: str) -> str:
    """Redact potential secrets from text"""
    # Basic patterns for common secrets
    patterns = [
        (r'\b[A-Za-z0-9+/]{40,}\b', '[REDACTED_BASE64]'),
        (r'\bghp_[A-Za-z0-9_]{36}\b', '[REDACTED_GITHUB_TOKEN]'),
        (r'\bgho_[A-Za-z0-9_]{36}\b', '[REDACTED_GITHUB_TOKEN]'),
        (r'\bghu_[A-Za-z0-9_]{36}\b', '[REDACTED_GITHUB_TOKEN]'),
        (r'\bghs_[A-Za-z0-9_]{36}\b', '[REDACTED_GITHUB_TOKEN]'),
        (r'\bghr_[A-Za-z0-9_]{36}\b', '[REDACTED_GITHUB_TOKEN]'),
        (r'\bsk-[A-Za-z0-9]{48}\b', '[REDACTED_OPENAI_KEY]'),
        (r'\b[A-Za-z0-9_-]{32,}\b', '[REDACTED_GENERIC_KEY]'),
    ]
    
    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)
    
    return redacted


@mcp.tool()
async def pr_index_build(request: PRIndexRequest) -> Dict[str, Any]:
    """Build and index PR overlay chunks with optimized chunking"""
    try:
        manager = get_manager()
        repo = os.getenv("GITHUB_REPOSITORY", "unknown/repo")
        
        # Load optimized chunking configuration
        config = load_config()
        chunker = SemanticChunker(config)
        repo_root = Path(request.repo_root)
        
        chunks = []
        total_chunks = 0
        
        # Always index diff hunks (source_type="diff")
        diff_chunker = DiffChunker()
        diff_chunks = diff_chunker.chunk_diff(request.diff_text)
        
        for chunk_text, start_line, end_line in diff_chunks:
            if not chunk_text.strip():
                continue
            
            # Create context header for diff
            header = chunker.create_context_header(
                source_type='diff',
                path='unknown',
                hunk_header=f"lines {start_line}-{end_line}"
            )
            
            enriched_content = header + chunk_text
            
            chunk_record = ChunkRecord(
                repo=repo,
                pr_number=request.pr_number,
                head_sha=request.head_sha,
                source_type="diff",
                path=None,
                language=None,
                symbol=None,
                start_line=start_line,
                end_line=end_line,
                content=redact_secrets(enriched_content),
                content_hash=manager.compute_content_hash(chunk_text),
                embedding=await manager.embed_text(enriched_content),
            )
            chunks.append(chunk_record)
            total_chunks += 1
        
        # Prioritize changed files for indexing
        prioritized_files = chunker.prioritize_changed_files(
            request.changed_files,
            config.max_changed_files_indexed
        )
        
        # Process changed files with limits
        for file_info in prioritized_files:
            if total_chunks >= config.max_total_chunks_per_run:
                logger.info(f"Reached chunk limit ({config.max_total_chunks_per_run}), stopping")
                break
            
            file_path = file_info.get("path")
            if not file_path:
                continue
            
            full_path = repo_root / file_path
            
            # Use optimized chunking with path filtering
            file_chunks = chunker.chunk_file(
                full_path,
                source_type='code',
                relative_to=repo_root
            )
            
            for chunk_data in file_chunks:
                if total_chunks >= config.max_total_chunks_per_run:
                    break
                
                # Extract original content for hashing
                original_content = chunk_data['original_content']
                
                chunk_record = ChunkRecord(
                    repo=repo,
                    pr_number=request.pr_number,
                    head_sha=request.head_sha,
                    source_type="code",
                    path=chunk_data['path'],
                    language=chunk_data['language'],
                    symbol=chunk_data['symbol'],
                    start_line=chunk_data['start_line'],
                    end_line=chunk_data['end_line'],
                    content=redact_secrets(chunk_data['content']),
                    content_hash=manager.compute_content_hash(original_content),
                    embedding=await manager.embed_text(chunk_data['content']),
                )
                chunks.append(chunk_record)
                total_chunks += 1
        
        # Upsert chunks
        stats = await manager.upsert_chunks(chunks)
        
        logger.info(f"PR indexing complete: {stats['upserted']} upserted, {stats['skipped']} skipped")
        
        return {
            "stats": stats,
            "upserted_count": stats["upserted"],
            "skipped_count": stats["skipped"],
            "files_considered": len(request.changed_files),
            "files_indexed": len(prioritized_files),
            "chunks_created": total_chunks
        }
        
    except Exception as e:
        logger.error(f"Failed to build PR index: {e}")
        raise


@mcp.tool()
async def pr_index_search(
    pr_number: int,
    head_sha: str,
    query: str,
    k: int = 10,
    source_types: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Search PR overlay chunks"""
    try:
        manager = get_manager()
        repo = os.getenv("GITHUB_REPOSITORY", "unknown/repo")
        
        if source_types is None:
            source_types = ["code", "diff"]
        
        query_embedding = await manager.embed_text(query)
        results = await manager.search_chunks(
            query_embedding=query_embedding,
            repo=repo,
            pr_number=pr_number,
            head_sha=head_sha,
            source_types=source_types,
            k=k
        )
        
        return results
        
    except Exception as e:
        logger.error(f"Failed to search PR index: {e}")
        raise


@mcp.tool()
async def repo_docs_build(repo_root: str) -> Dict[str, Any]:
    """Build and index repository documentation with optimized chunking"""
    try:
        manager = get_manager()
        repo = os.getenv("GITHUB_REPOSITORY", "unknown/repo")
        
        # Load optimized chunking configuration
        config = load_config()
        chunker = SemanticChunker(config)
        repo_root_path = Path(repo_root)
        
        chunks = []
        
        # Paths to index
        doc_paths = [
            "README.md",
            "SECURITY.md", 
            "CONTRIBUTING.md",
            "docs/**/*.md",
            "adr/**/*.md",
            ".github/**/*.md"
        ]
        
        for pattern in doc_paths:
            path = repo_root_path / pattern
            for file_path in repo_root_path.glob(pattern):
                if not file_path.is_file():
                    continue
                
                # Use optimized chunking with path filtering
                file_chunks = chunker.chunk_file(
                    file_path,
                    source_type='repo_doc',
                    relative_to=repo_root_path
                )
                
                for chunk_data in file_chunks:
                    # Extract original content for hashing
                    original_content = chunk_data['original_content']
                    
                    chunk_record = ChunkRecord(
                        repo=repo,
                        pr_number=None,
                        head_sha=None,
                        source_type="repo_doc",
                        path=chunk_data['path'],
                        language="markdown",
                        symbol=None,
                        start_line=chunk_data['start_line'],
                        end_line=chunk_data['end_line'],
                        content=redact_secrets(chunk_data['content']),
                        content_hash=manager.compute_content_hash(original_content),
                        embedding=await manager.embed_text(chunk_data['content']),
                    )
                    chunks.append(chunk_record)
                        
        stats = await manager.upsert_chunks(chunks)
        
        return {
            "stats": stats,
            "upserted_count": stats["upserted"],
            "skipped_count": stats["skipped"],
        }
        
    except Exception as e:
        logger.error(f"Failed to build repo docs index: {e}")
        raise


@mcp.tool()
async def repo_docs_search(query: str, k: int = 10) -> List[Dict[str, Any]]:
    """Search repository documentation"""
    try:
        manager = get_manager()
        repo = os.getenv("GITHUB_REPOSITORY", "unknown/repo")
        
        query_embedding = await manager.embed_text(query)
        results = await manager.search_chunks(
            query_embedding=query_embedding,
            repo=repo,
            source_types=["repo_doc"],
            k=k
        )
        
        return results
        
    except Exception as e:
        logger.error(f"Failed to search repo docs: {e}")
        raise


@mcp.tool()
async def notion_index(
    page_ids: Optional[List[str]] = None,
    refresh_mode: str = "incremental"
) -> Dict[str, Any]:
    """Index Notion pages"""
    try:
        manager = get_manager()
        notion_client = get_notion_client()
        repo = os.getenv("GITHUB_REPOSITORY", "unknown/repo")
        
        if page_ids is None:
            page_ids_str = os.getenv("NOTION_PAGE_IDS", "")
            page_ids = [pid.strip() for pid in page_ids_str.split(",") if pid.strip()]
        
        if not page_ids:
            return {"stats": {"upserted": 0, "skipped": 0}, "upserted_count": 0}
        
        chunks = []
        doc_chunker = DocumentChunker()
        
        for page_id in page_ids:
            try:
                page_data = await notion_client.get_page_content(page_id)
                
                file_chunks = doc_chunker.chunk_document(page_data["content"])
                
                for chunk_text, start_line, end_line in file_chunks:
                    if not chunk_text.strip():
                        continue
                    
                    chunk_record = ChunkRecord(
                        repo=repo,
                        pr_number=None,
                        head_sha=None,
                        source_type="notion",
                        source_id=page_id,
                        path=None,
                        language="markdown",
                        symbol=None,
                        start_line=start_line,
                        end_line=end_line,
                        url=page_data["url"],
                        last_edited_time=page_data["last_edited_time"],
                        content=redact_secrets(chunk_text),
                        content_hash=manager.compute_content_hash(chunk_text),
                        embedding=await manager.embed_text(chunk_text),
                    )
                    chunks.append(chunk_record)
                    
            except Exception as e:
                logger.error(f"Failed to process Notion page {page_id}: {e}")
                continue
        
        stats = await manager.upsert_chunks(chunks)
        
        return {
            "stats": stats,
            "upserted_count": stats["upserted"],
            "skipped_count": stats["skipped"],
            "last_sync": str(stats.get("last_sync", "unknown")),
        }
        
    except Exception as e:
        logger.error(f"Failed to index Notion pages: {e}")
        raise


@mcp.tool()
async def notion_search(
    query: str,
    k: int = 10,
    filters: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Search Notion pages"""
    try:
        manager = get_manager()
        repo = os.getenv("GITHUB_REPOSITORY", "unknown/repo")
        
        query_embedding = await manager.embed_text(query)
        results = await manager.search_chunks(
            query_embedding=query_embedding,
            repo=repo,
            source_types=["notion"],
            k=k,
            filters=filters
        )
        
        return results
        
    except Exception as e:
        logger.error(f"Failed to search Notion: {e}")
        raise


@mcp.tool()
async def snippet_get_repo(
    path: str,
    start_line: int,
    end_line: int,
    repo_root: str,
    head_sha: Optional[str] = None
) -> Optional[str]:
    """Get exact snippet from repository file"""
    try:
        manager = get_manager()
        return await manager.get_repo_snippet(path, start_line, end_line, repo_root, head_sha)
        
    except Exception as e:
        logger.error(f"Failed to get repo snippet: {e}")
        return None


@mcp.tool()
async def snippet_get_notion(
    page_id: str,
    chunk_id: Optional[str] = None
) -> Optional[str]:
    """Get snippet from Notion page"""
    try:
        notion_client = get_notion_client()
        page_data = await notion_client.get_page_content(page_id)
        return page_data.get("content", "")
        
    except Exception as e:
        logger.error(f"Failed to get Notion snippet: {e}")
        return None


@mcp.tool()
async def review_verify_citations(draft_markdown: str) -> Dict[str, Any]:
    """Verify citations in draft markdown"""
    try:
        # Pattern for hard claims
        hard_claim_patterns = [
            r'\b(must|shall|required|violates|policy|standard|breaks|we do|always|never)\b',
        ]
        
        # Pattern for citations
        citation_patterns = [
            r'\[.*?\]\(.*?\)',  # Markdown links
            r'@\w+',            # @mentions
            r'https?://[^\s]+', # URLs
        ]
        
        hard_claims = []
        cited_claims = []
        
        lines = draft_markdown.split('\n')
        for i, line in enumerate(lines, 1):
            line_lower = line.lower()
            
            # Check for hard claims
            for pattern in hard_claim_patterns:
                if re.search(pattern, line_lower):
                    hard_claims.append({"line": i, "content": line.strip()})
                    break
            
            # Check for citations
            has_citation = any(re.search(pattern, line) for pattern in citation_patterns)
            if has_citation:
                cited_claims.append({"line": i, "content": line.strip()})
        
        # Find missing citations
        missing_citations = []
        for claim in hard_claims:
            if not any(claim["line"] == cited["line"] for cited in cited_claims):
                missing_citations.append(claim)
        
        return {
            "hard_claim_count": len(hard_claims),
            "cited_hard_claim_count": len(cited_claims),
            "missing_citations": missing_citations,
        }
        
    except Exception as e:
        logger.error(f"Failed to verify citations: {e}")
        raise


@mcp.tool()
async def redact(text: str) -> str:
    """Redact secrets from text"""
    return redact_secrets(text)


if __name__ == "__main__":
    mcp.run()
