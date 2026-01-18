"""Supabase client and database utilities"""

import os
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

import openai
from supabase import create_client, Client
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ChunkRecord(BaseModel):
    """Database record for a chunk"""
    id: Optional[str] = None
    repo: str
    pr_number: Optional[int] = None
    head_sha: Optional[str] = None
    source_type: str  # code | diff | repo_doc | notion
    source_id: Optional[str] = None
    path: Optional[str] = None
    language: Optional[str] = None
    symbol: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    url: Optional[str] = None
    last_edited_time: Optional[datetime] = None
    content: str
    content_hash: str
    embedding: List[float]
    embedding_model: str = "text-embedding-3-small"


class SupabaseManager:
    """Manages Supabase operations for RAG storage"""
    
    def __init__(self, supabase_url: str, supabase_key: str, openai_api_key: str):
        self.client: Client = create_client(supabase_url, supabase_key)
        self.openai_client = openai.OpenAI(api_key=openai_api_key)
        
    def compute_content_hash(self, content: str) -> str:
        """Compute SHA256 hash of normalized content"""
        normalized = content.strip().lower()
        return hashlib.sha256(normalized.encode()).hexdigest()
    
    def embed_text(self, text: str) -> List[float]:
        """Embed text using OpenAI embeddings"""
        try:
            response = self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Failed to embed text: {e}")
            raise
    
    async def upsert_chunks(self, chunks: List[ChunkRecord]) -> Dict[str, int]:
        """Upsert chunks to Supabase with idempotency"""
        stats = {"upserted": 0, "skipped": 0}
        
        for chunk in chunks:
            try:
                # Check if chunk already exists
                query = self.client.table("rag_chunks").select("id").eq(
                    "repo", chunk.repo
                ).eq(
                    "source_type", chunk.source_type
                ).eq(
                    "content_hash", chunk.content_hash
                )
                
                # Add optional filters only if they're not None
                if chunk.pr_number is not None:
                    query = query.eq("pr_number", chunk.pr_number)
                if chunk.head_sha is not None:
                    query = query.eq("head_sha", chunk.head_sha)
                if chunk.path is not None:
                    query = query.eq("path", chunk.path)
                else:
                    query = query.is_("path", "null")
                if chunk.start_line is not None:
                    query = query.eq("start_line", chunk.start_line)
                else:
                    query = query.is_("start_line", "null")
                if chunk.end_line is not None:
                    query = query.eq("end_line", chunk.end_line)
                else:
                    query = query.is_("end_line", "null")
                
                existing = query.execute()
                
                if existing.data:
                    stats["skipped"] += 1
                    continue
                
                # Insert new chunk
                insert_data = {
                    "repo": chunk.repo,
                    "source_type": chunk.source_type,
                    "content": chunk.content,
                    "content_hash": chunk.content_hash,
                    "embedding": chunk.embedding,
                    "embedding_model": chunk.embedding_model,
                }
                
                # Add optional fields only if they're not None
                if chunk.pr_number is not None:
                    insert_data["pr_number"] = chunk.pr_number
                if chunk.head_sha is not None:
                    insert_data["head_sha"] = chunk.head_sha
                if chunk.source_id is not None:
                    insert_data["source_id"] = chunk.source_id
                if chunk.path is not None:
                    insert_data["path"] = chunk.path
                if chunk.language is not None:
                    insert_data["language"] = chunk.language
                if chunk.symbol is not None:
                    insert_data["symbol"] = chunk.symbol
                if chunk.start_line is not None:
                    insert_data["start_line"] = chunk.start_line
                if chunk.end_line is not None:
                    insert_data["end_line"] = chunk.end_line
                if chunk.url is not None:
                    insert_data["url"] = chunk.url
                if chunk.last_edited_time is not None:
                    # Convert datetime to ISO string for JSON serialization
                    if hasattr(chunk.last_edited_time, 'isoformat'):
                        insert_data["last_edited_time"] = chunk.last_edited_time.isoformat()
                    else:
                        insert_data["last_edited_time"] = str(chunk.last_edited_time)
                
                self.client.table("rag_chunks").insert(insert_data).execute()
                
                stats["upserted"] += 1
                
            except Exception as e:
                logger.error(f"Failed to upsert chunk: {e}")
                raise
        
        return stats
    
    async def search_chunks(
        self,
        query_embedding: List[float],
        repo: Optional[str] = None,
        pr_number: Optional[int] = None,
        head_sha: Optional[str] = None,
        source_types: Optional[List[str]] = None,
        k: int = 10,
        min_score: float = 0.7,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar chunks using the RPC function"""
        try:
            params = {
                "p_query_embedding": query_embedding,
                "p_k": k,
                "p_min_score": min_score,
            }
            
            if repo:
                params["p_repo"] = repo
            if pr_number is not None:
                params["p_pr_number"] = pr_number
            if head_sha:
                params["p_head_sha"] = head_sha
            if source_types:
                params["p_source_types"] = source_types
            if filters:
                params["p_filters"] = filters
            
            response = self.client.rpc("match_chunks", params).execute()
            return response.data or []
            
        except Exception as e:
            logger.error(f"Failed to search chunks: {e}")
            raise
    
    async def get_repo_snippet(
        self,
        path: str,
        start_line: int,
        end_line: int,
        repo_root: str,
        head_sha: Optional[str] = None
    ) -> Optional[str]:
        """Get exact snippet from repository file"""
        try:
            import os
            
            file_path = os.path.join(repo_root, path)
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Adjust for 1-based line numbers
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            
            snippet_lines = lines[start_idx:end_idx]
            return ''.join(snippet_lines).rstrip()
            
        except Exception as e:
            logger.error(f"Failed to get repo snippet: {e}")
            return None


def get_supabase_manager() -> SupabaseManager:
    """Get configured Supabase manager from environment variables"""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if not all([supabase_url, supabase_key, openai_key]):
        raise ValueError("Missing required environment variables: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENAI_API_KEY")
    
    return SupabaseManager(supabase_url, supabase_key, openai_key)
