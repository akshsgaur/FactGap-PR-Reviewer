"""Optimized chunking module for RAG indexing."""

import os
import re
import yaml
from pathlib import Path
from typing import List, Optional, Tuple, Set, Dict, Any
from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language


@dataclass
class ChunkingConfig:
    """Configuration for chunking behavior."""
    ignore_globs: List[str]
    max_file_bytes: int
    max_changed_files_indexed: int
    max_total_chunks_per_run: int
    chunk_sizes: Dict[str, Dict[str, int]]
    
    @classmethod
    def default(cls) -> 'ChunkingConfig':
        """Create default configuration."""
        return cls(
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
                '*.min.js',
                '*.map',
                '*.lock',
                'yarn.lock',
                'package-lock.json'
            ],
            max_file_bytes=1024 * 1024,  # 1MB
            max_changed_files_indexed=50,
            max_total_chunks_per_run=1500,
            chunk_sizes={
                'code': {'chunk_size': 1200, 'overlap': 150},
                'diff': {'chunk_size': 800, 'overlap': 100},
                'repo_doc': {'chunk_size': 1000, 'overlap': 150},
                'notion': {'chunk_size': 1000, 'overlap': 150}
            }
        )
    
    @classmethod
    def from_file(cls, config_path: Path) -> 'ChunkingConfig':
        """Load configuration from YAML file."""
        if not config_path.exists():
            return cls.default()
        
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f) or {}
        
        default = cls.default()
        
        # Merge with defaults
        return cls(
            ignore_globs=config_data.get('ignore_globs', default.ignore_globs),
            max_file_bytes=config_data.get('max_file_bytes', default.max_file_bytes),
            max_changed_files_indexed=config_data.get('max_changed_files_indexed', default.max_changed_files_indexed),
            max_total_chunks_per_run=config_data.get('max_total_chunks_per_run', default.max_total_chunks_per_run),
            chunk_sizes=config_data.get('chunk_sizes', default.chunk_sizes)
        )


class PathFilter:
    """Filter for determining which paths to index."""
    
    def __init__(self, config: ChunkingConfig):
        self.config = config
        self.env_ignore_globs = self._parse_env_globs()
    
    def _parse_env_globs(self) -> List[str]:
        """Parse ignore globs from environment variable."""
        env_globs = os.getenv('FACTGAP_IGNORE_GLOBS', '')
        if not env_globs:
            return []
        return [g.strip() for g in env_globs.split(',') if g.strip()]
    
    def should_skip_path(self, path: Path, relative_to: Optional[Path] = None) -> Tuple[bool, str]:
        """
        Check if a path should be skipped.
        
        Returns:
            Tuple of (should_skip, reason)
        """
        # Get relative path for checking
        if relative_to:
            rel_path = path.relative_to(relative_to)
        else:
            rel_path = path
        
        path_str = str(rel_path)
        
        # Check config ignore globs
        for glob in self.config.ignore_globs:
            if self._matches_glob(path_str, glob):
                return True, f"ignored by config glob: {glob}"
        
        # Check environment ignore globs
        for glob in self.env_ignore_globs:
            if self._matches_glob(path_str, glob):
                return True, f"ignored by env glob: {glob}"
        
        return False, ""
    
    def _matches_glob(self, path: str, glob: str) -> bool:
        """Simple glob matching."""
        # Convert glob to regex
        pattern = glob.replace('**', '.*').replace('*', '[^/]*')
        pattern = f'^{pattern}$'
        return re.match(pattern, path) is not None
    
    def should_skip_size(self, file_path: Path) -> Tuple[bool, str]:
        """
        Check if file should be skipped due to size.
        
        Returns:
            Tuple of (should_skip, reason)
        """
        try:
            size = file_path.stat().st_size
            if size > self.config.max_file_bytes:
                return True, f"file too large: {size} bytes > {self.config.max_file_bytes}"
            return False, ""
        except OSError:
            return True, "cannot read file size"


class SymbolExtractor:
    """Extract symbols from code chunks without heavy AST parsing."""
    
    @staticmethod
    def extract_symbol(content: str, language: str, chunk_start: int = 0) -> Optional[str]:
        """Extract best-effort symbol from chunk content."""
        if language == 'python':
            return SymbolExtractor._extract_python_symbol(content, chunk_start)
        elif language in ['js', 'ts', 'jsx', 'tsx']:
            return SymbolExtractor._extract_js_ts_symbol(content, chunk_start)
        elif language == 'go':
            return SymbolExtractor._extract_go_symbol(content, chunk_start)
        elif language == 'java':
            return SymbolExtractor._extract_java_symbol(content, chunk_start)
        elif language == 'rs':
            return SymbolExtractor._extract_rust_symbol(content, chunk_start)
        else:
            return None
    
    @staticmethod
    def _extract_python_symbol(content: str, chunk_start: int) -> Optional[str]:
        """Extract Python function/class name."""
        # Look for def/class before chunk content
        lines_before = content[:chunk_start].split('\n') if chunk_start > 0 else []
        lines_before.reverse()
        
        for line in lines_before[:50]:  # Look back 50 lines max
            line = line.strip()
            if line.startswith('def '):
                match = re.match(r'def\s+(\w+)', line)
                if match:
                    return f"function:{match.group(1)}"
            elif line.startswith('class '):
                match = re.match(r'class\s+(\w+)', line)
                if match:
                    return f"class:{match.group(1)}"
        
        return None
    
    @staticmethod
    def _extract_js_ts_symbol(content: str, chunk_start: int) -> Optional[str]:
        """Extract JS/TS function/class/const name."""
        lines_before = content[:chunk_start].split('\n') if chunk_start > 0 else []
        lines_before.reverse()
        
        for line in lines_before[:50]:
            line = line.strip()
            # Function declarations
            if 'function ' in line:
                match = re.search(r'function\s+(\w+)', line)
                if match:
                    return f"function:{match.group(1)}"
            # Arrow functions
            elif 'const ' in line and '=' in line:
                match = re.search(r'const\s+(\w+)\s*=', line)
                if match:
                    return f"const:{match.group(1)}"
            # Class declarations
            elif line.startswith('class '):
                match = re.match(r'class\s+(\w+)', line)
                if match:
                    return f"class:{match.group(1)}"
        
        return None
    
    @staticmethod
    def _extract_go_symbol(content: str, chunk_start: int) -> Optional[str]:
        """Extract Go function name."""
        lines_before = content[:chunk_start].split('\n') if chunk_start > 0 else []
        lines_before.reverse()
        
        for line in lines_before[:50]:
            line = line.strip()
            if line.startswith('func '):
                match = re.match(r'func\s+(\w+)', line)
                if match:
                    return f"function:{match.group(1)}"
        
        return None
    
    @staticmethod
    def _extract_java_symbol(content: str, chunk_start: int) -> Optional[str]:
        """Extract Java method/class name."""
        lines_before = content[:chunk_start].split('\n') if chunk_start > 0 else []
        lines_before.reverse()
        
        for line in lines_before[:50]:
            line = line.strip()
            # Method declarations
            if 'public ' in line or 'private ' in line or 'protected ' in line:
                match = re.search(r'(?:public|private|protected)\s+.*\s+(\w+)\s*\(', line)
                if match:
                    return f"method:{match.group(1)}"
            # Class declarations
            elif line.startswith('class '):
                match = re.match(r'class\s+(\w+)', line)
                if match:
                    return f"class:{match.group(1)}"
        
        return None
    
    @staticmethod
    def _extract_rust_symbol(content: str, chunk_start: int) -> Optional[str]:
        """Extract Rust function name."""
        lines_before = content[:chunk_start].split('\n') if chunk_start > 0 else []
        lines_before.reverse()
        
        for line in lines_before[:50]:
            line = line.strip()
            if line.startswith('fn '):
                match = re.match(r'fn\s+(\w+)', line)
                if match:
                    return f"function:{match.group(1)}"
        
        return None


class LineSpanMapper:
    """Map chunks back to original line spans for citations."""
    
    @staticmethod
    def map_chunk_to_line_spans(
        original_content: str,
        chunk_text: str,
        chunk_start_pos: int
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Map a chunk to its line spans in the original file.
        
        Returns:
            Tuple of (start_line, end_line) or (None, None) if mapping fails
        """
        try:
            # Count lines before chunk
            lines_before = original_content[:chunk_start_pos].count('\n')
            start_line = lines_before + 1
            
            # Count lines in chunk
            lines_in_chunk = chunk_text.count('\n')
            end_line = start_line + lines_in_chunk
            
            return start_line, end_line
        except Exception:
            return None, None
    
    @staticmethod
    def map_chunk_with_fallback(
        original_content: str,
        chunk_text: str
    ) -> Tuple[Optional[int], Optional[int]]:
        """
        Map chunk to line spans with fallback strategies.
        """
        # Strategy 1: Direct string find
        try:
            pos = original_content.find(chunk_text)
            if pos != -1:
                return LineSpanMapper.map_chunk_to_line_spans(original_content, chunk_text, pos)
        except Exception:
            pass
        
        # Strategy 2: Whitespace-normalized find
        try:
            normalized_original = re.sub(r'\s+', ' ', original_content)
            normalized_chunk = re.sub(r'\s+', ' ', chunk_text)
            pos = normalized_original.find(normalized_chunk)
            if pos != -1:
                return LineSpanMapper.map_chunk_to_line_spans(original_content, chunk_text, pos)
        except Exception:
            pass
        
        # Strategy 3: Failed mapping
        return None, None


class SemanticChunker:
    """Semantic-aware chunker with context headers."""
    
    def __init__(self, config: ChunkingConfig):
        self.config = config
        self.path_filter = PathFilter(config)
    
    def get_language_by_extension(self, file_path: Path) -> Language:
        """Get LangChain Language enum by file extension."""
        ext = file_path.suffix.lower()
        
        mapping = {
            '.py': Language.PYTHON,
            '.ts': Language.TS,
            '.tsx': Language.TS,
            '.js': Language.JS,
            '.jsx': Language.JS,
            '.go': Language.GO,
            '.java': Language.JAVA,
            '.rs': Language.RUST,
            '.rb': Language.RUBY,
        }
        
        return mapping.get(ext, None) or Language.MARKDOWN  # Fallback to markdown
    
    def create_context_header(
        self,
        source_type: str,
        path: str,
        language: Optional[str] = None,
        symbol: Optional[str] = None,
        title: Optional[str] = None,
        url: Optional[str] = None,
        last_edited_time: Optional[str] = None,
        hunk_header: Optional[str] = None
    ) -> str:
        """Create deterministic context header for chunk."""
        if source_type == 'code':
            header_parts = [f"File: {path}"]
            if language:
                header_parts.append(f"Language: {language}")
            if symbol:
                header_parts.append(f"Symbol: {symbol}")
        elif source_type == 'diff':
            header_parts = [f"Diff for: {path}"]
            if hunk_header:
                header_parts.append(f"Hunk: {hunk_header}")
        elif source_type == 'repo_doc':
            header_parts = [f"Doc: {path}"]
        elif source_type == 'notion':
            header_parts = []
            if title:
                header_parts.append(f"Notion: {title}")
            if url:
                header_parts.append(f"URL: {url}")
            if last_edited_time:
                header_parts.append(f"Last edited: {last_edited_time}")
        else:
            header_parts = [f"Source: {source_type}"]
        
        return '\n'.join(header_parts) + '\n---\n'
    
    def chunk_file(
        self,
        file_path: Path,
        source_type: str = 'code',
        relative_to: Optional[Path] = None
    ) -> List[Dict[str, Any]]:
        """
        Chunk a file into semantic chunks with context headers.
        
        Returns:
            List of chunk dictionaries with content, line spans, and metadata
        """
        # Check if should skip
        should_skip, skip_reason = self.path_filter.should_skip_path(file_path, relative_to)
        if should_skip:
            return []
        
        should_skip_size, size_reason = self.path_filter.should_skip_size(file_path)
        if should_skip_size:
            return []
        
        # Read file content once
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (UnicodeDecodeError, OSError):
            # Binary file or unreadable
            return []
        
        if not content.strip():
            return []
        
        # Get relative path
        if relative_to:
            rel_path = str(file_path.relative_to(relative_to))
        else:
            rel_path = str(file_path)
        
        # Determine language and splitter
        if source_type == 'code':
            language = file_path.suffix[1:] if file_path.suffix else None
            lang_enum = self.get_language_by_extension(file_path)
            chunk_config = self.config.chunk_sizes['code']
            splitter = RecursiveCharacterTextSplitter.from_language(
                lang_enum,
                chunk_size=chunk_config['chunk_size'],
                chunk_overlap=chunk_config['overlap']
            )
        else:
            language = None
            chunk_config = self.config.chunk_sizes.get(source_type, self.config.chunk_sizes['repo_doc'])
            splitter = RecursiveCharacterTextSplitter.from_language(
                Language.MARKDOWN,
                chunk_size=chunk_config['chunk_size'],
                chunk_overlap=chunk_config['overlap']
            )
        
        # Split content
        chunks = splitter.split_text(content)
        
        # Process chunks with context headers and line spans
        processed_chunks = []
        current_pos = 0
        
        for i, chunk_text in enumerate(chunks):
            if not chunk_text.strip():
                continue
            
            # Find actual position in original content
            actual_pos = content.find(chunk_text, current_pos)
            if actual_pos == -1:
                actual_pos = current_pos
            
            # Extract symbol for code chunks
            symbol = None
            if source_type == 'code' and language:
                symbol = SymbolExtractor.extract_symbol(content, language, actual_pos)
            
            # Create context header
            header = self.create_context_header(
                source_type=source_type,
                path=rel_path,
                language=language,
                symbol=symbol
            )
            
            # Combine header and content
            enriched_content = header + chunk_text
            
            # Map to line spans
            start_line, end_line = LineSpanMapper.map_chunk_with_fallback(content, chunk_text)
            
            processed_chunks.append({
                'content': enriched_content,
                'original_content': chunk_text,
                'path': rel_path,
                'language': language,
                'symbol': symbol,
                'source_type': source_type,
                'start_line': start_line,
                'end_line': end_line,
                'chunk_index': i,
                'position': actual_pos
            })
            
            current_pos = actual_pos + len(chunk_text)
        
        return processed_chunks
    
    def prioritize_changed_files(
        self,
        changed_files: List[Dict[str, Any]],
        max_files: int
    ) -> List[Dict[str, Any]]:
        """
        Prioritize changed files for indexing when limits are exceeded.
        """
        def score_file(file_info):
            path = file_info.get('path', '')
            
            # Skip ignored paths entirely
            should_skip, _ = self.path_filter.should_skip_path(Path(path))
            if should_skip:
                return -1
            
            score = 0
            
            # Prefer smaller files
            size = file_info.get('size', 0)
            if size > 0:
                score += min(100, 10000 / size)  # Diminishing returns
            
            # Prefer code files
            code_extensions = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.java', '.rs'}
            if any(path.endswith(ext) for ext in code_extensions):
                score += 50
            
            # Prefer important directories
            important_dirs = ['src/', 'app/', 'server/', 'factgap/', 'lib/']
            if any(dir in path for dir in important_dirs):
                score += 30
            
            return score
        
        # Filter and sort
        valid_files = [f for f in changed_files if score_file(f) > 0]
        valid_files.sort(key=score_file, reverse=True)
        
        return valid_files[:max_files]


def load_config(project_root: Optional[Path] = None) -> ChunkingConfig:
    """Load chunking configuration from project."""
    if project_root is None:
        # Try to find .factgap/config.yml
        current = Path.cwd()
        while current != current.parent:
            config_path = current / '.factgap' / 'config.yml'
            if config_path.exists():
                return ChunkingConfig.from_file(config_path)
            current = current.parent
        
        # Fallback to default
        return ChunkingConfig.default()
    else:
        config_path = project_root / '.factgap' / 'config.yml'
        return ChunkingConfig.from_file(config_path)
