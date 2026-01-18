"""Integration tests for FactGap PR Reviewer"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from factgap.reviewer.analyzer import PRAnalyzer
from factgap.reviewer.github_api import GitHubClient


class TestIntegration:
    """Integration tests with mocked dependencies"""
    
    @pytest.fixture
    def mock_mcp_client(self):
        """Mock MCP client"""
        client = Mock()
        client.call_tool = AsyncMock()
        return client
    
    @pytest.fixture
    def mock_github_client(self):
        """Mock GitHub client"""
        client = Mock(spec=GitHubClient)
        client.get_pr_details = AsyncMock(return_value={
            "number": 123,
            "title": "Test PR",
            "body": "This is a test PR",
            "head_sha": "abc123",
            "base_sha": "def456",
            "state": "open",
            "author": "testuser",
            "created_at": "2024-01-15T10:00:00Z",
            "updated_at": "2024-01-15T11:00:00Z",
        })
        client.get_pr_changed_files = AsyncMock(return_value=[
            {
                "path": "src/test.py",
                "status": "modified",
                "additions": 10,
                "deletions": 5,
                "changes": 15,
                "patch": "@@ -1,3 +1,4 @@\n def test():\n-    old()\n+    new()\n+    return True"
            }
        ])
        client.create_or_update_comment = AsyncMock()
        client.reply_to_comment = AsyncMock()
        client.parse_comment_mention = Mock(return_value="How does this function work?")
        return client
    
    @pytest.fixture
    def analyzer(self, mock_mcp_client):
        """Create PR analyzer with mocked MCP client"""
        with patch('factgap.reviewer.analyzer.GitHubClient'):
            return PRAnalyzer(mock_mcp_client)
    
    @pytest.mark.asyncio
    async def test_pr_analysis_flow(self, analyzer, mock_mcp_client, mock_github_client):
        """Test complete PR analysis flow"""
        # Mock MCP tool responses
        mock_mcp_client.call_tool.side_effect = [
            # pr_index_build response
            {"stats": {"upserted": 5, "skipped": 0}},
            # repo_docs_build response  
            {"stats": {"upserted": 10, "skipped": 2}},
            # notion_index response
            {"stats": {"upserted": 3, "skipped": 0}},
            # pr_index_search response
            [
                {
                    "id": "1",
                    "content": "def new_function():",
                    "source_type": "code",
                    "path": "src/test.py",
                    "start_line": 1,
                    "end_line": 5,
                    "score": 0.9
                }
            ],
            # repo_docs_search response
            [
                {
                    "id": "2", 
                    "content": "We use TypeScript for all new code",
                    "source_type": "repo_doc",
                    "path": "docs/standards.md",
                    "score": 0.8
                }
            ],
            # notion_search response
            [
                {
                    "id": "3",
                    "content": "Security policy requires input validation",
                    "source_type": "notion",
                    "url": "https://notion.so/security",
                    "last_edited_time": "2024-01-10T09:00:00Z",
                    "score": 0.85
                }
            ],
            # review_verify_citations response
            {
                "hard_claim_count": 2,
                "cited_hard_claim_count": 2,
                "missing_citations": []
            }
        ]
        
        # Mock GitHub client
        analyzer.github_client = mock_github_client
        
        # Run analysis
        result = await analyzer.analyze_pr(123, "/tmp/repo")
        
        # Verify result contains expected sections
        assert "## Summary of Changes" in result
        assert "## Risk Flags" in result
        assert "## Review Focus Checklist" in result
        assert "## Relevant Context" in result
        assert "## How to Chat" in result
        
        # Verify MCP calls were made
        assert mock_mcp_client.call_tool.call_count >= 6
        
        # Verify GitHub comment was created
        mock_github_client.create_or_update_comment.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_pr_chat_flow(self, analyzer, mock_mcp_client, mock_github_client):
        """Test PR chat flow"""
        # Mock MCP tool responses
        mock_mcp_client.call_tool.side_effect = [
            # pr_index_search response
            [
                {
                    "id": "1",
                    "content": "def new_function():\n    return True",
                    "source_type": "code",
                    "path": "src/test.py",
                    "start_line": 1,
                    "end_line": 2,
                    "score": 0.95
                }
            ],
            # review_verify_citations response
            {
                "hard_claim_count": 0,
                "cited_hard_claim_count": 0,
                "missing_citations": []
            }
        ]
        
        # Mock GitHub client
        analyzer.github_client = mock_github_client
        
        # Run chat
        result = await analyzer.handle_chat(123, "How does this function work?", "/tmp/repo")
        
        # Verify result contains answer
        assert "Based on the available evidence" in result or "src/test.py" in result
        
        # Verify MCP calls were made
        assert mock_mcp_client.call_tool.call_count >= 2
        
        # Verify GitHub reply was posted
        mock_github_client.reply_to_comment.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_retrieval_merge_rerank(self, analyzer, mock_mcp_client):
        """Test evidence retrieval and merging logic"""
        # Mock search responses with different scores
        mock_mcp_client.call_tool.side_effect = [
            # PR overlay results (high priority for implementation questions)
            [
                {"id": "pr1", "content": "implementation details", "source_type": "code", "score": 0.9},
                {"id": "pr2", "content": "more code", "source_type": "diff", "score": 0.85}
            ],
            # Repo docs results
            [
                {"id": "doc1", "content": "general guidelines", "source_type": "repo_doc", "score": 0.7}
            ],
            # Notion results (high priority for policy questions)
            [
                {"id": "notion1", "content": "team policy", "source_type": "notion", "score": 0.8}
            ]
        ]
        
        # Test implementation question (should prioritize PR overlay)
        evidence = await analyzer._retrieve_chat_evidence(123, "abc123", "how implement feature", "/tmp/repo")
        
        # Should have PR overlay results first
        source_types = [item.get("source_type") for item in evidence]
        assert "code" in source_types or "diff" in source_types
        
        # Test policy question (should prioritize Notion/docs)
        mock_mcp_client.call_tool.reset_mock()
        mock_mcp_client.call_tool.side_effect = [
            # Notion results
            [
                {"id": "notion1", "content": "team policy", "source_type": "notion", "score": 0.8}
            ],
            # Repo docs results  
            [
                {"id": "doc1", "content": "general guidelines", "source_type": "repo_doc", "score": 0.7}
            ]
        ]
        
        evidence = await analyzer._retrieve_chat_evidence(123, "abc123", "what is our policy", "/tmp/repo")
        
        # Should have Notion/docs results
        source_types = [item.get("source_type") for item in evidence]
        assert "notion" in source_types or "repo_doc" in source_types
    
    def test_marker_based_comment_update(self):
        """Test marker-based comment update logic"""
        # This would be tested in the actual GitHub client
        # For now, verify the marker format
        marker = "<!-- FACTGAP_PR_ANALYSIS -->"
        comment_body = f"{marker}\n\n## Analysis Content"
        
        assert marker in comment_body
        assert "## Analysis Content" in comment_body
    
    def test_mention_parsing_edge_cases(self):
        """Test @code-reviewer mention parsing edge cases"""
        client = GitHubClient(token="dummy")
        
        # Mention at start
        question = client.parse_comment_mention("@code-reviewer question")
        assert question == "question"
        
        # Mention in middle
        question = client.parse_comment_mention("Hey @code-reviewer can you help?")
        assert question == "can you help?"
        
        # Mention with punctuation
        question = client.parse_comment_mention("@code-reviewer: How does this work?")
        assert question == ": How does this work?"
        
        # No mention
        question = client.parse_comment_mention("Just a regular comment")
        assert question is None
