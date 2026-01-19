"""Fast file discovery with directory pruning and include roots."""

import os
import re
from pathlib import Path
from typing import List, Set, Dict, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class DiscoveryConfig:
    """Configuration for file discovery."""
    include_roots: List[str]
    ignore_globs: List[str]
    max_files: int
    max_chunks: int
    max_file_bytes: int
    include_tests: bool
    
    @classmethod
    def default(cls) -> 'DiscoveryConfig':
        """Create default configuration."""
        return cls(
            include_roots=[
                'factgap/',
                'apps/',
                'docs/',
                'adr/',
                '.github/',
                'README.md',
                'CLAUDE.md',
                'AGENTS.md',
                'SECURITY.md',
                'CONTRIBUTING.md'
            ],
            ignore_globs=[
                'node_modules/**',
                '.git/**',
                'dist/**',
                'build/**',
                '.next/**',
                'out/**',
                'coverage/**',
                'venv/**',
                '.venv/**',
                '__pycache__/**',
                '.pytest_cache/**',
                '.mypy_cache/**',
                '.ruff_cache/**',
                '.cache/**',
                '*.egg-info/**',
                'test-repo/**'
            ],
            max_files=800,
            max_chunks=5000,
            max_file_bytes=1024 * 1024,  # 1MB
            include_tests=False
        )


class FileDiscoveryStats:
    """Statistics for file discovery."""
    
    def __init__(self):
        self.dirs_visited = 0
        self.files_seen = 0
        self.files_included = 0
        self.skipped_counts = {
            'ignored_dir_pruned': 0,
            'ignored_path': 0,
            'unsupported_ext': 0,
            'too_large': 0,
            'binary': 0,
            'cap_reached': 0,
            'outside_include_roots': 0
        }
    
    def add_skip(self, reason: str, count: int = 1):
        """Add to skip count."""
        if reason in self.skipped_counts:
            self.skipped_counts[reason] += count
    
    def summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            'dirs_visited': self.dirs_visited,
            'files_seen': self.files_seen,
            'files_included': self.files_included,
            'skipped_counts': self.skipped_counts,
            'total_skipped': sum(self.skipped_counts.values())
        }


def is_hidden_directory(path: Path) -> bool:
    """Check if directory is hidden (except .github)."""
    return path.name.startswith('.') and path.name != '.github'


def matches_glob(path_str: str, glob: str) -> bool:
    """Simple glob matching."""
    # Convert glob to regex
    pattern = glob.replace('**', '.*').replace('*', '[^/]*')
    pattern = f'^{pattern}$'
    return re.match(pattern, path_str) is not None


def should_ignore_directory(dir_path: Path, relative_path: Path, config: DiscoveryConfig) -> Tuple[bool, str]:
    """Check if directory should be ignored during traversal."""
    dir_str = str(relative_path)
    
    # Check hidden directories (except .github)
    if is_hidden_directory(dir_path):
        if dir_path.name != '.github':
            return True, "hidden_directory"
    
    # Check ignore globs for directories
    for glob in config.ignore_globs:
        if matches_glob(dir_str + '/', glob) or matches_glob(dir_str, glob):
            return True, f"ignore_glob: {glob}"
    
    return False, ""


def should_ignore_file(file_path: Path, relative_path: Path, config: DiscoveryConfig) -> Tuple[bool, str]:
    """Check if file should be ignored."""
    file_str = str(relative_path)
    
    # Check ignore globs
    for glob in config.ignore_globs:
        if matches_glob(file_str, glob):
            return True, f"ignore_glob: {glob}"
    
    return False, ""


def is_binary_file(file_path: Path) -> bool:
    """Check if file is binary by reading first 8KB."""
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(8192)
            return b'\0' in chunk
    except (OSError, IOError):
        return True


def is_supported_extension(file_path: Path) -> bool:
    """Check if file has supported extension."""
    supported_extensions = {
        '.py', '.js', '.ts', '.tsx', '.jsx', '.md', '.txt', 
        '.go', '.rs', '.java', '.rb', '.php', '.c', '.cpp',
        '.h', '.hpp', '.cs', '.swift', '.kt', '.scala', '.yml',
        '.yaml', '.json', '.toml', '.ini', '.cfg', '.conf'
    }
    return file_path.suffix.lower() in supported_extensions


def is_test_file(file_path: Path) -> bool:
    """Check if file is a test file."""
    path_parts = file_path.parts
    filename = file_path.name.lower()
    
    # Check if in test directory
    if any('test' in part.lower() for part in path_parts):
        return True
    
    # Check if filename starts/ends with test
    if filename.startswith('test_') or filename.endswith('_test.py') or filename.endswith('.test.'):
        return True
    
    return False


def path_is_under_include_root(file_path: Path, repo_root: Path, config: DiscoveryConfig) -> bool:
    """Check if file is under an include root."""
    relative_path = file_path.relative_to(repo_root)
    
    # Check if file matches any include root
    for root in config.include_roots:
        if root.endswith('/'):
            # Directory include root
            if str(relative_path).startswith(root):
                return True
        else:
            # Single file include root
            if str(relative_path) == root:
                return True
    
    return False


def discover_files(
    repo_root: Path,
    config: Optional[DiscoveryConfig] = None
) -> Tuple[List[Path], FileDiscoveryStats]:
    """
    Discover files in repository with directory pruning and include roots.
    
    Returns:
        Tuple of (list of files to process, discovery statistics)
    """
    if config is None:
        config = DiscoveryConfig.default()
    
    stats = FileDiscoveryStats()
    files_to_process: List[Path] = []
    
    # First, handle single file include roots
    for root in config.include_roots:
        if not root.endswith('/'):
            # Single file
            file_path = repo_root / root
            if file_path.is_file():
                files_to_process.append(file_path)
                stats.files_included += 1
                stats.files_seen += 1
    
    # Then walk directories for include roots that are directories
    include_dirs = [root.rstrip('/') for root in config.include_roots if root.endswith('/')]
    
    for root_dir in include_dirs:
        root_path = repo_root / root_dir
        if not root_path.exists() or not root_path.is_dir():
            continue
        
        # Walk this directory with pruning
        for dirpath, dirnames, filenames in os.walk(root_path):
            stats.dirs_visited += 1
            
            # Prune directories in-place
            dirs_to_remove = []
            for dirname in dirnames:
                full_dir_path = Path(dirpath) / dirname
                relative_dir = full_dir_path.relative_to(repo_root)
                
                should_ignore, reason = should_ignore_directory(
                    Path(dirname), relative_dir, config
                )
                
                if should_ignore:
                    dirs_to_remove.append(dirname)
                    stats.add_skip('ignored_dir_pruned')
            
            # Remove ignored directories (this prevents os.walk from descending)
            for dirname in dirs_to_remove:
                dirnames.remove(dirname)
            
            # Process files in this directory
            for filename in filenames:
                if stats.files_included >= config.max_files:
                    stats.add_skip('cap_reached')
                    return files_to_process, stats
                
                file_path = Path(dirpath) / filename
                relative_path = file_path.relative_to(repo_root)
                stats.files_seen += 1
                
                # Check if file should be ignored
                should_ignore, reason = should_ignore_file(file_path, relative_path, config)
                if should_ignore:
                    stats.add_skip('ignored_path')
                    continue
                
                # Check if supported extension
                if not is_supported_extension(file_path):
                    stats.add_skip('unsupported_ext')
                    continue
                
                # Check if test file (and tests are excluded)
                if not config.include_tests and is_test_file(file_path):
                    stats.add_skip('ignored_path')  # Count as ignored path
                    continue
                
                # Check file size
                try:
                    file_size = file_path.stat().st_size
                    if file_size > config.max_file_bytes:
                        stats.add_skip('too_large')
                        continue
                except OSError:
                    stats.add_skip('too_large')  # Can't read size
                    continue
                
                # Check if binary
                if is_binary_file(file_path):
                    stats.add_skip('binary')
                    continue
                
                # File passed all checks
                files_to_process.append(file_path)
                stats.files_included += 1
    
    return files_to_process, stats
