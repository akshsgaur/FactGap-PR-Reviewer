"""LangChain-based chunking with line span mapping"""

import logging
from typing import List, Tuple, Optional
from pathlib import Path

from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    Language
)

logger = logging.getLogger(__name__)

# Language mapping from file extensions to LangChain Language enum
LANGUAGE_MAP = {
    '.py': Language.PYTHON,
    '.js': Language.JS,
    '.ts': Language.TS,
    '.tsx': Language.TS,  # Use TS for TSX
    '.jsx': Language.JS,  # Use JS for JSX
    '.java': Language.JAVA,
    '.cpp': Language.CPP,
    '.c': Language.C,
    '.cs': Language.CSHARP,
    '.php': Language.PHP,
    '.rb': Language.RUBY,
    '.go': Language.GO,
    '.rs': Language.RUST,
    '.swift': Language.SWIFT,
    '.kt': Language.KOTLIN,
    '.scala': Language.SCALA,
    '.html': Language.HTML,
    '.css': None,  # No CSS support, use generic
    '.sql': None,  # No SQL support, use generic
    '.sh': None,  # No BASH support, use generic
    '.yaml': None,  # No YAML support, use generic
    '.yml': None,  # No YAML support, use generic
    '.json': None,  # No JSON support, use generic
    '.xml': None,  # No XML support, use generic
    '.md': Language.MARKDOWN,
}


def get_language_from_extension(file_path: str) -> Optional[Language]:
    """Get LangChain Language enum from file extension"""
    ext = Path(file_path).suffix.lower()
    return LANGUAGE_MAP.get(ext)


def chunk_with_line_spans(
    original_text: str,
    chunks_in_order: List[str]
) -> List[Tuple[str, Optional[int], Optional[int]]]:
    """
    Map chunks back to line spans in the original text.
    
    Returns list of (chunk_text, start_line, end_line) tuples.
    Line numbers are 1-based and inclusive.
    """
    if not chunks_in_order:
        return []
    
    results = []
    cursor = 0
    
    for chunk in chunks_in_order:
        if not chunk.strip():
            results.append((chunk, None, None))
            continue
        
        # Find chunk occurrence starting from cursor
        chunk_start = original_text.find(chunk, cursor)
        
        if chunk_start == -1:
            # Chunk not found, might be due to normalization
            results.append((chunk, None, None))
            continue
        
        chunk_end = chunk_start + len(chunk)
        
        # Convert character positions to line numbers
        start_line = original_text[:chunk_start].count('\n') + 1
        end_line = original_text[:chunk_end].count('\n') + 1
        
        results.append((chunk, start_line, end_line))
        
        # Move cursor past this chunk
        cursor = chunk_end
    
    return results


class CodeChunker:
    """Code chunking using LangChain language-specific splitters"""
    
    def __init__(self, chunk_size: int = 1200, chunk_overlap: int = 150):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.generic_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
    
    def chunk_file(
        self,
        file_path: str,
        content: str
    ) -> List[Tuple[str, Optional[int], Optional[int]]]:
        """Chunk a file's content with line spans"""
        language = get_language_from_extension(file_path)
        
        if language:
            splitter = RecursiveCharacterTextSplitter.from_language(
                language,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap
            )
        else:
            splitter = self.generic_splitter
        
        # Get chunks
        chunks = splitter.split_text(content)
        
        # Map to line spans
        return chunk_with_line_spans(content, chunks)


class DiffChunker:
    """Diff chunking for PR hunks"""
    
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n@@ ", "\n@@ ", "\n", " "]
        )
    
    def chunk_diff(self, diff_text: str) -> List[Tuple[str, Optional[int], Optional[int]]]:
        """Chunk diff text with line spans"""
        chunks = self.splitter.split_text(diff_text)
        return chunk_with_line_spans(diff_text, chunks)


class DocumentChunker:
    """Document chunking for repo docs and Notion pages"""
    
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 150):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""]
        )
    
    def chunk_document(self, content: str) -> List[Tuple[str, Optional[int], Optional[int]]]:
        """Chunk document content with line spans"""
        chunks = self.splitter.split_text(content)
        return chunk_with_line_spans(content, chunks)
