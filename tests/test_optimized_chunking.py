"""Tests for optimized chunking module."""

import pytest
from pathlib import Path
from factgap.chunking.optimized import (
    ChunkingConfig,
    PathFilter,
    SymbolExtractor,
    LineSpanMapper,
    SemanticChunker,
    load_config
)


class TestChunkingConfig:
    """Test ChunkingConfig class."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = ChunkingConfig.default()
        
        assert 'node_modules/**' in config.ignore_globs
        assert '.git/**' in config.ignore_globs
        assert config.max_file_bytes == 1024 * 1024
        assert config.max_changed_files_indexed == 50
        assert config.max_total_chunks_per_run == 1500
        assert 'code' in config.chunk_sizes
        assert config.chunk_sizes['code']['chunk_size'] == 1200
    
    def test_from_file_missing(self):
        """Test loading config from missing file."""
        config = ChunkingConfig.from_file(Path('/nonexistent/config.yml'))
        # Should return default config
        assert config.max_file_bytes == 1024 * 1024


class TestPathFilter:
    """Test PathFilter class."""
    
    def test_should_skip_node_modules(self):
        """Test that node_modules is skipped."""
        config = ChunkingConfig.default()
        filter = PathFilter(config)
        
        should_skip, reason = filter.should_skip_path(Path('node_modules/package.json'))
        assert should_skip
        assert 'node_modules/**' in reason
    
    def test_should_skip_git(self):
        """Test that .git is skipped."""
        config = ChunkingConfig.default()
        filter = PathFilter(config)
        
        should_skip, reason = filter.should_skip_path(Path('.git/HEAD'))
        assert should_skip
        assert '.git/**' in reason
    
    def test_should_not_skip_source(self):
        """Test that source files are not skipped."""
        config = ChunkingConfig.default()
        filter = PathFilter(config)
        
        should_skip, reason = filter.should_skip_path(Path('src/main.py'))
        assert not should_skip
        assert reason == ""
    
    def test_should_skip_min_js(self):
        """Test that minified JS is skipped."""
        config = ChunkingConfig.default()
        filter = PathFilter(config)
        
        should_skip, reason = filter.should_skip_path(Path('app.min.js'))
        assert should_skip
        assert '*.min.js' in reason
    
    def test_should_skip_size_large_file(self, tmp_path):
        """Test skipping large files."""
        # Create a large file
        large_file = tmp_path / "large.txt"
        large_file.write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB
        
        config = ChunkingConfig.default()
        filter = PathFilter(config)
        
        should_skip, reason = filter.should_skip_size(large_file)
        assert should_skip
        assert "file too large" in reason
    
    def test_should_not_skip_size_small_file(self, tmp_path):
        """Test not skipping small files."""
        small_file = tmp_path / "small.txt"
        small_file.write_bytes(b"x" * 1024)  # 1KB
        
        config = ChunkingConfig.default()
        filter = PathFilter(config)
        
        should_skip, reason = filter.should_skip_size(small_file)
        assert not should_skip
        assert reason == ""


class TestSymbolExtractor:
    """Test SymbolExtractor class."""
    
    def test_extract_python_function(self):
        """Test extracting Python function name."""
        content = """
def calculate_sum(a, b):
    return a + b

def another_function():
    pass
"""
        symbol = SymbolExtractor.extract_symbol(content, 'python', len("def calculate_sum"))
        assert symbol == "function:calculate_sum"
    
    def test_extract_python_class(self):
        """Test extracting Python class name."""
        content = """
class MyClass:
    def method(self):
        pass

def another_function():
    pass
"""
        symbol = SymbolExtractor.extract_symbol(content, 'python', len("class MyClass"))
        assert symbol == "class:MyClass"
    
    def test_extract_js_function(self):
        """Test extracting JavaScript function name."""
        content = """
function myFunction() {
    return true;
}

const myConst = () => {};
"""
        symbol = SymbolExtractor.extract_symbol(content, 'js', len("function myFunction"))
        assert symbol == "function:myFunction"
    
    def test_extract_js_const(self):
        """Test extracting JavaScript const name."""
        content = """
function myFunction() {
    return true;
}

const myConst = () => {};
"""
        symbol = SymbolExtractor.extract_symbol(content, 'js', len("const myConst"))
        assert symbol == "const:myConst"
    
    def test_extract_unknown_language(self):
        """Test extracting symbol from unknown language."""
        content = "some random content"
        symbol = SymbolExtractor.extract_symbol(content, 'unknown', 0)
        assert symbol is None


class TestLineSpanMapper:
    """Test LineSpanMapper class."""
    
    def test_map_simple_chunk(self):
        """Test mapping simple chunk to line spans."""
        content = """line 1
line 2
line 3
line 4"""
        chunk = "line 2\nline 3"
        
        start_line, end_line = LineSpanMapper.map_chunk_with_fallback(content, chunk)
        
        assert start_line == 2
        assert end_line == 3
    
    def test_map_chunk_with_repeated_content(self):
        """Test mapping chunk with repeated content."""
        content = """line 1
repeat
line 2
repeat
line 3"""
        chunk = "repeat"
        
        # Should find first occurrence
        start_line, end_line = LineSpanMapper.map_chunk_with_fallback(content, chunk)
        
        assert start_line == 2
        assert end_line == 2
    
    def test_map_chunk_not_found(self):
        """Test mapping chunk that doesn't exist."""
        content = "line 1\nline 2\nline 3"
        chunk = "not found"
        
        start_line, end_line = LineSpanMapper.map_chunk_with_fallback(content, chunk)
        
        assert start_line is None
        assert end_line is None


class TestSemanticChunker:
    """Test SemanticChunker class."""
    
    def test_create_context_header_code(self):
        """Test creating context header for code."""
        config = ChunkingConfig.default()
        chunker = SemanticChunker(config)
        
        header = chunker.create_context_header(
            source_type='code',
            path='src/main.py',
            language='python',
            symbol='function:calculate_sum'
        )
        
        assert "File: src/main.py" in header
        assert "Language: python" in header
        assert "Symbol: function:calculate_sum" in header
        assert "---" in header
    
    def test_create_context_header_diff(self):
        """Test creating context header for diff."""
        config = ChunkingConfig.default()
        chunker = SemanticChunker(config)
        
        header = chunker.create_context_header(
            source_type='diff',
            path='src/main.py',
            hunk_header='@@ -10,5 +10,7 @@'
        )
        
        assert "Diff for: src/main.py" in header
        assert "Hunk: @@ -10,5 +10,7 @@" in header
        assert "---" in header
    
    def test_create_context_header_notion(self):
        """Test creating context header for Notion."""
        config = ChunkingConfig.default()
        chunker = SemanticChunker(config)
        
        header = chunker.create_context_header(
            source_type='notion',
            title='My Page',
            url='https://notion.so/page',
            last_edited_time='2024-01-15'
        )
        
        assert "Notion: My Page" in header
        assert "URL: https://notion.so/page" in header
        assert "Last edited: 2024-01-15" in header
        assert "---" in header
    
    def test_get_language_by_extension(self):
        """Test getting language by file extension."""
        config = ChunkingConfig.default()
        chunker = SemanticChunker(config)
        
        from langchain_text_splitters import Language
        
        assert chunker.get_language_by_extension(Path('test.py')) == Language.PYTHON
        assert chunker.get_language_by_extension(Path('test.ts')) == Language.TS
        assert chunker.get_language_by_extension(Path('test.js')) == Language.JS
        assert chunker.get_language_by_extension(Path('test.go')) == Language.GO
        assert chunker.get_language_by_extension(Path('test.java')) == Language.JAVA
        assert chunker.get_language_by_extension(Path('test.rs')) == Language.RUST
        assert chunker.get_language_by_extension(Path('test.rb')) == Language.RUBY
        assert chunker.get_language_by_extension(Path('test.txt')) == Language.MARKDOWN  # fallback
    
    def test_prioritize_changed_files(self):
        """Test prioritizing changed files."""
        config = ChunkingConfig.default()
        chunker = SemanticChunker(config)
        
        changed_files = [
            {'path': 'node_modules/package.json', 'size': 1000},
            {'path': 'src/main.py', 'size': 500},
            {'path': 'dist/bundle.js', 'size': 2000},
            {'path': 'README.md', 'size': 300},
            {'path': 'app/component.tsx', 'size': 800},
        ]
        
        prioritized = chunker.prioritize_changed_files(changed_files, max_files=3)
        
        # Should prioritize src/ and app/ files, ignore node_modules and dist
        paths = [f['path'] for f in prioritized]
        assert 'src/main.py' in paths
        assert 'app/component.tsx' in paths
        assert 'README.md' in paths
        assert 'node_modules/package.json' not in paths
        assert 'dist/bundle.js' not in paths


class TestLoadConfig:
    """Test config loading."""
    
    def test_load_default_config(self, tmp_path, monkeypatch):
        """Test loading default config when no config file exists."""
        monkeypatch.chdir(tmp_path)
        
        config = load_config()
        assert isinstance(config, ChunkingConfig)
        assert config.max_file_bytes == 1024 * 1024
