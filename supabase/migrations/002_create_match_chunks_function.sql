-- RPC function for similarity search
CREATE OR REPLACE FUNCTION match_chunks(
    p_query_embedding vector(1536),
    p_k int DEFAULT 10,
    p_min_score float DEFAULT 0.7,
    p_repo text DEFAULT NULL,
    p_pr_number int DEFAULT NULL,
    p_head_sha text DEFAULT NULL,
    p_source_types text[] DEFAULT NULL,
    p_filters jsonb DEFAULT '{}'::jsonb
)
RETURNS TABLE (
    id uuid,
    content text,
    repo text,
    pr_number int,
    head_sha text,
    source_type text,
    path text,
    start_line int,
    end_line int,
    url text,
    last_edited_time timestamptz,
    language text,
    symbol text,
    score float
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        rc.id,
        rc.content,
        rc.repo,
        rc.pr_number,
        rc.head_sha,
        rc.source_type,
        rc.path,
        rc.start_line,
        rc.end_line,
        rc.url,
        rc.last_edited_time,
        rc.language,
        rc.symbol,
        1 - (rc.embedding <=> p_query_embedding) as score
    FROM rag_chunks rc
    WHERE 
        (p_repo IS NULL OR rc.repo = p_repo)
        AND (p_pr_number IS NULL OR rc.pr_number = p_pr_number)
        AND (p_head_sha IS NULL OR rc.head_sha = p_head_sha)
        AND (p_source_types IS NULL OR rc.source_type = ANY(p_source_types))
        AND (1 - (rc.embedding <=> p_query_embedding)) >= p_min_score
        AND CASE 
            WHEN jsonb_typeof(p_filters) = 'object' THEN (
                (p_filters->>'path' IS NULL OR rc.path ILIKE '%' || (p_filters->>'path') || '%')
                AND (p_filters->>'language' IS NULL OR rc.language = p_filters->>'language')
                AND (p_filters->>'symbol' IS NULL OR rc.symbol ILIKE '%' || (p_filters->>'symbol') || '%')
            )
            ELSE true
        END
    ORDER BY rc.embedding <=> p_query_embedding
    LIMIT p_k;
END;
$$ LANGUAGE plpgsql;
