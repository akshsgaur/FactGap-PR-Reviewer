"""Scoped retrieval with intent-based routing and score normalization"""

import os
import logging
from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from app.services.rag.intent import IntentClassifier, IntentResult, QueryIntent

logger = logging.getLogger(__name__)

# Feature flag
ENABLE_INTENT_ROUTING = os.getenv("FACTGAP_ENABLE_INTENT_ROUTING", "true").lower() == "true"


class ScopeType(Enum):
    """Types of retrieval scopes"""
    PR_OVERLAY = "pr_overlay"
    REPO_DOCS = "repo_docs"
    NOTION = "notion"


@dataclass
class RetrievalScope:
    """Definition of a retrieval scope"""
    scope_type: ScopeType
    source_types: List[str]
    filters: Dict[str, Any] = field(default_factory=dict)
    k: int = 30
    min_score: float = 0.5


@dataclass
class ScoredChunk:
    """A chunk with normalized and weighted scores"""
    chunk: Dict[str, Any]
    raw_score: float
    normalized_score: float
    weighted_score: float
    scope_type: ScopeType

    @property
    def id(self) -> str:
        return self.chunk.get("id", "")

    @property
    def source_type(self) -> str:
        return self.chunk.get("source_type", "")

    @property
    def doc_key(self) -> str:
        """Unique document key for diversity constraints"""
        source_type = self.source_type
        if source_type in ("code", "diff", "repo_doc"):
            return self.chunk.get("path", "unknown")
        elif source_type == "notion":
            return self.chunk.get("url", "") or self.chunk.get("source_id", "unknown")
        return "unknown"


class ScopedRetriever:
    """
    Retriever that searches multiple scopes and merges results
    with intent-based weighting and score normalization.
    """

    def __init__(self, supabase_client, embed_func):
        """
        Args:
            supabase_client: Supabase client for RPC calls
            embed_func: Function to embed text -> List[float]
        """
        self.supabase = supabase_client
        self.embed_func = embed_func
        self.intent_classifier = IntentClassifier()

    def build_scopes(
        self,
        user_id: str,
        repo: Optional[str] = None,
        pr_number: Optional[int] = None,
        head_sha: Optional[str] = None,
    ) -> List[RetrievalScope]:
        """Build retrieval scopes based on context"""
        scopes = []

        # PR overlay scope (if PR context provided)
        if pr_number is not None:
            pr_filters = {"user_id": user_id}
            if repo:
                pr_filters["repo"] = repo
            pr_filters["pr_number"] = pr_number
            if head_sha:
                pr_filters["head_sha"] = head_sha

            scopes.append(RetrievalScope(
                scope_type=ScopeType.PR_OVERLAY,
                source_types=["code", "diff"],
                filters=pr_filters,
                k=30,
                min_score=0.5,
            ))

        # Repo docs scope
        if repo:
            scopes.append(RetrievalScope(
                scope_type=ScopeType.REPO_DOCS,
                source_types=["code", "repo_doc"],
                filters={"user_id": user_id, "repo": repo},
                k=30,
                min_score=0.5,
            ))

        # Notion scope
        scopes.append(RetrievalScope(
            scope_type=ScopeType.NOTION,
            source_types=["notion"],
            filters={"user_id": user_id},
            k=30,
            min_score=0.5,
        ))

        return scopes

    async def search_scope(
        self,
        query_embedding: List[float],
        scope: RetrievalScope,
    ) -> List[Dict[str, Any]]:
        """Search a single scope and return results"""
        params = {
            "p_query_embedding": query_embedding,
            "p_k": scope.k,
            "p_min_score": scope.min_score,
            "p_source_types": scope.source_types,
        }

        # Add filters
        for key, value in scope.filters.items():
            if key == "user_id":
                params["p_user_id"] = value
            elif key == "repo":
                params["p_repo"] = value
            elif key == "pr_number":
                params["p_pr_number"] = value
            elif key == "head_sha":
                params["p_head_sha"] = value

        try:
            response = self.supabase.rpc("match_chunks_user", params).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Error searching scope {scope.scope_type}: {e}")
            return []

    def normalize_scores(
        self,
        chunks: List[Dict[str, Any]],
        scope_type: ScopeType,
    ) -> List[ScoredChunk]:
        """
        Normalize scores within a scope using min-max normalization.
        Returns ScoredChunk objects with normalized scores.
        """
        if not chunks:
            return []

        scores = [c.get("score", 0.0) for c in chunks]
        min_score = min(scores)
        max_score = max(scores)
        score_range = max_score - min_score

        scored_chunks = []
        for chunk in chunks:
            raw_score = chunk.get("score", 0.0)

            # Normalize to 0-1 range
            if score_range > 0:
                normalized = (raw_score - min_score) / score_range
            else:
                normalized = 1.0  # All same score

            scored_chunks.append(ScoredChunk(
                chunk=chunk,
                raw_score=raw_score,
                normalized_score=normalized,
                weighted_score=normalized,  # Will be updated with weights
                scope_type=scope_type,
            ))

        return scored_chunks

    def apply_intent_weights(
        self,
        scored_chunks: List[ScoredChunk],
        intent_result: IntentResult,
    ) -> List[ScoredChunk]:
        """Apply intent-based weights to normalized scores"""
        weights = intent_result.scope_weights

        for sc in scored_chunks:
            # Get weight for this source type
            source_type = sc.source_type
            weight = weights.get(source_type, 1.0)

            # Apply weight to normalized score
            sc.weighted_score = sc.normalized_score * weight

        return scored_chunks

    def merge_and_sort(
        self,
        all_chunks: List[ScoredChunk],
        top_k: int = 40,
    ) -> List[ScoredChunk]:
        """
        Merge chunks from all scopes, deduplicate, and sort by weighted score.
        Returns top_k candidates for reranking.
        """
        # Deduplicate by chunk ID
        seen_ids = set()
        unique_chunks = []
        for sc in all_chunks:
            if sc.id not in seen_ids:
                seen_ids.add(sc.id)
                unique_chunks.append(sc)

        # Sort by weighted score descending
        unique_chunks.sort(key=lambda x: x.weighted_score, reverse=True)

        return unique_chunks[:top_k]

    async def retrieve(
        self,
        query: str,
        user_id: str,
        repo: Optional[str] = None,
        pr_number: Optional[int] = None,
        head_sha: Optional[str] = None,
        top_k: int = 40,
    ) -> tuple[List[ScoredChunk], IntentResult, Dict[str, Any]]:
        """
        Main retrieval method with scoped search and intent routing.

        Returns:
            - List of ScoredChunk candidates (top_k)
            - IntentResult from classification
            - Stats dict for logging
        """
        stats: Dict[str, Any] = {
            "query_length": len(query),
            "scopes": {},
        }

        # Classify intent
        if ENABLE_INTENT_ROUTING:
            intent_result = self.intent_classifier.classify(query)
        else:
            # Default to general intent if routing disabled
            intent_result = IntentResult(
                intent=QueryIntent.GENERAL,
                confidence=0.0,
                matched_keywords=set(),
                scope_weights={"code": 1.0, "diff": 1.0, "repo_doc": 1.0, "notion": 1.0},
            )

        stats["intent"] = intent_result.intent.value
        stats["intent_confidence"] = intent_result.confidence

        # Embed query
        query_embedding = self.embed_func(query)

        # Build scopes
        scopes = self.build_scopes(user_id, repo, pr_number, head_sha)

        # Search each scope
        all_scored_chunks: List[ScoredChunk] = []

        for scope in scopes:
            results = await self.search_scope(query_embedding, scope)

            # Normalize scores within scope
            scored = self.normalize_scores(results, scope.scope_type)

            # Apply intent weights
            if ENABLE_INTENT_ROUTING:
                scored = self.apply_intent_weights(scored, intent_result)

            all_scored_chunks.extend(scored)

            # Record stats
            scope_stats = {
                "count": len(results),
                "source_types": scope.source_types,
            }
            if results:
                raw_scores = [r.get("score", 0) for r in results]
                scope_stats["score_min"] = min(raw_scores)
                scope_stats["score_max"] = max(raw_scores)
                scope_stats["score_mean"] = sum(raw_scores) / len(raw_scores)

            stats["scopes"][scope.scope_type.value] = scope_stats

        # Merge and get top candidates
        candidates = self.merge_and_sort(all_scored_chunks, top_k)

        stats["total_candidates"] = len(all_scored_chunks)
        stats["merged_candidates"] = len(candidates)

        return candidates, intent_result, stats
