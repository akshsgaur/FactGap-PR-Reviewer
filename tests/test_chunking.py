"""Tests for chunking functionality"""

import pytest
from factgap.chunking.splitters import (
    CodeChunker,
    DiffChunker,
    DocumentChunker,
    chunk_with_line_spans,
    get_language_from_extension
)


class TestChunking:
    """Test chunking utilities"""
    
    def test_get_language_from_extension(self):
        """Test language detection from file extensions"""
        assert get_language_from_extension("test.py") is not None
        assert get_language_from_extension("test.js") is not None
        assert get_language_from_extension("test.ts") is not None
        assert get_language_from_extension("test.unknown") is None
        assert get_language_from_extension("test") is None
    
    def test_chunk_with_line_spans_basic(self):
        """Test basic line span mapping"""
        text = """line 1
line 2
line 3
line 4"""
        
        chunks = ["line 1\nline 2", "line 3\nline 4"]
        results = chunk_with_line_spans(text, chunks)
        
        assert len(results) == 2
        assert results[0] == ("line 1\nline 2", 1, 2)
        assert results[1] == ("line 3\nline 4", 3, 4)
    
    def test_chunk_with_line_spans_empty(self):
        """Test line span mapping with empty input"""
        results = chunk_with_line_spans("", [])
        assert results == []
    
    def test_chunk_with_line_spans_not_found(self):
        """Test line span mapping when chunk not found"""
        text = "line 1\nline 2\nline 3"
        chunks = ["nonexistent chunk"]
        results = chunk_with_line_spans(text, chunks)
        
        assert len(results) == 1
        assert results[0] == ("nonexistent chunk", None, None)
    
    def test_code_chunker_python(self):
        """Test Python code chunking"""
        code = """def hello_world():
    print("Hello, World!")
    return True

class TestClass:
    def method(self):
        pass"""
        
        chunker = CodeChunker(chunk_size=100, chunk_overlap=20)
        chunks = chunker.chunk_file("test.py", code)
        
        assert len(chunks) > 0
        for chunk_text, start_line, end_line in chunks:
            assert isinstance(chunk_text, str)
            assert start_line is None or isinstance(start_line, int)
            assert end_line is None or isinstance(end_line, int)
            if start_line and end_line:
                assert start_line <= end_line
    
    def test_code_chunker_unknown_language(self):
        """Test code chunking with unknown language"""
        code = "some random content\nwith multiple lines"
        
        chunker = CodeChunker(chunk_size=50, chunk_overlap=10)
        chunks = chunker.chunk_file("test.unknown", code)
        
        assert len(chunks) > 0
    
    def test_diff_chunker(self):
        """Test diff chunking"""
        diff = """diff --git a/test.py b/test.py
index 123..456 100644
--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 def old_func():
-    print("old")
+    print("new")
+    return True
@@ -10,2 +11,3 @@
 class OldClass:
-    pass
+    def new_method(self):
+    return 42"""
        
        chunker = DiffChunker(chunk_size=200, chunk_overlap=50)
        chunks = chunker.chunk_diff(diff)
        
        assert len(chunks) > 0
        for chunk_text, start_line, end_line in chunks:
            assert isinstance(chunk_text, str)
            # Check for diff indicators (either "diff" or "@@")
            assert any(indicator in chunk_text for indicator in ["diff", "@@", "---", "+++"])
    
    def test_document_chunker(self):
        """Test document chunking"""
        doc = """# Title

This is a paragraph with multiple lines.
It should be chunked properly.

## Subsection

- Item 1
- Item 2
- Item 3

More content here."""
        
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
        chunks = chunker.chunk_document(doc)
        
        assert len(chunks) > 0
        for chunk_text, start_line, end_line in chunks:
            assert isinstance(chunk_text, str)
            assert len(chunk_text) <= 100 + 20  # Allow for overlap
    
    def test_chunking_determinism(self):
        """Test that chunking is deterministic"""
        code = """def function1():
    return "test"

def function2():
    return "another test"

def function3():
    return "final test" """
        
        chunker = CodeChunker(chunk_size=80, chunk_overlap=10)
        chunks1 = chunker.chunk_file("test.py", code)
        chunks2 = chunker.chunk_file("test.py", code)
        
        # Should produce identical results
        assert len(chunks1) == len(chunks2)
        for (c1, s1, e1), (c2, s2, e2) in zip(chunks1, chunks2):
            assert c1 == c2
            assert s1 == s2
            assert e1 == e2
