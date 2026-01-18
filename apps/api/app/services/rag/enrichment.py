"""Contextual chunk enrichment with deterministic headers"""

import re
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Maximum lines for context prefix
MAX_PREFIX_LINES = 20
MAX_IMPORT_LINES = 10


@dataclass
class EnrichedChunk:
    """A chunk with enriched content for embedding"""
    original_content: str
    enriched_content: str
    prefix: str
    metadata: dict


class ChunkEnricher:
    """
    Enriches chunks with deterministic header prefixes before embedding.
    Does NOT use LLM-generated summaries - only deterministic extraction.
    """

    def enrich_code_chunk(
        self,
        content: str,
        path: str,
        language: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        full_file_content: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> EnrichedChunk:
        """
        Enrich a code chunk with header prefix.

        Prefix includes:
        - File path
        - Language
        - Symbol (if extracted)
        - Context (imports) for early chunks
        """
        prefix_parts = []

        # File and language
        prefix_parts.append(f"File: {path}")
        if language:
            prefix_parts.append(f"Language: {language}")

        # Symbol if provided
        if symbol:
            prefix_parts.append(f"Symbol: {symbol}")

        # Extract context for early chunks (imports, module docstring)
        if start_line and start_line <= 30 and full_file_content:
            context = self._extract_file_context(full_file_content, language)
            if context:
                prefix_parts.append(f"Context:\n{context}")

        prefix = "\n".join(prefix_parts)

        # Ensure prefix doesn't exceed limit
        prefix_lines = prefix.split("\n")
        if len(prefix_lines) > MAX_PREFIX_LINES:
            prefix = "\n".join(prefix_lines[:MAX_PREFIX_LINES])

        enriched = f"{prefix}\n\n{content}"

        return EnrichedChunk(
            original_content=content,
            enriched_content=enriched,
            prefix=prefix,
            metadata={
                "path": path,
                "language": language,
                "start_line": start_line,
                "end_line": end_line,
                "symbol": symbol,
            },
        )

    def enrich_diff_chunk(
        self,
        content: str,
        path: Optional[str] = None,
        hunk_header: Optional[str] = None,
    ) -> EnrichedChunk:
        """
        Enrich a diff chunk with header prefix.

        Prefix includes:
        - File path being diffed
        - Hunk header if available
        """
        prefix_parts = []

        if path:
            prefix_parts.append(f"Diff for: {path}")
        else:
            # Try to extract path from diff content
            extracted_path = self._extract_diff_path(content)
            if extracted_path:
                prefix_parts.append(f"Diff for: {extracted_path}")

        if hunk_header:
            prefix_parts.append(f"Hunk: {hunk_header}")
        else:
            # Try to extract hunk header from content
            extracted_hunk = self._extract_hunk_header(content)
            if extracted_hunk:
                prefix_parts.append(f"Hunk: {extracted_hunk}")

        prefix = "\n".join(prefix_parts) if prefix_parts else "Diff:"

        enriched = f"{prefix}\n\n{content}"

        return EnrichedChunk(
            original_content=content,
            enriched_content=enriched,
            prefix=prefix,
            metadata={"path": path, "hunk_header": hunk_header},
        )

    def enrich_repo_doc_chunk(
        self,
        content: str,
        path: str,
    ) -> EnrichedChunk:
        """
        Enrich a repository documentation chunk.

        Prefix includes:
        - Document path
        """
        prefix = f"Doc: {path}"
        enriched = f"{prefix}\n\n{content}"

        return EnrichedChunk(
            original_content=content,
            enriched_content=enriched,
            prefix=prefix,
            metadata={"path": path},
        )

    def enrich_notion_chunk(
        self,
        content: str,
        title: Optional[str] = None,
        url: Optional[str] = None,
        last_edited_time: Optional[str] = None,
    ) -> EnrichedChunk:
        """
        Enrich a Notion page chunk.

        Prefix includes:
        - Page title
        - URL
        - Last edited time
        """
        prefix_parts = []

        if title:
            prefix_parts.append(f"Notion: {title}")
        else:
            prefix_parts.append("Notion: Untitled")

        if url:
            prefix_parts.append(f"URL: {url}")

        if last_edited_time:
            prefix_parts.append(f"Last edited: {last_edited_time}")

        prefix = "\n".join(prefix_parts)
        enriched = f"{prefix}\n\n{content}"

        return EnrichedChunk(
            original_content=content,
            enriched_content=enriched,
            prefix=prefix,
            metadata={
                "title": title,
                "url": url,
                "last_edited_time": last_edited_time,
            },
        )

    def _extract_file_context(
        self,
        full_content: str,
        language: Optional[str],
    ) -> Optional[str]:
        """
        Extract deterministic context from file (imports, module docstring).
        Returns up to MAX_IMPORT_LINES of context.
        """
        lines = full_content.split("\n")
        context_lines = []

        # Language-specific import patterns
        import_patterns = {
            "py": [r"^import\s+", r"^from\s+\S+\s+import"],
            "python": [r"^import\s+", r"^from\s+\S+\s+import"],
            "js": [r"^import\s+", r"^const\s+\w+\s*=\s*require\("],
            "ts": [r"^import\s+", r"^const\s+\w+\s*=\s*require\("],
            "tsx": [r"^import\s+"],
            "jsx": [r"^import\s+"],
            "go": [r"^import\s+"],
            "java": [r"^import\s+"],
            "rs": [r"^use\s+"],
            "rust": [r"^use\s+"],
        }

        patterns = import_patterns.get(language or "", [r"^import\s+"])
        compiled = [re.compile(p) for p in patterns]

        for line in lines[:50]:  # Only check first 50 lines
            stripped = line.strip()

            # Skip empty lines and comments at start
            if not stripped:
                continue

            # Check for imports
            is_import = any(p.match(stripped) for p in compiled)
            if is_import:
                context_lines.append(stripped)

            # Stop if we have enough context
            if len(context_lines) >= MAX_IMPORT_LINES:
                break

        if context_lines:
            return "\n".join(context_lines)
        return None

    def _extract_diff_path(self, diff_content: str) -> Optional[str]:
        """Extract file path from diff content"""
        # Look for diff --git a/path b/path
        match = re.search(r"diff --git a/(.+?) b/", diff_content)
        if match:
            return match.group(1)

        # Look for +++ b/path
        match = re.search(r"\+\+\+ b/(.+)", diff_content)
        if match:
            return match.group(1)

        return None

    def _extract_hunk_header(self, diff_content: str) -> Optional[str]:
        """Extract hunk header from diff content"""
        # Look for @@ -start,count +start,count @@ optional_context
        match = re.search(r"@@\s*-\d+(?:,\d+)?\s*\+\d+(?:,\d+)?\s*@@\s*(.*)", diff_content)
        if match:
            return match.group(0)[:100]  # Limit length
        return None


def extract_symbol_from_chunk(content: str, language: Optional[str]) -> Optional[str]:
    """
    Attempt to extract a symbol (function/class name) from chunk content.
    Returns the first meaningful symbol found, or None.
    """
    patterns = {
        "py": [
            r"^(?:async\s+)?def\s+(\w+)",  # Function
            r"^class\s+(\w+)",  # Class
        ],
        "python": [
            r"^(?:async\s+)?def\s+(\w+)",
            r"^class\s+(\w+)",
        ],
        "js": [
            r"^(?:async\s+)?function\s+(\w+)",
            r"^(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(",
            r"^class\s+(\w+)",
        ],
        "ts": [
            r"^(?:async\s+)?function\s+(\w+)",
            r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=",
            r"^(?:export\s+)?class\s+(\w+)",
            r"^(?:export\s+)?interface\s+(\w+)",
        ],
        "go": [
            r"^func\s+(?:\([^)]+\)\s+)?(\w+)",
            r"^type\s+(\w+)\s+struct",
            r"^type\s+(\w+)\s+interface",
        ],
        "java": [
            r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:\w+\s+)+(\w+)\s*\(",
            r"^\s*(?:public\s+)?class\s+(\w+)",
            r"^\s*(?:public\s+)?interface\s+(\w+)",
        ],
        "rs": [
            r"^(?:pub\s+)?fn\s+(\w+)",
            r"^(?:pub\s+)?struct\s+(\w+)",
            r"^(?:pub\s+)?enum\s+(\w+)",
            r"^(?:pub\s+)?trait\s+(\w+)",
        ],
        "rust": [
            r"^(?:pub\s+)?fn\s+(\w+)",
            r"^(?:pub\s+)?struct\s+(\w+)",
            r"^(?:pub\s+)?enum\s+(\w+)",
        ],
    }

    lang_patterns = patterns.get(language or "", [])
    if not lang_patterns:
        return None

    for line in content.split("\n"):
        stripped = line.strip()
        for pattern in lang_patterns:
            match = re.match(pattern, stripped)
            if match:
                return match.group(1)

    return None
