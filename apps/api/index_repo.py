#!/usr/bin/env python3
"""Index local repository into rag_chunks table."""

import argparse
import sys
import os
from pathlib import Path

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import openai
from app.config import get_settings
from app.database import get_db
from app.services.rag.enrichment import ChunkEnricher, extract_symbol_from_chunk
from app.services.rag.embeddings import BatchEmbedder, compute_content_hash
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language


def index_repository(repo_path: str, repo_name: str):
    """Index a local repository into rag_chunks table"""
    print(f"📁 Indexing repository: {repo_path} as {repo_name}")
    
    # Initialize components
    settings = get_settings()
    db = get_db()
    enricher = ChunkEnricher()
    openai_client = openai.OpenAI(api_key=settings.openai_api_key)
    batch_embedder = BatchEmbedder(openai_client, db.client)
    
    repo_path = Path(repo_path)
    if not repo_path.exists():
        print(f"❌ Error: Repository path {repo_path} does not exist")
        return
    
    # Find all supported files
    supported_extensions = {'.py', '.js', '.ts', '.tsx', '.jsx', '.md', '.txt', '.go', '.rs', '.java'}
    
    files_to_process = []
    for file_path in repo_path.rglob('*'):
        if file_path.is_file() and file_path.suffix in supported_extensions:
            files_to_process.append(file_path)
    
    print(f"  Found {len(files_to_process)} files to process")
    
    processed = 0
    errors = 0
    
    for file_path in files_to_process:
        try:
            print(f"    📄 Processing {file_path.relative_to(repo_path)}")
            
            # Read file content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Skip empty files
            if not content.strip():
                print(f"      ⏭️  Skipping empty file")
                continue
            
            # Determine language and split into chunks
            if file_path.suffix in ['.py', '.js', '.ts', '.go', '.rs', '.java']:
                language = file_path.suffix[1:]  # Remove dot
                splitter = RecursiveCharacterTextSplitter.from_language(
                    getattr(Language, language.upper(), Language.PYTHON)
                )
            else:
                language = None
                splitter = RecursiveCharacterTextSplitter.from_language(Language.MARKDOWN)
            
            # Split content
            chunks = splitter.split_text(content)
            
            # Process each chunk
            for i, chunk_text in enumerate(chunks):
                if not chunk_text.strip():
                    continue
                
                # Enrich content
                if language:
                    symbol = extract_symbol_from_chunk(chunk_text, language)
                    enriched = enricher.enrich_code_chunk(
                        content=chunk_text,
                        path=str(file_path.relative_to(repo_path)),
                        language=language,
                        start_line=None,
                        end_line=None,
                        symbol=symbol
                    )
                else:
                    enriched = enricher.enrich_repo_doc_chunk(
                        content=chunk_text,
                        path=str(file_path.relative_to(repo_path))
                    )
                
                # Generate embedding
                embedding = batch_embedder.embed_single(enriched.enriched_content)
                
                # Insert into database
                chunk_data = {
                    'repo': repo_name,
                    'source_type': 'code' if language else 'repo_doc',
                    'path': str(file_path.relative_to(repo_path)),
                    'content': enriched.enriched_content,
                    'embedding': embedding,
                    'language': language,
                    'symbol': getattr(enriched, 'symbol', None),
                    'pr_number': None,
                    'head_sha': None,
                    'start_line': None,
                    'end_line': None,
                    'content_hash': compute_content_hash(chunk_text),
                    'embedding_model': 'text-embedding-3-small'
                }
                
                result = db.client.table('rag_chunks').insert(chunk_data).execute()
                
                if result.data:
                    processed += 1
                else:
                    errors += 1
                    print(f"      ❌ Failed to insert chunk")
            
            print(f"      ✅ Processed {len(chunks)} chunks")
            
        except Exception as e:
            errors += 1
            print(f"      ❌ Error processing {file_path}: {e}")
    
    print(f"\n📊 SUMMARY: {len(files_to_process)} files, {processed} chunks processed, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description='Index repository into rag_chunks table')
    parser.add_argument('repo_path', help='Path to repository to index')
    parser.add_argument('--repo-name', required=True, help='Repository name for indexing')
    
    args = parser.parse_args()
    
    index_repository(args.repo_path, args.repo_name)


if __name__ == "__main__":
    main()
