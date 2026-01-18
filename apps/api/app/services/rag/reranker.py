"""Reranking with Cohere API or LLM fallback, plus diversity constraints"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Feature flags
ENABLE_RERANK = os.getenv("FACTGAP_ENABLE_RERANK", "true").lower() == "true"
ENABLE_DIVERSITY = os.getenv("FACTGAP_ENABLE_DIVERSITY", "true").lower() == "true"
COHERE_API_KEY = os.getenv("COHERE_API_KEY")

# Diversity constraints
MAX_CHUNKS_PER_DOC = 2
MIN_DISTINCT_SOURCES = 2


@dataclass
class RerankerResult:
    """Result from reranking"""
    chunks: List[Any]  # ScoredChunk objects
    rerank_scores: List[float]
    rerank_reasons: List[str]
    method: str  # "cohere", "llm", "passthrough"
    stats: Dict[str, Any]


class Reranker:
    """
    Reranker with Cohere API (preferred) or LLM fallback.
    Includes diversity constraints for final selection.
    """

    def __init__(self, openai_client=None):
        """
        Args:
            openai_client: OpenAI client for LLM fallback reranking
        """
        self.openai_client = openai_client
        self.cohere_api_key = COHERE_API_KEY

    async def rerank(
        self,
        query: str,
        candidates: List[Any],  # ScoredChunk objects
        top_k: int = 8,
        head_sha: Optional[str] = None,
    ) -> RerankerResult:
        """
        Rerank candidates and return top_k with diversity constraints.

        Args:
            query: The search query
            candidates: List of ScoredChunk objects
            top_k: Number of final results to return
            head_sha: For citation formatting

        Returns:
            RerankerResult with reranked chunks
        """
        if not ENABLE_RERANK or not candidates:
            # Passthrough mode - just apply diversity
            return self._apply_diversity(
                candidates[:top_k * 2],
                top_k,
                method="passthrough",
            )

        # Try Cohere first
        if self.cohere_api_key:
            try:
                result = await self._rerank_cohere(query, candidates, top_k * 2)
                return self._apply_diversity(result.chunks, top_k, method="cohere")
            except Exception as e:
                logger.warning(f"Cohere rerank failed, falling back to LLM: {e}")

        # Fallback to LLM reranking
        if self.openai_client:
            try:
                result = await self._rerank_llm(query, candidates, top_k * 2, head_sha)
                return self._apply_diversity(result.chunks, top_k, method="llm")
            except Exception as e:
                logger.warning(f"LLM rerank failed, using passthrough: {e}")

        # Final fallback - just apply diversity to original order
        return self._apply_diversity(candidates[:top_k * 2], top_k, method="passthrough")

    async def _rerank_cohere(
        self,
        query: str,
        candidates: List[Any],
        top_n: int,
    ) -> RerankerResult:
        """Rerank using Cohere API"""
        # Prepare documents for Cohere
        documents = []
        for sc in candidates:
            content = sc.chunk.get("content", "")[:1000]  # Limit content length
            documents.append(content)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.cohere.ai/v1/rerank",
                headers={
                    "Authorization": f"Bearer {self.cohere_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "rerank-english-v3.0",
                    "query": query,
                    "documents": documents,
                    "top_n": min(top_n, len(documents)),
                    "return_documents": False,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

        # Reorder candidates based on Cohere results
        reranked = []
        scores = []
        reasons = []

        for result in data.get("results", []):
            idx = result["index"]
            score = result["relevance_score"]
            if idx < len(candidates):
                reranked.append(candidates[idx])
                scores.append(score)
                reasons.append(f"cohere_score={score:.3f}")

        logger.info(f"Cohere reranked {len(reranked)} candidates")

        return RerankerResult(
            chunks=reranked,
            rerank_scores=scores,
            rerank_reasons=reasons,
            method="cohere",
            stats={"cohere_results": len(reranked)},
        )

    async def _rerank_llm(
        self,
        query: str,
        candidates: List[Any],
        top_n: int,
        head_sha: Optional[str] = None,
    ) -> RerankerResult:
        """Rerank using OpenAI LLM"""
        # Build candidate list for prompt
        candidate_texts = []
        for i, sc in enumerate(candidates[:20]):  # Limit to 20 for context window
            chunk = sc.chunk
            source_type = chunk.get("source_type", "unknown")
            content = chunk.get("content", "")[:400]

            # Build citation
            if source_type in ("code", "diff"):
                path = chunk.get("path", "unknown")
                start = chunk.get("start_line")
                end = chunk.get("end_line")
                sha = head_sha[:8] if head_sha else "unknown"
                citation = f"{path}:{start}-{end} @ {sha}"
            elif source_type == "notion":
                citation = chunk.get("url", "unknown")
            else:
                citation = "unknown"

            candidate_texts.append(
                f"[{i}] ({source_type}) {citation}\n{content}"
            )

        candidates_str = "\n\n".join(candidate_texts)

        prompt = f"""You are a code review assistant. Given a query and candidate evidence snippets, select the most relevant ones.

Query: {query}

Candidates:
{candidates_str}

Instructions:
1. Select the top {min(top_n, 10)} most relevant candidates for answering the query
2. Prefer candidates that directly address the query topic
3. Include a mix of code/diff and documentation when relevant
4. Output ONLY valid JSON in this exact format:

{{"selected": [{{"index": 0, "reason": "brief reason"}}, ...]}}

Output:"""

        response = self.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a precise assistant that outputs only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=500,
        )

        response_text = response.choices[0].message.content.strip()

        # Parse JSON response
        try:
            # Handle potential markdown code blocks
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            result = json.loads(response_text)
            selected = result.get("selected", [])
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM rerank response: {e}")
            # Fall back to original order
            return RerankerResult(
                chunks=candidates[:top_n],
                rerank_scores=[1.0] * min(top_n, len(candidates)),
                rerank_reasons=["llm_parse_error"] * min(top_n, len(candidates)),
                method="llm_fallback",
                stats={"parse_error": str(e)},
            )

        # Reorder based on LLM selection
        reranked = []
        scores = []
        reasons = []

        for item in selected:
            idx = item.get("index", -1)
            reason = item.get("reason", "selected")
            if 0 <= idx < len(candidates):
                reranked.append(candidates[idx])
                scores.append(1.0 - len(reranked) * 0.05)  # Decreasing score
                reasons.append(reason)

        logger.info(f"LLM reranked {len(reranked)} candidates")

        return RerankerResult(
            chunks=reranked,
            rerank_scores=scores,
            rerank_reasons=reasons,
            method="llm",
            stats={"llm_selected": len(reranked)},
        )

    def _apply_diversity(
        self,
        chunks: List[Any],
        top_k: int,
        method: str,
    ) -> RerankerResult:
        """
        Apply diversity constraints:
        - Max 2 chunks per unique document
        - Try to include at least 2 distinct source types
        """
        if not ENABLE_DIVERSITY:
            return RerankerResult(
                chunks=chunks[:top_k],
                rerank_scores=[1.0] * min(top_k, len(chunks)),
                rerank_reasons=["no_diversity"] * min(top_k, len(chunks)),
                method=method,
                stats={"diversity_applied": False},
            )

        # Track counts per document
        doc_counts: Dict[str, int] = {}
        source_type_counts: Dict[str, int] = {}

        selected = []
        scores = []
        reasons = []

        for sc in chunks:
            if len(selected) >= top_k:
                break

            doc_key = sc.doc_key
            source_type = sc.source_type

            # Check document limit
            current_doc_count = doc_counts.get(doc_key, 0)
            if current_doc_count >= MAX_CHUNKS_PER_DOC:
                continue

            # Add chunk
            selected.append(sc)
            doc_counts[doc_key] = current_doc_count + 1
            source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1

            scores.append(getattr(sc, 'weighted_score', 1.0))
            reasons.append(f"doc={doc_key[:30]}")

        # Check if we have minimum distinct sources
        distinct_sources = len(source_type_counts)

        stats = {
            "diversity_applied": True,
            "distinct_sources": distinct_sources,
            "source_distribution": source_type_counts,
            "docs_represented": len(doc_counts),
        }

        if distinct_sources < MIN_DISTINCT_SOURCES and len(chunks) > len(selected):
            stats["diversity_warning"] = f"Only {distinct_sources} distinct sources (min: {MIN_DISTINCT_SOURCES})"

        logger.debug(
            f"Diversity applied: {len(selected)} chunks from {len(doc_counts)} docs, "
            f"{distinct_sources} source types"
        )

        return RerankerResult(
            chunks=selected,
            rerank_scores=scores,
            rerank_reasons=reasons,
            method=method,
            stats=stats,
        )
