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
    """Build and index PR overlay chunks"""
    try:
        manager = get_manager()
        repo = os.getenv("GITHUB_REPOSITORY", "unknown/repo")
        
        chunks = []
        
        # Chunk diff hunks
        diff_chunker = DiffChunker()
        diff_chunks = diff_chunker.chunk_diff(request.diff_text)
        
        for chunk_text, start_line, end_line in diff_chunks:
            if not chunk_text.strip():
                continue
                
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
                content=redact_secrets(chunk_text),
                content_hash=manager.compute_content_hash(chunk_text),
                embedding=await manager.embed_text(chunk_text),
            )
            chunks.append(chunk_record)
        
        # Chunk changed files
        code_chunker = CodeChunker()
        
        for file_info in request.changed_files:
            file_path = file_info.get("path")
            if not file_path:
                continue
                
            full_path = Path(request.repo_root) / file_path
            if not full_path.exists():
                logger.warning(f"File not found: {full_path}")
                continue
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                file_chunks = code_chunker.chunk_file(file_path, content)
                
                for chunk_text, start_line, end_line in file_chunks:
                    if not chunk_text.strip():
                        continue
                    
                    # Try to extract symbol (function/class name) - basic heuristic
                    symbol = None
                    if start_line and end_line:
                        lines = content.split('\n')[start_line-1:end_line]
                        for line in lines:
                            line = line.strip()
                            if line.startswith(('def ', 'class ', 'function ', 'const ')):
                                symbol = line.split('(')[0].split()[1]
                                break
                    
                    chunk_record = ChunkRecord(
                        repo=repo,
                        pr_number=request.pr_number,
                        head_sha=request.head_sha,
                        source_type="code",
                        path=file_path,
                        language=Path(file_path).suffix[1:] if Path(file_path).suffix else None,
                        symbol=symbol,
                        start_line=start_line,
                        end_line=end_line,
                        content=redact_secrets(chunk_text),
                        content_hash=manager.compute_content_hash(chunk_text),
                        embedding=await manager.embed_text(chunk_text),
                    )
                    chunks.append(chunk_record)
                    
            except Exception as e:
                logger.error(f"Failed to process file {file_path}: {e}")
                continue
        
        # Upsert chunks
        stats = await manager.upsert_chunks(chunks)
        
        return {
            "stats": stats,
            "upserted_count": stats["upserted"],
            "skipped_count": stats["skipped"],
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
    """Build and index repository documentation"""
    try:
        manager = get_manager()
        repo = os.getenv("GITHUB_REPOSITORY", "unknown/repo")
        
        chunks = []
        doc_chunker = DocumentChunker()
        
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
            path = Path(repo_root) / pattern
            for file_path in Path(repo_root).glob(pattern):
                if not file_path.is_file():
                    continue
                    
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    file_chunks = doc_chunker.chunk_document(content)
                    
                    for chunk_text, start_line, end_line in file_chunks:
                        if not chunk_text.strip():
                            continue
                        
                        relative_path = str(file_path.relative_to(repo_root))
                        
                        chunk_record = ChunkRecord(
                            repo=repo,
                            pr_number=None,
                            head_sha=None,
                            source_type="repo_doc",
                            path=relative_path,
                            language="markdown",
                            symbol=None,
                            start_line=start_line,
                            end_line=end_line,
                            content=redact_secrets(chunk_text),
                            content_hash=manager.compute_content_hash(chunk_text),
                            embedding=await manager.embed_text(chunk_text),
                        )
                        chunks.append(chunk_record)
                        
                except Exception as e:
                    logger.error(f"Failed to process doc file {file_path}: {e}")
                    continue
        
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
