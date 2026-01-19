"""Tests for fast file discovery module."""

import pytest
import tempfile
import shutil
from pathlib import Path
from factgap.discovery.fast import (
    DiscoveryConfig,
    FileDiscoveryStats,
    discover_files,
    is_hidden_directory,
    matches_glob,
    should_ignore_directory,
    should_ignore_file,
    is_binary_file,
    is_supported_extension,
    is_test_file,
    path_is_under_include_root
)


class TestDiscoveryConfig:
    """Test DiscoveryConfig class."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = DiscoveryConfig.default()
        
        assert 'factgap/' in config.include_roots
        assert 'apps/' in config.include_roots
        assert 'README.md' in config.include_roots
        assert 'node_modules/**' in config.ignore_globs
        assert '.git/**' in config.ignore_globs
        assert config.max_files == 800
        assert config.max_chunks == 5000
        assert config.max_file_bytes == 1024 * 1024
        assert config.include_tests is False


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_is_hidden_directory(self):
        """Test hidden directory detection."""
        assert is_hidden_directory(Path('.git')) is True
        assert is_hidden_directory(Path('.github')) is False  # Exception
        assert is_hidden_directory(Path('src')) is False
        assert is_hidden_directory(Path('.pytest_cache')) is True
    
    def test_matches_glob(self):
        """Test glob matching."""
        assert matches_glob('node_modules/package.json', 'node_modules/**') is True
        assert matches_glob('src/main.py', 'node_modules/**') is False
        assert matches_glob('test.py', '*.py') is True
        assert matches_glob('dir/test.py', '*.py') is False
        assert matches_glob('dir/test.py', '**/*.py') is True
    
    def test_is_supported_extension(self):
        """Test supported extension detection."""
        assert is_supported_extension(Path('test.py')) is True
        assert is_supported_extension(Path('test.js')) is True
        assert is_supported_extension(Path('test.ts')) is True
        assert is_supported_extension(Path('test.md')) is True
        assert is_supported_extension(Path('test.txt')) is True
        assert is_supported_extension(Path('test.go')) is True
        assert is_supported_extension(Path('test.rs')) is True
        assert is_supported_extension(Path('test.java')) is True
        assert is_supported_extension(Path('test.exe')) is False
        assert is_supported_extension(Path('test.dll')) is False
        assert is_supported_extension(Path('test.so')) is False
    
    def test_is_test_file(self):
        """Test test file detection."""
        assert is_test_file(Path('test_main.py')) is True
        assert is_test_file(Path('main_test.py')) is True
        assert is_test_file(Path('test/main.py')) is True
        assert is_test_file(Path('tests/main.py')) is True
        assert is_test_file(Path('src/main.py')) is False
        assert is_test_file(Path('src/test_helper.py')) is True
        assert is_test_file(Path('component.test.js')) is True
    
    def test_is_binary_file(self, tmp_path):
        """Test binary file detection."""
        # Create text file
        text_file = tmp_path / "text.txt"
        text_file.write_text("This is text content")
        assert is_binary_file(text_file) is False
        
        # Create binary file
        binary_file = tmp_path / "binary.bin"
        binary_file.write_bytes(b"This is text\x00 with null byte")
        assert is_binary_file(binary_file) is True
    
    def test_path_is_under_include_root(self):
        """Test include root checking."""
        config = DiscoveryConfig.default()
        repo_root = Path("/repo")
        
        # Directory include roots
        assert path_is_under_include_root(repo_root / "factgap" / "chunking.py", repo_root, config) is True
        assert path_is_under_include_root(repo_root / "apps" / "api" / "main.py", repo_root, config) is True
        assert path_is_under_include_root(repo_root / "vendor" / "lib.py", repo_root, config) is False
        
        # Single file include roots
        assert path_is_under_include_root(repo_root / "README.md", repo_root, config) is True
        assert path_is_under_include_root(repo_root / "CLAUDE.md", repo_root, config) is True
        assert path_is_under_include_root(repo_root / "random.txt", repo_root, config) is False


class TestShouldIgnore:
    """Test ignore functions."""
    
    def test_should_ignore_directory(self):
        """Test directory ignore logic."""
        config = DiscoveryConfig.default()
        repo_root = Path("/repo")
        
        # Hidden directories (except .github)
        assert should_ignore_directory(Path('.git'), Path('.git'), config)[0] is True
        assert should_ignore_directory(Path('.github'), Path('.github'), config)[0] is False
        assert should_ignore_directory(Path('.pytest_cache'), Path('.pytest_cache'), config)[0] is True
        
        # Ignore globs
        assert should_ignore_directory(Path('node_modules'), Path('node_modules'), config)[0] is True
        assert should_ignore_directory(Path('dist'), Path('dist'), config)[0] is True
        assert should_ignore_directory(Path('src'), Path('src'), config)[0] is False
    
    def test_should_ignore_file(self):
        """Test file ignore logic."""
        config = DiscoveryConfig.default()
        
        # Ignore globs
        assert should_ignore_file(Path('package-lock.json'), Path('package-lock.json'), config)[0] is True
        assert should_ignore_file(Path('yarn.lock'), Path('yarn.lock'), config)[0] is True
        assert should_ignore_file(Path('main.py'), Path('main.py'), config)[0] is False


class TestDiscoverFiles:
    """Test file discovery with pruning."""
    
    def test_discover_files_basic(self, tmp_path):
        """Test basic file discovery."""
        # Create test structure
        (tmp_path / "factgap").mkdir()
        (tmp_path / "factgap" / "chunking.py").write_text("# chunking module")
        (tmp_path / "apps" / "api").mkdir(parents=True)
        (tmp_path / "apps" / "api" / "main.py").write_text("# main module")
        (tmp_path / "README.md").write_text("# README")
        (tmp_path / "node_modules" / "package.json").mkdir(parents=True)
        (tmp_path / "node_modules" / "package.json").write_text("{}")
        (tmp_path / ".git" / "config").mkdir(parents=True)
        (tmp_path / ".git" / "config").write_text("git config")
        
        config = DiscoveryConfig.default()
        files, stats = discover_files(tmp_path, config)
        
        # Should include files from include roots
        file_paths = [f.relative_to(tmp_path) for f in files]
        assert Path("factgap/chunking.py") in file_paths
        assert Path("apps/api/main.py") in file_paths
        assert Path("README.md") in file_paths
        
        # Should not include ignored directories
        assert Path("node_modules/package.json") not in file_paths
        assert Path(".git/config") not in file_paths
        
        # Stats should show pruning
        assert stats.skipped_counts['ignored_dir_pruned'] > 0
        assert stats.files_included > 0
    
    def test_discover_files_with_tests(self, tmp_path):
        """Test file discovery with tests excluded/included."""
        # Create test structure
        (tmp_path / "factgap").mkdir()
        (tmp_path / "factgap" / "main.py").write_text("# main module")
        (tmp_path / "factgap" / "test_main.py").write_text("# test")
        (tmp_path / "tests" / "test_api.py").mkdir(parents=True)
        (tmp_path / "tests" / "test_api.py").write_text("# test")
        (tmp_path / "apps" / "api" / "main.py").mkdir(parents=True)
        (tmp_path / "apps" / "api" / "main.py").write_text("# main module")
        
        # With tests excluded (default)
        config = DiscoveryConfig.default()
        config.include_tests = False
        files, stats = discover_files(tmp_path, config)
        
        file_paths = [f.relative_to(tmp_path) for f in files]
        assert Path("factgap/main.py") in file_paths
        assert Path("apps/api/main.py") in file_paths
        assert Path("factgap/test_main.py") not in file_paths
        assert Path("tests/test_api.py") not in file_paths
        
        # With tests included
        config.include_tests = True
        files, stats = discover_files(tmp_path, config)
        
        file_paths = [f.relative_to(tmp_path) for f in files]
        assert Path("factgap/test_main.py") in file_paths
        assert Path("tests/test_api.py") in file_paths
    
    def test_discover_files_max_files_cap(self, tmp_path):
        """Test max files cap."""
        # Create many files
        (tmp_path / "factgap").mkdir()
        for i in range(10):
            (tmp_path / "factgap" / f"file_{i}.py").write_text(f"# file {i}")
        
        config = DiscoveryConfig.default()
        config.max_files = 5
        files, stats = discover_files(tmp_path, config)
        
        assert len(files) <= 5
        assert stats.skipped_counts['cap_reached'] > 0
    
    def test_discover_files_binary_detection(self, tmp_path):
        """Test binary file detection."""
        # Create text and binary files
        (tmp_path / "factgap").mkdir()
        (tmp_path / "factgap" / "text.py").write_text("# text file")
        (tmp_path / "factgap" / "binary.bin").write_bytes(b"binary\x00 content")
        
        config = DiscoveryConfig.default()
        files, stats = discover_files(tmp_path, config)
        
        file_paths = [f.relative_to(tmp_path) for f in files]
        assert Path("factgap/text.py") in file_paths
        assert Path("factgap/binary.bin") not in file_paths
        assert stats.skipped_counts['binary'] > 0
    
    def test_discover_files_unsupported_extensions(self, tmp_path):
        """Test unsupported extension filtering."""
        # Create files with different extensions
        (tmp_path / "factgap").mkdir()
        (tmp_path / "factgap" / "supported.py").write_text("# python")
        (tmp_path / "factgap" / "unsupported.exe").write_bytes(b"binary")
        (tmp_path / "factgap" / "also_unsupported.dll").write_bytes(b"binary")
        
        config = DiscoveryConfig.default()
        files, stats = discover_files(tmp_path, config)
        
        file_paths = [f.relative_to(tmp_path) for f in files]
        assert Path("factgap/supported.py") in file_paths
        assert Path("factgap/unsupported.exe") not in file_paths
        assert Path("factgap/also_unsupported.dll") not in file_paths
        assert stats.skipped_counts['unsupported_ext'] >= 2
    
    def test_discover_files_large_files(self, tmp_path):
        """Test large file filtering."""
        # Create small and large files
        (tmp_path / "factgap").mkdir()
        (tmp_path / "factgap" / "small.py").write_text("# small file")
        
        large_file = tmp_path / "factgap" / "large.py"
        large_file.write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB
        
        config = DiscoveryConfig.default()
        config.max_file_bytes = 1024 * 1024  # 1MB
        files, stats = discover_files(tmp_path, config)
        
        file_paths = [f.relative_to(tmp_path) for f in files]
        assert Path("factgap/small.py") in file_paths
        assert Path("factgap/large.py") not in file_paths
        assert stats.skipped_counts['too_large'] > 0
    
    def test_discover_files_stats_summary(self, tmp_path):
        """Test statistics summary."""
        # Create test structure
        (tmp_path / "factgap").mkdir()
        (tmp_path / "factgap" / "main.py").write_text("# main")
        (tmp_path / "node_modules" / "package.json").mkdir(parents=True)
        (tmp_path / "node_modules" / "package.json").write_text("{}")
        (tmp_path / "README.md").write_text("# README")
        (tmp_path / "large.exe").write_bytes(b"x" * 2000000)
        
        config = DiscoveryConfig.default()
        files, stats = discover_files(tmp_path, config)
        
        summary = stats.summary()
        
        assert 'dirs_visited' in summary
        assert 'files_seen' in summary
        assert 'files_included' in summary
        assert 'skipped_counts' in summary
        assert 'total_skipped' in summary
        
        # Should have some statistics
        assert summary['files_included'] > 0
        assert summary['total_skipped'] > 0
        assert summary['dirs_visited'] > 0
