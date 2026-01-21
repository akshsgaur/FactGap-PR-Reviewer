# AGENTS.md - FactGap API

This file provides guidance for AI coding agents working with the FactGap API backend.

## Current Status

**RAG Improvements Sprint: COMPLETE** 
**User Dependencies Cleanup: COMPLETE** 
**Debug Tools: COMPLETE** 
**CLI Tools: COMPLETE** 

The FactGap PR Reviewer now has a fully functional RAG system with complete debugging capabilities!

## Overview

The API is a FastAPI backend that powers the FactGap PR Reviewer SaaS. It handles:
- GitHub App OAuth and webhook processing
- Notion OAuth integration
- Repository and Notion page indexing
- PR analysis and @code-reviewer chat
- RAG (Retrieval-Augmented Generation) pipeline

## Project Structure

```
apps/api/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Settings with pydantic-settings
│   ├── database.py          # Supabase operations
│   ├── auth.py              # JWT token handling
│   ├── models.py            # Pydantic models
│   ├── routes/
│   │   ├── auth.py          # GitHub/Notion OAuth
│   │   ├── repos.py         # Repository management
│   │   ├── notion.py        # Notion pages
│   │   └── webhooks.py      # GitHub webhooks
│   ├── services/
│   │   ├── github_app.py    # GitHub API operations
│   │   ├── notion_oauth.py  # Notion API operations
│   │   ├── indexing.py      # Indexing pipeline (uses enrichment)
│   │   ├── analysis.py      # PR analysis + chat (uses new RAG)
│   │   └── rag/             # RAG modules (NEW)
│   │       ├── __init__.py  # Exports all RAG classes
│   │       ├── intent.py    # IntentClassifier, QueryIntent
│   │       ├── retrieval.py # ScopedRetriever, ScoredChunk
│   │       ├── reranker.py  # Reranker (Cohere + LLM)
│   │       ├── enrichment.py# ChunkEnricher
│   │       ├── embeddings.py# BatchEmbedder, EmbedFunction
│   │       └── logging.py   # RAGLogger
│   └── cli/
│       └── eval_smoke.py    # RAG evaluation CLI
├── tests/
│   └── test_rag.py          # RAG module tests
├── compare_rag.py           # Compare OLD vs NEW pipeline
├── check_data.py            # Check Supabase data
├── test_rag_local.py        # Test RAG without database
└── requirements.txt
```

## RAG Pipeline Architecture

```
Query → Intent Classification → Scoped Retrieval → Score Normalization
                                       ↓
                              Weight by Intent
                                       ↓
                              Merge & Dedupe
                                       ↓
                              Rerank (Cohere/LLM)
                                       ↓
                              Apply Diversity
                                       ↓
                              Final Results
```

### RAG Modules

| Module | Class | Purpose |
|--------|-------|---------|
| `intent.py` | `IntentClassifier` | Classify query intent (standards, implementation, process, general) |
| `retrieval.py` | `ScopedRetriever` | Multi-scope search with score normalization |
| `reranker.py` | `Reranker` | Cohere API + LLM fallback reranking |
| `enrichment.py` | `ChunkEnricher` | Add contextual prefixes before embedding |
| `embeddings.py` | `BatchEmbedder` | Batch embedding with identity skip |
| `logging.py` | `RAGLogger` | Pipeline logging and metrics |

## How to Implement

### 1. Using the RAG Pipeline in Code

```python
from app.services.rag import (
    ScopedRetriever,
    Reranker,
    EmbedFunction,
    RAGLogger,
)

# Initialize
openai_client = openai.OpenAI(api_key=settings.openai_api_key)
embed_fn = EmbedFunction(openai_client)
retriever = ScopedRetriever(supabase_client, embed_fn.embed)
reranker = Reranker(openai_client)
rag_logger = RAGLogger()

# Retrieve and rerank
candidates, intent_result, stats = await retriever.retrieve(
    query="How does authentication work?",
    user_id=user_id,
    repo="owner/repo",
    pr_number=123,
    head_sha="abc123",
    top_k=40,
)

rerank_result = await reranker.rerank(
    query="How does authentication work?",
    candidates=candidates,
    top_k=8,
)

# Log results
rag_logger.log_retrieval(query, intent_result, stats, rerank_result)

# Use results
for chunk in rerank_result.chunks:
    print(chunk.chunk["content"])
```

### 2. Using Enrichment During Indexing

```python
from app.services.rag import ChunkEnricher, extract_symbol_from_chunk

enricher = ChunkEnricher()

# For code chunks
symbol = extract_symbol_from_chunk(code_content, "python")
enriched = enricher.enrich_code_chunk(
    content=code_content,
    path="src/auth.py",
    language="python",
    start_line=10,
    end_line=50,
    full_file_content=full_file,
    symbol=symbol,
)
# Embed enriched.enriched_content, store original code_content

# For Notion chunks
enriched = enricher.enrich_notion_chunk(
    content=notion_content,
    title="Auth Standards",
    url="https://notion.so/page",
    last_edited_time="2024-01-15",
)
```

### 3. Using Batch Embeddings

```python
from app.services.rag import BatchEmbedder, compute_content_hash

embedder = BatchEmbedder(openai_client, supabase_client)

# Compute hashes for identity check
texts = ["chunk1", "chunk2", "chunk3"]
hashes = [compute_content_hash(t) for t in texts]

# Embed with skip logic
result = await embedder.embed_with_skip(
    texts=texts,
    content_hashes=hashes,
    user_id=user_id,
)

# result.embeddings[i] is None if skipped, List[float] if embedded
# result.skipped_indices shows which were skipped
# result.stats has counts
```

### 4. Running the Eval CLI

```bash
# Set environment variables
export SUPABASE_URL=...
export SUPABASE_SERVICE_ROLE_KEY=...
export OPENAI_API_KEY=...

# Run with default test queries
python -m app.cli.eval_smoke --user-id <uuid>

# Run with custom queries
python -m app.cli.eval_smoke --user-id <uuid> --query "How does auth work?"

# Run with repo/PR context
python -m app.cli.eval_smoke --user-id <uuid> --repo owner/repo --pr-number 123

# Verbose output
python -m app.cli.eval_smoke --user-id <uuid> --verbose

# JSON output
python -m app.cli.eval_smoke --user-id <uuid> --json
```

## Feature Flags

All new features are controlled by environment variables for gradual rollout:

| Flag | Default | Description |
|------|---------|-------------|
| `FACTGAP_ENABLE_ENRICHMENT` | `true` | Use contextual chunk enrichment |
| `FACTGAP_ENABLE_BATCH_EMBED` | `true` | Use batch embeddings |
| `FACTGAP_ENABLE_RERANK` | `true` | Use Cohere/LLM reranking |
| `FACTGAP_ENABLE_DIVERSITY` | `true` | Apply diversity constraints |
| `FACTGAP_ENABLE_INTENT_ROUTING` | `true` | Use intent-based routing |
| `FACTGAP_ENABLE_NEW_RAG` | `true` | Use new RAG pipeline in analysis |
| `FACTGAP_ENABLE_RAG_LOGGING` | `true` | Enable pipeline logging |
| `FACTGAP_EMBED_BATCH_SIZE` | `32` | Batch size for embeddings |
| `FACTGAP_RAG_LOG_LEVEL` | `INFO` | Log level (DEBUG for chunk details) |
| `COHERE_API_KEY` | - | Required for Cohere reranking |

## Intent Categories

The intent classifier uses keyword matching to route queries:

| Intent | Keywords (partial) | Scope Weights |
|--------|-------------------|---------------|
| `STANDARDS_POLICY` | standard, policy, convention, best practice | notion: 1.5, repo_doc: 1.3, code: 0.7 |
| `IMPLEMENTATION_DEBUG` | error, bug, how does, implement, function | code: 1.5, diff: 1.4, notion: 0.6 |
| `PROCESS` | deploy, incident, runbook, approval, merge | notion: 1.5, repo_doc: 1.4, code: 0.5 |
| `GENERAL` | (no match) | all: 1.0 |

## Diversity Constraints

The reranker applies these constraints to final results:

- **Max chunks per document**: 2 (prevents one file dominating)
- **Min distinct source types**: 2 (ensures variety)

## Quick Start - Testing RAG

```bash
cd apps/api

# 1. Check what data exists in Supabase
python check_data.py

# 2. Compare OLD vs NEW RAG pipeline (no user_id needed)
python compare_rag.py

# 3. With custom queries
python compare_rag.py -q "How does chunking work?" -q "What is in the README?"

# 4. Filter by repo
python compare_rag.py --repo factgap-pr-reviewer

# 5. Run unit tests (no database needed)
pytest tests/test_rag.py -v
```

**Note:** The comparison uses the original `match_chunks` function (no user_id required).
Set `min_score` lower (e.g., 0.3) if you get no results.

## Common Tasks

### Adding a New Intent Category

1. Add to `QueryIntent` enum in `intent.py`
2. Add keywords to `INTENT_KEYWORDS` dict
3. Add scope weights to `INTENT_SCOPE_WEIGHTS` dict
4. Update tests in `test_rag.py`

### Adding a New Source Type

1. Add enrichment method to `ChunkEnricher` in `enrichment.py`
2. Update `_enrich_*_content` helper in `indexing.py`
3. Add to `INTENT_SCOPE_WEIGHTS` for all intents

### Tuning Reranking

1. Adjust `MAX_CHUNKS_PER_DOC` and `MIN_DISTINCT_SOURCES` in `reranker.py`
2. Modify Cohere model in `_rerank_cohere` (currently `rerank-english-v3.0`)
3. Adjust LLM prompt in `_rerank_llm` for different selection criteria

## Environment Variables (Full List)

```bash
# Required
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
OPENAI_API_KEY=sk-...

# GitHub App
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
GITHUB_APP_CLIENT_ID=Iv1.xxx
GITHUB_APP_CLIENT_SECRET=xxx
GITHUB_WEBHOOK_SECRET=xxx

# Notion
NOTION_CLIENT_ID=xxx
NOTION_CLIENT_SECRET=xxx

# Auth
JWT_SECRET=your-secret-key

# Optional - Reranking
COHERE_API_KEY=xxx

# Optional - Feature Flags (see table above)
FACTGAP_ENABLE_NEW_RAG=true
FACTGAP_ENABLE_RERANK=true
# ... etc
```
