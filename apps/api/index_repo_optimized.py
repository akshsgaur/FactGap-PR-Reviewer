#!/usr/bin/env python3
"""Optimized repository indexing script."""

import argparse
import sys
import os
from pathlib import Path
from typing import Dict, Any

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from app.config import get_settings
from app.database import get_db
from app.services.rag.embeddings import BatchEmbedder, compute_content_hash

# Add factgap to path for optimized chunking
factgap_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(factgap_root / 'factgap'))
from chunking import SemanticChunker, load_config
from discovery import discover_files, DiscoveryConfig


def index_repository(repo_path: str, repo_name: str) -> Dict[str, Any]:
    """Index a repository with optimized chunking."""
    print(f"📁 Indexing repository: {repo_path} as {repo_name}")
    
    # Initialize components
    settings = get_settings()
    db = get_db()
    
    # Initialize OpenAI client
    import openai
    openai_client = openai.OpenAI(api_key=settings.openai_api_key)
    
    # Load optimized chunking configuration
    config = load_config()
    chunker = SemanticChunker(config)
    
    repo_path = Path(repo_path)
    if not repo_path.exists():
        print(f"❌ Error: Repository path {repo_path} does not exist")
        return {"error": "Repository path does not exist"}
    
    # Discover files with fast pruning
    discovery_config = DiscoveryConfig.default()
    # Override include tests from environment
    include_tests = os.getenv('FACTGAP_INCLUDE_TESTS', '').lower() == 'true'
    discovery_config.include_tests = include_tests
    
    files_to_process, discovery_stats = discover_files(repo_path, discovery_config)
    
    print(f"  📊 Discovery summary:")
    print(f"    Directories visited: {discovery_stats.dirs_visited}")
    print(f"    Files seen: {discovery_stats.files_seen}")
    print(f"    Files included: {discovery_stats.files_included}")
    
    # Calculate total skipped
    total_skipped = sum(discovery_stats.skipped_counts.values())
    print(f"    Files skipped: {total_skipped}")
    
    # Show skip reasons
    for reason, count in discovery_stats.skipped_counts.items():
        if count > 0:
            print(f"      {reason}: {count}")
    
    if not files_to_process:
        print("  ⚠️  No files to process")
        return {"files_processed": 0, "chunks_created": 0}
    
    # Initialize batch embedder
    batch_embedder = BatchEmbedder(openai_client, db.client)
    
    processed = 0
    errors = 0
    chunks_by_type = {"code": 0, "repo_doc": 0}
    total_chunks = 0
    
    for file_path in files_to_process:
        try:
            print(f"    📄 Processing {file_path.relative_to(repo_path)}")
            
            # Use optimized chunking
            file_chunks = chunker.chunk_file(
                file_path,
                source_type='code' if file_path.suffix in ['.py', '.js', '.ts', '.go', '.rs', '.java'] else 'repo_doc',
                relative_to=repo_path
            )
            
            # Check chunk cap
            if total_chunks + len(file_chunks) > discovery_config.max_chunks:
                print(f"  ⚠️  Reached chunk cap ({discovery_config.max_chunks}), stopping")
                break
            
            # Prepare batch data
            texts_to_embed = []
            chunk_records = []
            
            for chunk_data in file_chunks:
                enriched_content = chunk_data['content']
                original_content = chunk_data['original_content']
                
                # Determine source type
                source_type = chunk_data['source_type']
                chunks_by_type[source_type] += 1
                
                # Prepare for embedding
                texts_to_embed.append(enriched_content)
                
                # Prepare chunk record
                chunk_record = {
                    'repo': repo_name,
                    'source_type': source_type,
                    'path': chunk_data['path'],
                    'content': enriched_content,
                    'language': chunk_data['language'],
                    'symbol': chunk_data['symbol'],
                    'pr_number': None,
                    'head_sha': None,
                    'start_line': chunk_data['start_line'],
                    'end_line': chunk_data['end_line'],
                    'content_hash': compute_content_hash(original_content),
                    'embedding_model': 'text-embedding-3-small'
                }
                chunk_records.append(chunk_record)
            
            # Batch embed all chunks from this file
            if texts_to_embed:
                embeddings = batch_embedder.embed_batch(texts_to_embed)
                
                # Insert chunks with embeddings
                for i, chunk_record in enumerate(chunk_records):
                    if i < len(embeddings) and embeddings[i] is not None:
                        chunk_record['embedding'] = embeddings[i]
                        result = db.client.table('rag_chunks').insert(chunk_record).execute()
                        
                        if result.data:
                            processed += 1
                        else:
                            errors += 1
                            print(f"      ❌ Failed to insert chunk")
                    else:
                        errors += 1
                        print(f"      ❌ Failed to embed chunk")
                
                total_chunks += len(file_chunks)
            
            print(f"      ✅ Processed {len(file_chunks)} chunks")
            
        except Exception as e:
            errors += 1
            print(f"      ❌ Error processing {file_path}: {e}")
    
    # Print summary
    print(f"\n📊 FINAL SUMMARY:")
    print(f"  Files processed: {len(files_to_process)}")
    print(f"  Chunks created: {total_chunks}")
    print(f"  Errors: {errors}")
    print(f"  Chunks by type: {chunks_by_type}")
    
    return {
        "files_processed": len(files_to_process),
        "chunks_created": total_chunks,
        "errors": errors,
        "chunks_by_type": chunks_by_type,
        "discovery_stats": discovery_stats.summary()
    }


def main():
    parser = argparse.ArgumentParser(description='Optimized repository indexing')
    parser.add_argument('repo_path', help='Path to repository to index')
    parser.add_argument('--repo-name', required=True, help='Repository name for indexing')
    parser.add_argument('--config', help='Path to .factgap/config.yml file')
    
    args = parser.parse_args()
    
    # Override config path if provided
    if args.config:
        os.environ['FACTGAP_CONFIG_PATH'] = args.config
    
    result = index_repository(args.repo_path, args.repo_name)
    
    if "error" in result:
        print(f"❌ {result['error']}")
        sys.exit(1)
    else:
        print(f"\n✅ Indexing completed successfully!")


if __name__ == "__main__":
    main()
