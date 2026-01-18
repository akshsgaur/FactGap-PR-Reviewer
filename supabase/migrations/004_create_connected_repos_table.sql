-- Create connected_repos table for tracking enabled repositories
CREATE TABLE IF NOT EXISTS connected_repos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    github_repo_id bigint NOT NULL,
    repo_full_name text NOT NULL,          -- "owner/repo"
    is_active boolean DEFAULT true,
    indexing_status text DEFAULT 'pending',
    last_indexed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(user_id, github_repo_id)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_connected_repos_user_id ON connected_repos (user_id);
CREATE INDEX IF NOT EXISTS idx_connected_repos_full_name ON connected_repos (repo_full_name);
CREATE INDEX IF NOT EXISTS idx_connected_repos_active ON connected_repos (is_active);

-- Create trigger to auto-update updated_at
CREATE TRIGGER update_connected_repos_updated_at
    BEFORE UPDATE ON connected_repos
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
