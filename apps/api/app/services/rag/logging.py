"""Pipeline logging for RAG retrieval and reranking"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Feature flag for verbose logging
ENABLE_RAG_LOGGING = os.getenv("FACTGAP_ENABLE_RAG_LOGGING", "true").lower() == "true"
LOG_LEVEL = os.getenv("FACTGAP_RAG_LOG_LEVEL", "INFO")


@dataclass
class RetrievalLogEntry:
    """Log entry for a retrieval operation"""
    timestamp: str
    query: str
    query_length: int
    intent: str
    intent_confidence: float
    scope_stats: Dict[str, Any]
    total_candidates: int
    merged_candidates: int
    rerank_method: str
    final_count: int
    source_distribution: Dict[str, int]
    latency_ms: Optional[float] = None


@dataclass
class ChunkLogEntry:
    """Log entry for individual chunk details"""
    rank: int
    source_type: str
    doc_key: str
    raw_score: float
    normalized_score: float
    weighted_score: float
    rerank_score: Optional[float] = None
    rerank_reason: Optional[str] = None


class RAGLogger:
    """
    Logger for RAG pipeline operations.

    Logs retrieval stats, reranking decisions, and chunk details
    for debugging and evaluation.
    """

    def __init__(self, log_level: str = LOG_LEVEL):
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.enabled = ENABLE_RAG_LOGGING

    def log_retrieval(
        self,
        query: str,
        intent_result,  # IntentResult
        retrieval_stats: Dict[str, Any],
        rerank_result,  # RerankerResult
        latency_ms: Optional[float] = None,
    ) -> Optional[RetrievalLogEntry]:
        """
        Log a complete retrieval operation.

        Returns the log entry for potential storage.
        """
        if not self.enabled:
            return None

        # Build source distribution
        source_distribution = {}
        for chunk in rerank_result.chunks:
            st = chunk.source_type
            source_distribution[st] = source_distribution.get(st, 0) + 1

        entry = RetrievalLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            query=query[:200],  # Truncate long queries
            query_length=len(query),
            intent=intent_result.intent.value,
            intent_confidence=intent_result.confidence,
            scope_stats=retrieval_stats.get("scopes", {}),
            total_candidates=retrieval_stats.get("total_candidates", 0),
            merged_candidates=retrieval_stats.get("merged_candidates", 0),
            rerank_method=rerank_result.method,
            final_count=len(rerank_result.chunks),
            source_distribution=source_distribution,
            latency_ms=latency_ms,
        )

        # Log at appropriate level
        if self.log_level <= logging.DEBUG:
            logger.debug(f"RAG Retrieval: {json.dumps(asdict(entry), indent=2)}")
        else:
            logger.info(
                f"RAG Retrieval: intent={entry.intent} "
                f"candidates={entry.total_candidates} "
                f"final={entry.final_count} "
                f"method={entry.rerank_method} "
                f"sources={entry.source_distribution}"
            )

        return entry

    def log_chunks(
        self,
        chunks,  # List[ScoredChunk]
        rerank_scores: List[float],
        rerank_reasons: List[str],
    ) -> List[ChunkLogEntry]:
        """
        Log individual chunk details for debugging.

        Only logs at DEBUG level.
        """
        if not self.enabled or self.log_level > logging.DEBUG:
            return []

        entries = []
        for i, chunk in enumerate(chunks):
            rerank_score = rerank_scores[i] if i < len(rerank_scores) else None
            rerank_reason = rerank_reasons[i] if i < len(rerank_reasons) else None

            entry = ChunkLogEntry(
                rank=i + 1,
                source_type=chunk.source_type,
                doc_key=chunk.doc_key[:50],  # Truncate
                raw_score=chunk.raw_score,
                normalized_score=chunk.normalized_score,
                weighted_score=chunk.weighted_score,
                rerank_score=rerank_score,
                rerank_reason=rerank_reason,
            )
            entries.append(entry)

            logger.debug(
                f"  [{i+1}] {entry.source_type} | {entry.doc_key} | "
                f"raw={entry.raw_score:.3f} norm={entry.normalized_score:.3f} "
                f"weighted={entry.weighted_score:.3f}"
            )

        return entries

    def format_eval_output(
        self,
        retrieval_entry: RetrievalLogEntry,
        chunk_entries: List[ChunkLogEntry],
    ) -> str:
        """Format entries for eval CLI output"""
        lines = [
            "=" * 60,
            f"Query: {retrieval_entry.query}",
            f"Intent: {retrieval_entry.intent} (confidence: {retrieval_entry.intent_confidence:.2f})",
            f"Candidates: {retrieval_entry.total_candidates} → {retrieval_entry.merged_candidates} → {retrieval_entry.final_count}",
            f"Method: {retrieval_entry.rerank_method}",
            f"Sources: {retrieval_entry.source_distribution}",
            "-" * 60,
            "Top chunks:",
        ]

        for entry in chunk_entries[:10]:  # Show top 10
            lines.append(
                f"  [{entry.rank}] {entry.source_type:10} | {entry.doc_key[:40]:40} | "
                f"score={entry.weighted_score:.3f}"
            )

        lines.append("=" * 60)
        return "\n".join(lines)


# Global logger instance
rag_logger = RAGLogger()
