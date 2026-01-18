-- Add user_id column to rag_chunks for multi-tenancy
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES users(id);

-- Create index for user_id
CREATE INDEX IF NOT EXISTS idx_rag_chunks_user_id ON rag_chunks (user_id);

-- Create composite index for user-scoped queries
CREATE INDEX IF NOT EXISTS idx_rag_chunks_user_repo ON rag_chunks (user_id, repo);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_user_source_type ON rag_chunks (user_id, source_type);
