"""Fast file discovery module."""

from .fast import (
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

__all__ = [
    'DiscoveryConfig',
    'FileDiscoveryStats',
    'discover_files',
    'is_hidden_directory',
    'matches_glob',
    'should_ignore_directory',
    'should_ignore_file',
    'is_binary_file',
    'is_supported_extension',
    'is_test_file',
    'path_is_under_include_root'
]
