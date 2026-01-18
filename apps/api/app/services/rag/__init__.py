"""RAG (Retrieval-Augmented Generation) services for FactGap"""

from app.services.rag.intent import IntentClassifier, QueryIntent, IntentResult
from app.services.rag.retrieval import ScopedRetriever, RetrievalScope, ScopeType, ScoredChunk
from app.services.rag.reranker import Reranker, RerankerResult
from app.services.rag.enrichment import ChunkEnricher, EnrichedChunk, extract_symbol_from_chunk
from app.services.rag.embeddings import BatchEmbedder, EmbedFunction, EmbedResult, compute_content_hash
from app.services.rag.logging import RAGLogger, RetrievalLogEntry, ChunkLogEntry, rag_logger

__all__ = [
    # Intent classification
    "IntentClassifier",
    "QueryIntent",
    "IntentResult",
    # Retrieval
    "ScopedRetriever",
    "RetrievalScope",
    "ScopeType",
    "ScoredChunk",
    # Reranking
    "Reranker",
    "RerankerResult",
    # Enrichment
    "ChunkEnricher",
    "EnrichedChunk",
    "extract_symbol_from_chunk",
    # Embeddings
    "BatchEmbedder",
    "EmbedFunction",
    "EmbedResult",
    "compute_content_hash",
    # Logging
    "RAGLogger",
    "RetrievalLogEntry",
    "ChunkLogEntry",
    "rag_logger",
]
