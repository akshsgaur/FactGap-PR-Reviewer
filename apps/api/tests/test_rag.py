"""Tests for RAG modules"""

import pytest
from unittest.mock import Mock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.services.rag.intent import IntentClassifier, QueryIntent
from app.services.rag.enrichment import (
    ChunkEnricher, EnrichedChunk, extract_symbol_from_chunk
)
from app.services.rag.embeddings import compute_content_hash, BatchEmbedder


class TestIntentClassifier:
    """Tests for IntentClassifier"""

    def setup_method(self):
        self.classifier = IntentClassifier()

    def test_classify_standards_policy(self):
        """Test that standards/policy queries are classified correctly"""
        result = self.classifier.classify("What are our naming conventions?")
        assert result.intent == QueryIntent.STANDARDS_POLICY
        assert result.confidence > 0
        assert "conventions" in result.matched_keywords

    def test_classify_implementation_debug(self):
        """Test that implementation/debug queries are classified correctly"""
        result = self.classifier.classify("How does the authentication function work?")
        assert result.intent == QueryIntent.IMPLEMENTATION_DEBUG
        assert result.confidence > 0
        assert "how does" in result.matched_keywords or "function" in result.matched_keywords

    def test_classify_process(self):
        """Test that process queries are classified correctly"""
        result = self.classifier.classify("What is the deployment process?")
        assert result.intent == QueryIntent.PROCESS
        assert result.confidence > 0
        assert "deployment" in result.matched_keywords or "deploy" in result.matched_keywords

    def test_classify_general(self):
        """Test that general queries fall back to GENERAL intent"""
        result = self.classifier.classify("Hello world")
        assert result.intent == QueryIntent.GENERAL
        assert result.confidence == 0.0
        assert len(result.matched_keywords) == 0

    def test_scope_weights_standards(self):
        """Test that standards queries weight Notion higher"""
        result = self.classifier.classify("What are our coding standards?")
        weights = result.scope_weights
        assert weights["notion"] > weights["code"]
        assert weights["notion"] > weights["diff"]

    def test_scope_weights_implementation(self):
        """Test that implementation queries weight code higher"""
        result = self.classifier.classify("How to implement this function?")
        weights = result.scope_weights
        assert weights["code"] > weights["notion"]
        assert weights["diff"] > weights["notion"]


class TestChunkEnricher:
    """Tests for ChunkEnricher"""

    def setup_method(self):
        self.enricher = ChunkEnricher()

    def test_enrich_code_chunk_basic(self):
        """Test basic code chunk enrichment"""
        result = self.enricher.enrich_code_chunk(
            content="def hello():\n    print('world')",
            path="src/hello.py",
            language="python",
        )

        assert isinstance(result, EnrichedChunk)
        assert "File: src/hello.py" in result.enriched_content
        assert "Language: python" in result.enriched_content
        assert "def hello():" in result.enriched_content

    def test_enrich_code_chunk_with_symbol(self):
        """Test code chunk enrichment with symbol"""
        result = self.enricher.enrich_code_chunk(
            content="class MyClass:\n    pass",
            path="src/myclass.py",
            language="python",
            symbol="MyClass",
        )

        assert "Symbol: MyClass" in result.enriched_content

    def test_enrich_code_chunk_with_context(self):
        """Test code chunk enrichment with context for early chunks"""
        full_content = "import os\nimport sys\n\ndef main():\n    pass"
        result = self.enricher.enrich_code_chunk(
            content="def main():\n    pass",
            path="src/main.py",
            language="python",
            start_line=4,
            end_line=5,
            full_file_content=full_content,
        )

        assert "Context:" in result.enriched_content
        assert "import os" in result.enriched_content

    def test_enrich_diff_chunk(self):
        """Test diff chunk enrichment"""
        diff_content = "diff --git a/src/app.py b/src/app.py\n@@ -1,5 +1,6 @@\n+import new_module"

        result = self.enricher.enrich_diff_chunk(
            content=diff_content,
            path="src/app.py",
        )

        assert "Diff for: src/app.py" in result.enriched_content
        assert diff_content in result.enriched_content

    def test_enrich_notion_chunk(self):
        """Test Notion chunk enrichment"""
        result = self.enricher.enrich_notion_chunk(
            content="Our coding standards require...",
            title="Coding Standards",
            url="https://notion.so/page",
            last_edited_time="2024-01-15",
        )

        assert "Notion: Coding Standards" in result.enriched_content
        assert "URL: https://notion.so/page" in result.enriched_content
        assert "Last edited: 2024-01-15" in result.enriched_content


class TestExtractSymbol:
    """Tests for extract_symbol_from_chunk"""

    def test_extract_python_function(self):
        """Test extracting Python function name"""
        code = "def my_function():\n    pass"
        result = extract_symbol_from_chunk(code, "python")
        assert result == "my_function"

    def test_extract_python_async_function(self):
        """Test extracting Python async function name"""
        code = "async def async_handler():\n    pass"
        result = extract_symbol_from_chunk(code, "python")
        assert result == "async_handler"

    def test_extract_python_class(self):
        """Test extracting Python class name"""
        code = "class MyClass:\n    pass"
        result = extract_symbol_from_chunk(code, "python")
        assert result == "MyClass"

    def test_extract_typescript_function(self):
        """Test extracting TypeScript function name"""
        code = "function handleClick() {\n    // ...\n}"
        result = extract_symbol_from_chunk(code, "ts")
        assert result == "handleClick"

    def test_extract_go_function(self):
        """Test extracting Go function name"""
        code = "func HandleRequest(w http.ResponseWriter) {\n}"
        result = extract_symbol_from_chunk(code, "go")
        assert result == "HandleRequest"

    def test_extract_no_symbol(self):
        """Test returns None when no symbol found"""
        code = "# Just a comment\nprint('hello')"
        result = extract_symbol_from_chunk(code, "python")
        assert result is None


class TestComputeContentHash:
    """Tests for compute_content_hash"""

    def test_same_content_same_hash(self):
        """Test that same content produces same hash"""
        content = "def hello(): pass"
        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Test that different content produces different hash"""
        hash1 = compute_content_hash("content 1")
        hash2 = compute_content_hash("content 2")
        assert hash1 != hash2

    def test_hash_is_hex_string(self):
        """Test that hash is a valid hex string"""
        result = compute_content_hash("test content")
        assert all(c in "0123456789abcdef" for c in result)
        assert len(result) == 64  # SHA-256 produces 64 hex chars


class TestBatchEmbedder:
    """Tests for BatchEmbedder"""

    def setup_method(self):
        self.mock_openai = Mock()
        self.embedder = BatchEmbedder(self.mock_openai, batch_size=2)

    def test_embed_single(self):
        """Test embedding a single text"""
        self.mock_openai.embeddings.create.return_value = Mock(
            data=[Mock(embedding=[0.1, 0.2, 0.3])]
        )

        result = self.embedder.embed_single("test text")

        assert result == [0.1, 0.2, 0.3]
        self.mock_openai.embeddings.create.assert_called_once()

    def test_embed_batch_empty(self):
        """Test embedding empty list returns empty list"""
        result = self.embedder.embed_batch([])
        assert result == []

    def test_embed_batch_single_batch(self):
        """Test embedding texts that fit in one batch"""
        self.mock_openai.embeddings.create.return_value = Mock(
            data=[
                Mock(index=0, embedding=[0.1, 0.2]),
                Mock(index=1, embedding=[0.3, 0.4]),
            ]
        )

        result = self.embedder.embed_batch(["text1", "text2"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]

    def test_embed_batch_multiple_batches(self):
        """Test embedding texts that span multiple batches"""
        self.mock_openai.embeddings.create.side_effect = [
            Mock(data=[
                Mock(index=0, embedding=[0.1]),
                Mock(index=1, embedding=[0.2]),
            ]),
            Mock(data=[
                Mock(index=0, embedding=[0.3]),
            ]),
        ]

        result = self.embedder.embed_batch(["a", "b", "c"])

        assert len(result) == 3
        assert result[0] == [0.1]
        assert result[1] == [0.2]
        assert result[2] == [0.3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
