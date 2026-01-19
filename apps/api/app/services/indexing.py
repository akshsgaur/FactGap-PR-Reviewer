"""Indexing service for repositories and Notion pages"""

import os
import sys
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from pathlib import Path

import openai
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    Language,
)

from app.config import get_settings
from app.database import get_db
from app.services.github_app import get_github_service
from app.services.notion_oauth import get_notion_service

# New RAG modules
from app.services.rag.enrichment import ChunkEnricher, extract_symbol_from_chunk
from app.services.rag.embeddings import BatchEmbedder, compute_content_hash

# Add factgap to path for optimized chunking
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent / 'factgap'))
from chunking import SemanticChunker, load_config

logger = logging.getLogger(__name__)

# Feature flags for new RAG features
ENABLE_ENRICHMENT = os.getenv("FACTGAP_ENABLE_ENRICHMENT", "true").lower() == "true"
ENABLE_BATCH_EMBED = os.getenv("FACTGAP_ENABLE_BATCH_EMBED", "true").lower() == "true"

# Language mappings for code splitter
EXTENSION_TO_LANGUAGE = {
    ".py": Language.PYTHON,
    ".js": Language.JS,
    ".ts": Language.TS,
    ".tsx": Language.TS,
    ".jsx": Language.JS,
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".java": Language.JAVA,
    ".rb": Language.RUBY,
    ".php": Language.PHP,
    ".c": Language.C,
    ".cpp": Language.CPP,
    ".h": Language.C,
    ".hpp": Language.CPP,
    ".cs": Language.CSHARP,
    ".swift": Language.SWIFT,
    ".kt": Language.KOTLIN,
    ".scala": Language.SCALA,
    ".md": Language.MARKDOWN,
}


class IndexingService:
    """Service for indexing repositories and Notion pages"""

    def __init__(self):
        self.settings = get_settings()
        self.db = get_db()
        self.github_service = get_github_service()
        self.notion_service = get_notion_service()
        self.openai_client = openai.OpenAI(api_key=self.settings.openai_api_key)

        # Supabase client for direct chunk operations
        from supabase import create_client
        self.supabase = create_client(
            self.settings.supabase_url,
            self.settings.supabase_service_role_key
        )

        # New RAG components
        self.enricher = ChunkEnricher() if ENABLE_ENRICHMENT else None
        self.batch_embedder = BatchEmbedder(
            self.openai_client,
            self.supabase if ENABLE_BATCH_EMBED else None
        ) if ENABLE_BATCH_EMBED else None

    def _compute_hash(self, content: str) -> str:
        """Compute SHA256 hash of content"""
        # Use new compute_content_hash for consistency
        return compute_content_hash(content)

    def _embed_text(self, text: str) -> List[float]:
        """Generate embedding for text"""
        if self.batch_embedder:
            return self.batch_embedder.embed_single(text)
        response = self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding

    def _enrich_code_content(
        self,
        content: str,
        path: str,
        language: Optional[str],
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        full_file_content: Optional[str] = None,
    ) -> str:
        """Enrich code content with contextual prefix (if enabled)"""
        if not self.enricher:
            return content

        # Try to extract symbol from chunk
        symbol = extract_symbol_from_chunk(content, language)

        enriched = self.enricher.enrich_code_chunk(
            content=content,
            path=path,
            language=language,
            start_line=start_line,
            end_line=end_line,
            full_file_content=full_file_content,
            symbol=symbol,
        )
        return enriched.enriched_content

    def _enrich_diff_content(
        self,
        content: str,
        path: Optional[str] = None,
    ) -> str:
        """Enrich diff content with contextual prefix (if enabled)"""
        if not self.enricher:
            return content

        enriched = self.enricher.enrich_diff_chunk(
            content=content,
            path=path,
        )
        return enriched.enriched_content

    def _enrich_notion_content(
        self,
        content: str,
        title: Optional[str] = None,
        url: Optional[str] = None,
        last_edited_time: Optional[str] = None,
    ) -> str:
        """Enrich Notion content with contextual prefix (if enabled)"""
        if not self.enricher:
            return content

        enriched = self.enricher.enrich_notion_chunk(
            content=content,
            title=title,
            url=url,
            last_edited_time=last_edited_time,
        )
        return enriched.enriched_content

    def _get_code_splitter(self, language: Optional[Language]) -> RecursiveCharacterTextSplitter:
        """Get appropriate code splitter"""
        if language:
            return RecursiveCharacterTextSplitter.from_language(
                language=language,
                chunk_size=1200,
                chunk_overlap=150,
            )
        return RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=150,
        )

    def _get_doc_splitter(self) -> RecursiveCharacterTextSplitter:
        """Get document splitter"""
        return RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
        )

    async def index_repository(
        self,
        user_id: str,
        repo_id: str,
        installation_id: int,
        repo_full_name: str
    ) -> Dict[str, int]:
        """Index a repository's code files"""
        stats = {"indexed": 0, "skipped": 0, "errors": 0}

        try:
            # Update status to indexing
            await self.db.update_repo_indexing_status(repo_id, "indexing")

            # Get all files from the repository
            files = await self.github_service.clone_repo_files(
                installation_id, repo_full_name
            )

            logger.info(f"Found {len(files)} files to index in {repo_full_name}")

            for path, content in files.items():
                try:
                    # Determine language and splitter
                    ext = "." + path.split(".")[-1] if "." in path else ""
                    language = EXTENSION_TO_LANGUAGE.get(ext.lower())
                    splitter = self._get_code_splitter(language)

                    # Split content into chunks
                    chunks = splitter.split_text(content)

                    # Track line numbers
                    current_line = 1

                    lang_str = ext.lstrip(".") if ext else None

                    for chunk in chunks:
                        # Calculate line range
                        chunk_lines = chunk.count("\n") + 1
                        start_line = current_line
                        end_line = current_line + chunk_lines - 1
                        current_line = end_line + 1

                        # Compute hash (on original content for identity)
                        content_hash = self._compute_hash(chunk)

                        # Check if chunk already exists
                        existing = self.supabase.table("rag_chunks").select("id").eq(
                            "user_id", user_id
                        ).eq("repo", repo_full_name).eq("path", path).eq(
                            "content_hash", content_hash
                        ).execute()

                        if existing.data:
                            stats["skipped"] += 1
                            continue

                        # Enrich content for embedding (if enabled)
                        enriched_content = self._enrich_code_content(
                            content=chunk,
                            path=path,
                            language=lang_str,
                            start_line=start_line,
                            end_line=end_line,
                            full_file_content=content,
                        )

                        # Embed the enriched content
                        embedding = self._embed_text(enriched_content)

                        # Insert chunk (store original content, embed enriched)
                        self.supabase.table("rag_chunks").insert({
                            "user_id": user_id,
                            "repo": repo_full_name,
                            "source_type": "code",
                            "path": path,
                            "language": lang_str,
                            "start_line": start_line,
                            "end_line": end_line,
                            "content": chunk,
                            "content_hash": content_hash,
                            "embedding": embedding,
                            "embedding_model": "text-embedding-3-small",
                        }).execute()

                        stats["indexed"] += 1

                except Exception as e:
                    logger.error(f"Error indexing file {path}: {e}")
                    stats["errors"] += 1

            # Update status to complete
            await self.db.update_repo_indexing_status(
                repo_id, "complete", datetime.now(timezone.utc)
            )

            logger.info(f"Indexed {repo_full_name}: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Error indexing repository {repo_full_name}: {e}")
            await self.db.update_repo_indexing_status(repo_id, "error")
            raise

    async def index_notion_page(
        self,
        user_id: str,
        page_db_id: str,
        notion_page_id: str,
        notion_token: str
    ) -> Dict[str, int]:
        """Index a Notion page"""
        stats = {"indexed": 0, "skipped": 0, "errors": 0}

        try:
            # Update status to indexing
            await self.db.update_notion_page_indexing_status(page_db_id, "indexing")

            # Get page content
            page_data = await self.notion_service.get_page_content(
                notion_token, notion_page_id
            )

            content = page_data["content"]
            if not content.strip():
                await self.db.update_notion_page_indexing_status(page_db_id, "complete")
                return stats

            # Split content
            splitter = self._get_doc_splitter()
            chunks = splitter.split_text(content)

            page_title = page_data.get("title")
            page_url = page_data.get("url")
            last_edited = page_data.get("last_edited_time")

            for chunk in chunks:
                try:
                    content_hash = self._compute_hash(chunk)

                    # Check if chunk already exists
                    existing = self.supabase.table("rag_chunks").select("id").eq(
                        "user_id", user_id
                    ).eq("source_type", "notion").eq("source_id", notion_page_id).eq(
                        "content_hash", content_hash
                    ).execute()

                    if existing.data:
                        stats["skipped"] += 1
                        continue

                    # Enrich content for embedding (if enabled)
                    enriched_content = self._enrich_notion_content(
                        content=chunk,
                        title=page_title,
                        url=page_url,
                        last_edited_time=last_edited,
                    )

                    embedding = self._embed_text(enriched_content)

                    # Insert chunk
                    self.supabase.table("rag_chunks").insert({
                        "user_id": user_id,
                        "repo": "notion",
                        "source_type": "notion",
                        "source_id": notion_page_id,
                        "url": page_url,
                        "last_edited_time": last_edited,
                        "content": chunk,
                        "content_hash": content_hash,
                        "embedding": embedding,
                        "embedding_model": "text-embedding-3-small",
                    }).execute()

                    stats["indexed"] += 1

                except Exception as e:
                    logger.error(f"Error indexing Notion chunk: {e}")
                    stats["errors"] += 1

            # Update status to complete
            await self.db.update_notion_page_indexing_status(page_db_id, "complete")

            logger.info(f"Indexed Notion page {notion_page_id}: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Error indexing Notion page {notion_page_id}: {e}")
            await self.db.update_notion_page_indexing_status(page_db_id, "error")
            raise

    async def index_pr(
        self,
        user_id: str,
        installation_id: int,
        repo_full_name: str,
        pr_number: int
    ) -> Dict[str, int]:
        """Index PR diff and changed files"""
        stats = {"indexed": 0, "skipped": 0, "errors": 0}

        try:
            # Get PR details
            pr = await self.github_service.get_pr_details(
                installation_id, repo_full_name, pr_number
            )
            head_sha = pr["head"]["sha"]

            # Get PR diff
            diff = await self.github_service.get_pr_diff(
                installation_id, repo_full_name, pr_number
            )

            # Get changed files
            files = await self.github_service.get_pr_files(
                installation_id, repo_full_name, pr_number
            )

            # Index diff chunks
            diff_splitter = RecursiveCharacterTextSplitter(
                chunk_size=800,
                chunk_overlap=100,
            )

            diff_chunks = diff_splitter.split_text(diff)

            for chunk in diff_chunks:
                try:
                    content_hash = self._compute_hash(chunk)

                    existing = self.supabase.table("rag_chunks").select("id").eq(
                        "user_id", user_id
                    ).eq("repo", repo_full_name).eq("pr_number", pr_number).eq(
                        "source_type", "diff"
                    ).eq("content_hash", content_hash).execute()

                    if existing.data:
                        stats["skipped"] += 1
                        continue

                    # Enrich diff content for embedding
                    enriched_content = self._enrich_diff_content(chunk)
                    embedding = self._embed_text(enriched_content)

                    self.supabase.table("rag_chunks").insert({
                        "user_id": user_id,
                        "repo": repo_full_name,
                        "pr_number": pr_number,
                        "head_sha": head_sha,
                        "source_type": "diff",
                        "content": chunk,
                        "content_hash": content_hash,
                        "embedding": embedding,
                        "embedding_model": "text-embedding-3-small",
                    }).execute()

                    stats["indexed"] += 1

                except Exception as e:
                    logger.error(f"Error indexing diff chunk: {e}")
                    stats["errors"] += 1

            # Index changed file contents
            for file in files:
                if file.get("status") == "removed":
                    continue

                path = file["filename"]
                ext = "." + path.split(".")[-1] if "." in path else ""
                language = EXTENSION_TO_LANGUAGE.get(ext.lower())

                # Get file content at head SHA
                content = await self.github_service.get_file_content(
                    installation_id, repo_full_name, path, head_sha
                )

                if not content:
                    continue

                splitter = self._get_code_splitter(language)
                chunks = splitter.split_text(content)

                current_line = 1
                lang_str = ext.lstrip(".") if ext else None

                for chunk in chunks:
                    try:
                        chunk_lines = chunk.count("\n") + 1
                        start_line = current_line
                        end_line = current_line + chunk_lines - 1
                        current_line = end_line + 1

                        content_hash = self._compute_hash(chunk)

                        # Enrich code content for embedding
                        enriched_content = self._enrich_code_content(
                            content=chunk,
                            path=path,
                            language=lang_str,
                            start_line=start_line,
                            end_line=end_line,
                            full_file_content=content,
                        )
                        embedding = self._embed_text(enriched_content)

                        existing = self.supabase.table("rag_chunks").select("id").eq(
                            "user_id", user_id
                        ).eq("repo", repo_full_name).eq("pr_number", pr_number).eq(
                            "path", path
                        ).eq("content_hash", content_hash).execute()

                        if existing.data:
                            stats["skipped"] += 1
                            continue

                        self.supabase.table("rag_chunks").insert({
                            "user_id": user_id,
                            "repo": repo_full_name,
                            "pr_number": pr_number,
                            "head_sha": head_sha,
                            "source_type": "code",
                            "path": path,
                            "language": ext.lstrip(".") if ext else None,
                            "start_line": start_line,
                            "end_line": end_line,
                            "content": chunk,
                            "content_hash": content_hash,
                            "embedding": embedding,
                            "embedding_model": "text-embedding-3-small",
                        }).execute()

                        stats["indexed"] += 1

                    except Exception as e:
                        logger.error(f"Error indexing PR file chunk: {e}")
                        stats["errors"] += 1

            logger.info(f"Indexed PR #{pr_number} in {repo_full_name}: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Error indexing PR #{pr_number}: {e}")
            raise

    async def delete_user_chunks(self, user_id: str, repo: Optional[str] = None) -> int:
        """Delete all chunks for a user (optionally filtered by repo)"""
        try:
            query = self.supabase.table("rag_chunks").delete().eq("user_id", user_id)
            if repo:
                query = query.eq("repo", repo)

            response = query.execute()
            return len(response.data) if response.data else 0
        except Exception as e:
            logger.error(f"Error deleting user chunks: {e}")
            raise


# Singleton instance
_indexing_service: Optional[IndexingService] = None


def get_indexing_service() -> IndexingService:
    """Get indexing service instance"""
    global _indexing_service
    if _indexing_service is None:
        _indexing_service = IndexingService()
    return _indexing_service
