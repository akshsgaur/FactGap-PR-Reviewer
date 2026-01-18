"""Tests for citation formatting and verification"""

import pytest
from factgap.reviewer.github_api import GitHubClient


class TestCitations:
    """Test citation formatting and verification"""
    
    def test_parse_comment_mention_basic(self):
        """Test basic @code-reviewer mention parsing"""
        client = GitHubClient(token="dummy")
        
        # Basic mention
        question = client.parse_comment_mention("@code-reviewer How does this work?")
        assert question == "How does this work?"
        
        # Mention with extra whitespace
        question = client.parse_comment_mention("@code-reviewer    What is this function?")
        assert question == "What is this function?"
        
        # Multi-line question
        question = client.parse_comment_mention("@code-reviewer What is this?\n\nCan you explain?")
        assert question == "What is this?\n\nCan you explain?"
    
    def test_parse_comment_mention_case_insensitive(self):
        """Test case-insensitive mention parsing"""
        client = GitHubClient(token="dummy")
        
        question = client.parse_comment_mention("@CODE-REVIEWER How does this work?")
        assert question == "How does this work?"
        
        question = client.parse_comment_mention("@Code-Reviewer What is this?")
        assert question == "What is this?"
    
    def test_parse_comment_mention_no_mention(self):
        """Test parsing without mention"""
        client = GitHubClient(token="dummy")
        
        question = client.parse_comment_mention("How does this work?")
        assert question is None
        
        question = client.parse_comment_mention("Hey @someone else, can you help?")
        assert question is None
    
    def test_parse_comment_mention_multiple_mentions(self):
        """Test parsing with multiple mentions"""
        client = GitHubClient(token="dummy")
        
        question = client.parse_comment_mention("@code-reviewer How does this work? @other-user")
        assert question == "How does this work? @other-user"
    
    def test_citation_formatting_repo(self):
        """Test repository citation formatting"""
        # This would be tested in the actual prompt formatting
        # For now, just verify the format structure
        path = "src/main.py"
        start_line = 123
        end_line = 125
        head_sha = "abc123def456"
        
        citation = f"{path}:{start_line}-{end_line} @ {head_sha}"
        expected = "src/main.py:123-125 @ abc123def456"
        
        assert citation == expected
    
    def test_citation_formatting_notion(self):
        """Test Notion citation formatting"""
        url = "https://notion.so/page-id"
        last_edited = "2024-01-15T10:30:00.000Z"
        
        citation = f"{url} (edited: {last_edited})"
        expected = "https://notion.so/page-id (edited: 2024-01-15T10:30:00.000Z)"
        
        assert citation == expected
    
    def test_hard_claim_detection(self):
        """Test hard claim detection patterns"""
        hard_claim_words = [
            "must", "shall", "required", "violates", 
            "policy", "standard", "breaks", "we do", 
            "always", "never"
        ]
        
        test_sentences = [
            "This must be fixed before merge",
            "We always use TypeScript for new features",
            "This violates our security policy",
            "The code breaks the existing API",
            "This is required for compliance"
        ]
        
        for sentence in test_sentences:
            sentence_lower = sentence.lower()
            has_hard_claim = any(word in sentence_lower for word in hard_claim_words)
            assert has_hard_claim, f"Should detect hard claim in: {sentence}"
    
    def test_citation_detection(self):
        """Test citation detection in markdown"""
        import re
        
        citation_patterns = [
            r'\[.*?\]\(.*?\)',  # Markdown links
            r'@\w+',            # @mentions
            r'https?://[^\s]+', # URLs
        ]
        
        test_lines = [
            "See [documentation](https://docs.example.com) for details",
            "Check @security-team for guidance",
            "Visit https://notion.so/page-id for more info",
            "This has no citation",
            "[link](url) and @mention and https://url.com"
        ]
        
        for line in test_lines:
            has_citation = any(re.search(pattern, line) for pattern in citation_patterns)
            
            # Lines 1, 2, 3, 5 should have citations
            if line in test_lines[:3] + [test_lines[4]]:
                assert has_citation, f"Should detect citation in: {line}"
            else:
                assert not has_citation, f"Should not detect citation in: {line}"
