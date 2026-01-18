-- Create users table for multi-tenant SaaS
CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    github_id bigint UNIQUE NOT NULL,
    github_login text NOT NULL,
    github_access_token text,              -- Encrypted
    github_app_installation_id bigint,
    notion_access_token text,              -- Encrypted
    notion_workspace_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Create index for GitHub App installation lookup
CREATE INDEX IF NOT EXISTS idx_users_github_id ON users (github_id);
CREATE INDEX IF NOT EXISTS idx_users_installation_id ON users (github_app_installation_id);

-- Create trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
