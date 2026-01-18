-- Create rag_chunks table for RAG storage
CREATE TABLE IF NOT EXISTS rag_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repo text NOT NULL,
    pr_number int NULL,
    head_sha text NULL,
    source_type text NOT NULL,        -- code | diff | repo_doc | notion
    source_id text NULL,              -- e.g., notion page_id
    path text NULL,                   -- repo file path
    language text NULL,               -- python/typescript/etc
    symbol text NULL,                 -- optional: function/class name if easily derived
    start_line int NULL,
    end_line int NULL,
    url text NULL,                    -- notion page url
    last_edited_time timestamptz NULL,
    content text NOT NULL,
    content_hash text NOT NULL,       -- sha256 of normalized content
    embedding vector(1536) NOT NULL,
    embedding_model text NOT NULL,    -- e.g. text-embedding-3-small
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Create unique constraint for upserts
CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_chunks_unique 
ON rag_chunks (repo, pr_number, head_sha, source_type, COALESCE(path, source_id), start_line, end_line, content_hash);

-- Create HNSW index for similarity search
CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding 
ON rag_chunks USING hnsw (embedding vector_cosine_ops);

-- Create B-tree indexes for common queries
CREATE INDEX IF NOT EXISTS idx_rag_chunks_repo_pr_sha 
ON rag_chunks (repo, pr_number, head_sha);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_repo_source_type 
ON rag_chunks (repo, source_type);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_source_type 
ON rag_chunks (source_type);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_source_id 
ON rag_chunks (source_id);

-- Enable vector extension if not already enabled
CREATE EXTENSION IF NOT EXISTS vector;
