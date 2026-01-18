"""Batch embeddings with identity skip logic"""

import os
import logging
import hashlib
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Configuration
EMBED_BATCH_SIZE = int(os.getenv("FACTGAP_EMBED_BATCH_SIZE", "32"))
EMBED_MODEL = os.getenv("FACTGAP_EMBED_MODEL", "text-embedding-3-small")


@dataclass
class EmbedResult:
    """Result of embedding a batch of texts"""
    embeddings: List[List[float]]
    skipped_indices: List[int]  # Indices that were skipped (already exist)
    new_indices: List[int]  # Indices that were newly embedded
    stats: Dict[str, Any]


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content for identity checks"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class BatchEmbedder:
    """
    Batch embedder with identity skip logic.

    Uses OpenAI batch embedding API for efficiency.
    Skips embedding when content_hash already exists in database.
    """

    def __init__(
        self,
        openai_client,
        supabase_client=None,
        batch_size: int = EMBED_BATCH_SIZE,
        model: str = EMBED_MODEL,
    ):
        """
        Args:
            openai_client: OpenAI client for embeddings
            supabase_client: Optional Supabase client for hash lookups
            batch_size: Number of texts to embed per API call
            model: OpenAI embedding model to use
        """
        self.openai_client = openai_client
        self.supabase = supabase_client
        self.batch_size = batch_size
        self.model = model

    def embed_single(self, text: str) -> List[float]:
        """Embed a single text (convenience method)"""
        response = self.openai_client.embeddings.create(
            model=self.model,
            input=[text],
        )
        return response.data[0].embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a batch of texts using OpenAI batch API.

        Returns embeddings in the same order as input texts.
        """
        if not texts:
            return []

        all_embeddings = []

        # Process in batches
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]

            response = self.openai_client.embeddings.create(
                model=self.model,
                input=batch,
            )

            # Sort by index to ensure order matches input
            sorted_data = sorted(response.data, key=lambda x: x.index)
            batch_embeddings = [d.embedding for d in sorted_data]
            all_embeddings.extend(batch_embeddings)

            logger.debug(f"Embedded batch {i // self.batch_size + 1}: {len(batch)} texts")

        return all_embeddings

    async def embed_with_skip(
        self,
        texts: List[str],
        content_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        check_existing_fn: Optional[Callable[[List[str]], List[str]]] = None,
    ) -> EmbedResult:
        """
        Embed texts with identity skip logic.

        Skips embedding for texts whose content_hash already exists in database.

        Args:
            texts: List of texts to embed
            content_hashes: Optional pre-computed hashes (computed if not provided)
            user_id: User ID for scoped hash lookups
            check_existing_fn: Optional custom function to check existing hashes.
                               Should take list of hashes and return list of existing hashes.

        Returns:
            EmbedResult with embeddings, skipped indices, and stats
        """
        if not texts:
            return EmbedResult(
                embeddings=[],
                skipped_indices=[],
                new_indices=[],
                stats={"total": 0, "skipped": 0, "embedded": 0},
            )

        # Compute hashes if not provided
        if content_hashes is None:
            content_hashes = [compute_content_hash(t) for t in texts]

        # Check which hashes already exist
        existing_hashes: set = set()

        if check_existing_fn:
            # Use custom check function
            existing_list = check_existing_fn(content_hashes)
            existing_hashes = set(existing_list)
        elif self.supabase and user_id:
            # Check against Supabase
            existing_hashes = await self._check_existing_hashes(
                content_hashes, user_id
            )

        # Separate texts into new vs existing
        texts_to_embed = []
        text_indices = []  # Original indices for texts we're embedding
        skipped_indices = []

        for i, (text, hash_val) in enumerate(zip(texts, content_hashes)):
            if hash_val in existing_hashes:
                skipped_indices.append(i)
            else:
                texts_to_embed.append(text)
                text_indices.append(i)

        # Embed only new texts
        new_embeddings = []
        if texts_to_embed:
            new_embeddings = self.embed_batch(texts_to_embed)

        # Build result embeddings array (None for skipped, embedding for new)
        embeddings: List[Any] = [None] * len(texts)
        for orig_idx, embedding in zip(text_indices, new_embeddings):
            embeddings[orig_idx] = embedding

        stats = {
            "total": len(texts),
            "skipped": len(skipped_indices),
            "embedded": len(texts_to_embed),
            "batch_count": (len(texts_to_embed) + self.batch_size - 1) // self.batch_size if texts_to_embed else 0,
        }

        logger.info(
            f"Batch embedding: {stats['total']} total, "
            f"{stats['skipped']} skipped, {stats['embedded']} embedded"
        )

        return EmbedResult(
            embeddings=embeddings,
            skipped_indices=skipped_indices,
            new_indices=text_indices,
            stats=stats,
        )

    async def _check_existing_hashes(
        self,
        content_hashes: List[str],
        user_id: str,
    ) -> set:
        """Check which content hashes already exist in database"""
        if not content_hashes or not self.supabase:
            return set()

        try:
            # Query for existing hashes
            response = self.supabase.from_("rag_chunks").select(
                "content_hash"
            ).eq(
                "user_id", user_id
            ).in_(
                "content_hash", content_hashes
            ).execute()

            existing = {row["content_hash"] for row in (response.data or [])}
            logger.debug(f"Found {len(existing)} existing hashes out of {len(content_hashes)}")
            return existing

        except Exception as e:
            logger.warning(f"Error checking existing hashes: {e}")
            return set()  # On error, embed everything


class EmbedFunction:
    """
    Wrapper to create an embed function for use with ScopedRetriever.

    Usage:
        embed_fn = EmbedFunction(openai_client).embed
        retriever = ScopedRetriever(supabase, embed_fn)
    """

    def __init__(self, openai_client, model: str = EMBED_MODEL):
        self.openai_client = openai_client
        self.model = model

    def embed(self, text: str) -> List[float]:
        """Embed a single text for query embedding"""
        response = self.openai_client.embeddings.create(
            model=self.model,
            input=[text],
        )
        return response.data[0].embedding
