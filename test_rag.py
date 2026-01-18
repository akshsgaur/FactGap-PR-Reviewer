#!/usr/bin/env python3
"""
Test script for FactGap RAG pipeline.

Usage:
    python test_rag.py index                      # Index codebase + Notion into Supabase
    python test_rag.py query                      # Interactive query with RAG generation
    python test_rag.py both                       # Index then query
    python test_rag.py ask "your question here"   # Direct query (no interactive mode)

Add --verbose or -v for detailed logging.
"""

import os
import sys
import asyncio
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from factgap.db.supabase_client import get_supabase_manager, ChunkRecord
from factgap.chunking.splitters import CodeChunker, DocumentChunker
from factgap.notion.client import NotionClient
import openai

# Check for verbose flag
VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv
if VERBOSE:
    sys.argv = [arg for arg in sys.argv if arg not in ["--verbose", "-v"]]


def log(msg: str, indent: int = 0):
    """Print verbose log message."""
    if VERBOSE:
        prefix = "   " * indent + "│ " if indent else ""
        print(f"\033[90m{prefix}{msg}\033[0m")


def log_step(step: str):
    """Print a step header."""
    if VERBOSE:
        print(f"\n\033[94m┌─ {step}\033[0m")


def log_end(msg: str):
    """Print step completion."""
    if VERBOSE:
        print(f"\033[94m└─ {msg}\033[0m")


def log_data(label: str, value, indent: int = 1):
    """Print a labeled data value."""
    if VERBOSE:
        prefix = "   " * indent + "│ "
        print(f"\033[90m{prefix}{label}: \033[93m{value}\033[0m")


# Initialize clients
def get_clients():
    log_step("Initializing Clients")

    start = time.time()
    log("Creating Supabase manager...", 1)
    manager = get_supabase_manager()
    log_data("Supabase URL", os.getenv("SUPABASE_URL", "")[:50] + "...")

    log("Creating OpenAI client...", 1)
    openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    log_data("OpenAI model for embeddings", "text-embedding-3-small")

    notion_client = None
    notion_token = os.getenv("NOTION_TOKEN")
    if notion_token and notion_token != "your-notion-integration-token":
        log("Creating Notion client...", 1)
        notion_client = NotionClient(notion_token)
    else:
        log("Notion client skipped (no valid token)", 1)

    log_end(f"Clients initialized in {time.time() - start:.2f}s")

    return manager, openai_client, notion_client


async def index_codebase(manager, repo_root: str, repo_name: str = "factgap-pr-reviewer"):
    """Index all Python files and documentation."""
    print("\n📂 Indexing codebase...")
    log_step("Codebase Indexing")

    chunks = []
    code_chunker = CodeChunker()
    doc_chunker = DocumentChunker()

    log_data("Code chunker settings", f"chunk_size=1200, overlap=150")
    log_data("Doc chunker settings", f"chunk_size=1000, overlap=150")

    # Index Python files
    python_files = list(Path(repo_root).rglob("*.py"))
    python_files = [f for f in python_files if "__pycache__" not in str(f) and ".venv" not in str(f)]
    print(f"   Found {len(python_files)} Python files")

    total_chars = 0
    total_chunks = 0
    embed_time = 0

    for file_path in python_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            relative_path = str(file_path.relative_to(repo_root))
            total_chars += len(content)

            log(f"Processing: {relative_path}", 1)
            log_data("File size", f"{len(content)} chars", 2)

            file_chunks = code_chunker.chunk_file(relative_path, content)
            log_data("Chunks created", len(file_chunks), 2)

            for chunk_text, start_line, end_line in file_chunks:
                if not chunk_text.strip():
                    continue

                embed_start = time.time()
                embedding = manager.embed_text(chunk_text)
                embed_time += time.time() - embed_start

                chunk_record = ChunkRecord(
                    repo=repo_name,
                    source_type="code",
                    path=relative_path,
                    language="python",
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_text,
                    content_hash=manager.compute_content_hash(chunk_text),
                    embedding=embedding,
                )
                chunks.append(chunk_record)
                total_chunks += 1

            print(f"   ✓ {relative_path}")
        except Exception as e:
            print(f"   ✗ {file_path}: {e}")

    # Index markdown docs
    doc_files = list(Path(repo_root).glob("*.md")) + list(Path(repo_root).rglob("docs/**/*.md"))
    print(f"\n   Found {len(doc_files)} markdown files")

    for file_path in doc_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            relative_path = str(file_path.relative_to(repo_root))
            total_chars += len(content)

            log(f"Processing: {relative_path}", 1)

            file_chunks = doc_chunker.chunk_document(content)
            log_data("Chunks created", len(file_chunks), 2)

            for chunk_text, start_line, end_line in file_chunks:
                if not chunk_text.strip():
                    continue

                embed_start = time.time()
                embedding = manager.embed_text(chunk_text)
                embed_time += time.time() - embed_start

                chunk_record = ChunkRecord(
                    repo=repo_name,
                    source_type="repo_doc",
                    path=relative_path,
                    language="markdown",
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_text,
                    content_hash=manager.compute_content_hash(chunk_text),
                    embedding=embedding,
                )
                chunks.append(chunk_record)
                total_chunks += 1

            print(f"   ✓ {relative_path}")
        except Exception as e:
            print(f"   ✗ {file_path}: {e}")

    log_data("Total characters processed", f"{total_chars:,}")
    log_data("Total chunks created", total_chunks)
    log_data("Total embedding time", f"{embed_time:.2f}s")
    log_data("Avg embedding time per chunk", f"{embed_time/max(total_chunks,1)*1000:.1f}ms")

    # Upsert to Supabase
    print(f"\n   Upserting {len(chunks)} chunks to Supabase...")
    log_step("Supabase Upsert")

    upsert_start = time.time()
    stats = await manager.upsert_chunks(chunks)
    upsert_time = time.time() - upsert_start

    log_data("Upsert time", f"{upsert_time:.2f}s")
    log_data("Chunks upserted", stats['upserted'])
    log_data("Chunks skipped (duplicates)", stats['skipped'])
    log_end(f"Indexing complete")

    print(f"   ✓ Upserted: {stats['upserted']}, Skipped: {stats['skipped']}")

    return stats


async def index_notion(manager, notion_client, repo_name: str = "factgap-pr-reviewer"):
    """Index Notion pages."""
    page_ids_str = os.getenv("NOTION_PAGE_IDS", "")
    page_ids = [pid.strip() for pid in page_ids_str.split(",") if pid.strip()]

    # Filter out placeholder values
    page_ids = [pid for pid in page_ids if not pid.startswith("page-id")]

    if not page_ids:
        print("\n📝 Skipping Notion indexing (no valid page IDs configured)")
        return {"upserted": 0, "skipped": 0}

    print(f"\n📝 Indexing {len(page_ids)} Notion pages...")
    log_step("Notion Indexing")

    chunks = []
    doc_chunker = DocumentChunker()

    for page_id in page_ids:
        try:
            log(f"Fetching page: {page_id}", 1)
            fetch_start = time.time()
            page_data = await notion_client.get_page_content(page_id)
            log_data("Fetch time", f"{time.time() - fetch_start:.2f}s", 2)
            log_data("Content length", f"{len(page_data['content'])} chars", 2)

            file_chunks = doc_chunker.chunk_document(page_data["content"])
            log_data("Chunks created", len(file_chunks), 2)

            for chunk_text, start_line, end_line in file_chunks:
                if not chunk_text.strip():
                    continue

                embedding = manager.embed_text(chunk_text)

                chunk_record = ChunkRecord(
                    repo=repo_name,
                    source_type="notion",
                    source_id=page_id,
                    url=page_data.get("url"),
                    last_edited_time=page_data.get("last_edited_time"),
                    start_line=start_line,
                    end_line=end_line,
                    content=chunk_text,
                    content_hash=manager.compute_content_hash(chunk_text),
                    embedding=embedding,
                )
                chunks.append(chunk_record)

            print(f"   ✓ Page {page_id}")
        except Exception as e:
            print(f"   ✗ Page {page_id}: {e}")

    if chunks:
        print(f"\n   Upserting {len(chunks)} Notion chunks to Supabase...")
        stats = await manager.upsert_chunks(chunks)
        print(f"   ✓ Upserted: {stats['upserted']}, Skipped: {stats['skipped']}")
        return stats

    return {"upserted": 0, "skipped": 0}


async def query_with_rag(manager, openai_client, query: str, repo_name: str = "factgap-pr-reviewer"):
    """Query with RAG-augmented generation."""
    print(f"\n🔍 Searching for: {query}")

    # ===== STEP 1: Embed the query =====
    log_step("Step 1: Query Embedding")
    log_data("Query text", query[:100] + "..." if len(query) > 100 else query)
    log_data("Query length", f"{len(query)} chars")

    embed_start = time.time()
    query_embedding = manager.embed_text(query)
    embed_time = time.time() - embed_start

    log_data("Embedding model", "text-embedding-3-small")
    log_data("Embedding dimensions", len(query_embedding))
    log_data("Embedding time", f"{embed_time*1000:.1f}ms")
    log_data("Embedding sample", f"[{query_embedding[0]:.4f}, {query_embedding[1]:.4f}, ..., {query_embedding[-1]:.4f}]")
    log_end("Query embedded")

    # ===== STEP 2: Vector search in Supabase =====
    log_step("Step 2: Vector Search (Supabase)")
    log_data("Repository filter", repo_name)
    log_data("Source types", ["code", "repo_doc", "notion"])
    log_data("Top-K", 5)
    log_data("Min score threshold", 0.3)

    search_start = time.time()
    results = await manager.search_chunks(
        query_embedding=query_embedding,
        repo=repo_name,
        source_types=["code", "repo_doc", "notion"],
        k=5,
        min_score=0.3
    )
    search_time = time.time() - search_start

    log_data("Search time", f"{search_time*1000:.1f}ms")
    log_data("Results returned", len(results))
    log_end("Vector search complete")

    if not results:
        print("   No relevant chunks found.")
        return None

    print(f"\n📚 Found {len(results)} relevant chunks:")

    # ===== STEP 3: Build context from results =====
    log_step("Step 3: Context Building")

    context_parts = []
    total_context_chars = 0

    for i, result in enumerate(results, 1):
        source_type = result.get("source_type", "unknown")
        path = result.get("path", "")
        content = result.get("content", "")
        score = result.get("score", 0)

        if source_type == "code":
            start_line = result.get("start_line", "?")
            end_line = result.get("end_line", "?")
            source_ref = f"{path}:{start_line}-{end_line}"
        elif source_type == "notion":
            source_ref = f"Notion: {result.get('url', result.get('source_id', 'unknown'))}"
        else:
            source_ref = path or "unknown"

        print(f"   {i}. [{source_type}] {source_ref} (score: {score:.3f})")

        log(f"Chunk {i}:", 1)
        log_data("Source", source_ref, 2)
        log_data("Score", f"{score:.4f}", 2)
        log_data("Content length", f"{len(content)} chars", 2)
        log_data("Preview", content[:80].replace('\n', ' ') + "...", 2)

        context_parts.append(f"--- Source: {source_ref} ({source_type}) ---\n{content}")
        total_context_chars += len(content)

    context = "\n\n".join(context_parts)

    log_data("Total context length", f"{total_context_chars:,} chars")
    log_data("Estimated tokens", f"~{total_context_chars // 4}")
    log_end("Context built")

    # ===== STEP 4: Generate response with OpenAI =====
    log_step("Step 4: LLM Generation (OpenAI)")
    print("\n🤖 Generating response...")

    system_prompt = """You are a helpful code assistant. Answer questions based on the provided context from the codebase and documentation.

Rules:
1. Only use information from the provided context
2. If the context doesn't contain enough information, say so
3. Cite your sources using the format: [source_type: path]
4. Be concise and accurate"""

    user_prompt = f"""Context:
{context}

Question: {query}

Please provide a helpful answer based on the context above."""

    log_data("Model", "gpt-4o")
    log_data("Temperature", 0.3)
    log_data("Max tokens", 1000)
    log_data("System prompt length", f"{len(system_prompt)} chars")
    log_data("User prompt length", f"{len(user_prompt)} chars")
    log_data("Total prompt tokens (est)", f"~{(len(system_prompt) + len(user_prompt)) // 4}")

    if VERBOSE:
        print(f"\n\033[94m┌─ Full Prompt to OpenAI ─────────────────────────────────────\033[0m")
        print(f"\033[95m[SYSTEM]\033[0m")
        print(f"\033[90m{system_prompt}\033[0m")
        print(f"\n\033[95m[USER]\033[0m")
        print(f"\033[90m{user_prompt}\033[0m")
        print(f"\033[94m└─────────────────────────────────────────────────────────────\033[0m")

    log("\nSending request to OpenAI...", 1)

    gen_start = time.time()
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        max_tokens=1000
    )
    gen_time = time.time() - gen_start

    answer = response.choices[0].message.content

    log_data("Generation time", f"{gen_time:.2f}s")
    log_data("Response length", f"{len(answer)} chars")
    log_data("Prompt tokens", response.usage.prompt_tokens)
    log_data("Completion tokens", response.usage.completion_tokens)
    log_data("Total tokens", response.usage.total_tokens)
    log_data("Finish reason", response.choices[0].finish_reason)
    log_end("Generation complete")

    # ===== STEP 5: Return answer =====
    log_step("Step 5: Response Summary")
    log_data("Total pipeline time", f"{embed_time + search_time + gen_time:.2f}s")
    log_data("  - Embedding", f"{embed_time*1000:.1f}ms")
    log_data("  - Vector search", f"{search_time*1000:.1f}ms")
    log_data("  - LLM generation", f"{gen_time*1000:.1f}ms")
    log_end("Pipeline complete")

    print(f"\n💬 Answer:\n{answer}")

    return answer


async def interactive_query(manager, openai_client):
    """Interactive query loop."""
    print("\n" + "="*60)
    print("🔮 Interactive RAG Query Mode")
    print("   Type your questions, or 'quit' to exit")
    if VERBOSE:
        print("   (Verbose logging enabled)")
    print("="*60)

    while True:
        print()
        query = input("❓ Your question: ").strip()

        if query.lower() in ["quit", "exit", "q"]:
            print("👋 Goodbye!")
            break

        if not query:
            continue

        await query_with_rag(manager, openai_client, query)


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    repo_root = Path(__file__).parent.absolute()

    print("🚀 FactGap RAG Test")
    print(f"   Repository: {repo_root}")
    if VERBOSE:
        print("   Verbose mode: ON")

    manager, openai_client, notion_client = get_clients()
    print("   ✓ Clients initialized")

    if command in ["index", "both"]:
        await index_codebase(manager, str(repo_root))
        if notion_client:
            await index_notion(manager, notion_client)
        print("\n✅ Indexing complete!")

    if command in ["query", "both"]:
        await interactive_query(manager, openai_client)

    if command == "ask":
        if len(sys.argv) < 3:
            print("Error: Please provide a question after 'ask'")
            print("Usage: python test_rag.py ask \"your question here\"")
            sys.exit(1)
        question = " ".join(sys.argv[2:])
        await query_with_rag(manager, openai_client, question)

    if command not in ["index", "query", "both", "ask"]:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
