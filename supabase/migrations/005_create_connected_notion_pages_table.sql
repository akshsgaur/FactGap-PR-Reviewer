-- Create connected_notion_pages table for tracking enabled Notion pages
CREATE TABLE IF NOT EXISTS connected_notion_pages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notion_page_id text NOT NULL,
    notion_page_title text,
    is_active boolean DEFAULT true,
    indexing_status text DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(user_id, notion_page_id)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_connected_notion_pages_user_id ON connected_notion_pages (user_id);
CREATE INDEX IF NOT EXISTS idx_connected_notion_pages_page_id ON connected_notion_pages (notion_page_id);

-- Create trigger to auto-update updated_at
CREATE TRIGGER update_connected_notion_pages_updated_at
    BEFORE UPDATE ON connected_notion_pages
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
