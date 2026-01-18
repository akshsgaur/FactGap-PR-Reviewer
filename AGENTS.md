# FactGap PR Reviewer - AI Agents Guide

This document describes the AI agents and their roles within the FactGap PR Reviewer system.

## System Architecture

The FactGap PR Reviewer uses a multi-agent architecture with specialized components working together to provide contextual PR analysis and chat functionality through a centralized MCP (Model Context Protocol) server.

## Core Agents

### 1. PR Analysis Agent
**Purpose**: Automatically analyzes pull requests and generates contextual reviews

**Triggers**:
- PR opened
- PR synchronized (new commits pushed)

**Workflow**:
1. **Indexing Phase**: 
   - Calls `pr_index_build` to index PR diff and changed files
   - Calls `repo_docs_build` to index repository documentation
   - Calls `notion_index` to index Notion documentation (if configured)

2. **Retrieval Phase**:
   - Searches for relevant code patterns, documentation, and guidelines
   - Retrieves evidence from multiple sources (code, diff, repo docs, Notion)
   - Uses semantic similarity with OpenAI embeddings

3. **Analysis Phase**:
   - Generates AI-powered analysis using OpenAI GPT-4
   - Falls back to retrieval-only analysis if AI unavailable
   - Ensures all hard claims have proper citations

4. **Verification Phase**:
   - Calls `review_verify_citations` to verify Fact Gap compliance
   - Adds warnings for missing citations

**Output**: PR comment with analysis, evidence, and citations

### 2. PR Chat Agent
**Purpose**: Handles @code-reviewer mentions in PR comments

**Triggers**:
- PR comment containing `@code-reviewer`

**Workflow**:
1. **Intent Recognition**: Parses comment to extract the question using regex patterns
2. **Evidence Retrieval**: Searches for relevant context from all indexed sources
3. **Response Generation**: Provides contextual answers with citations
4. **Citation Verification**: Ensures compliance with Fact Gap rules

**Output**: PR comment answering the user's question with evidence

## Supporting Agents

### 3. MCP Server Agent
**Purpose**: Central gateway for all context retrieval operations using FastMCP

**Available Tools**:
- **Indexing Tools**:
  - `pr_index_build`: Index PR diff and changed files with line span mapping
  - `repo_docs_build`: Index repository documentation (README, SECURITY.md, CONTRIBUTING.md, docs/, adr/, .github/)
  - `notion_index`: Index Notion pages with metadata and timestamps

- **Search Tools**:
  - `pr_index_search`: Search within PR context (code + diff)
  - `repo_docs_search`: Search repository documentation
  - `notion_search`: Search Notion documentation

- **Utility Tools**:
  - `snippet_get_repo`: Get specific code snippets from repository files
  - `snippet_get_notion`: Get specific Notion content by page ID
  - `review_verify_citations`: Check citation compliance using hard claim detection
  - `redact`: Remove sensitive information (API keys, tokens, secrets)

**Security Features**:
- Automatic secret redaction using regex patterns
- Content sanitization before indexing
- No persistent storage of sensitive data

### 4. Chunking Agent
**Purpose**: Intelligently splits content for semantic search with line span preservation

**Specializations**:
- **CodeChunker**: Splits code files using LangChain language-specific splitters
  - Supports 20+ programming languages
  - 1200 character chunks with 150 overlap
  - Automatic symbol extraction (function/class names)

- **DiffChunker**: Handles git diff format with line mapping
  - 800 character chunks with 100 overlap
  - Preserves hunk boundaries
  - Custom separators for diff format

- **DocumentChunker**: Processes markdown and documentation
  - 1000 character chunks with 150 overlap
  - Semantic-aware separators (headers, paragraphs)

**Features**:
- Line span mapping for precise citations
- Deterministic chunking for reproducibility
- Content hashing for idempotency

### 5. Embedding Agent
**Purpose**: Generates vector embeddings for semantic search

**Configuration**:
- Model: `text-embedding-3-small` (1536 dimensions)
- Provider: OpenAI
- Purpose: Semantic similarity matching

### 6. Notion Agent
**Purpose**: Extracts and processes Notion page content

**Capabilities**:
- Recursive block traversal for complete content extraction
- Rich text to plain text conversion
- Metadata preservation (URLs, timestamps, titles)
- Support for all major Notion block types (paragraphs, headings, lists, code, etc.)

### 7. GitHub Agent
**Purpose**: Interacts with GitHub API for PR operations

**Capabilities**:
- Async PR details retrieval (title, body, SHA, metadata)
- Changed files listing with patch data
- Comment management (create, update, reply)
- Mention parsing with regex
- Marker-based comment updates

## Agent Coordination

### Request Flow
1. **GitHub Webhook** → **PR Analysis/Chat Agent**
2. **Analysis Agent** → **MCP Server Agent** (via stdio transport)
3. **MCP Server** → **Chunking Agent** (for content processing)
4. **Chunking Agent** → **Embedding Agent** (for vector generation)
5. **Embedding Agent** → **Supabase** (for storage/search)

### Data Flow
```
GitHub Event → Analysis Agent → MCP Server → Chunking → Embedding → Database
     ↓              ↓              ↓           ↓          ↓         ↓
   PR Details → Context Retrieval → Processing → Vectors → Storage → Search
```

### MCP Communication
- **Transport**: stdio (standard input/output)
- **Protocol**: JSON-RPC over stdio
- **Session**: Client-Server model with initialization
- **Tools**: Schema-defined with Pydantic models

## Agent Capabilities

### Fact Gap Enforcement
All agents follow strict Fact Gap rules:
- **Hard claims require citations** (words like "must", "violates", "policy")
- **Repo citations format**: `path:line-line @ sha`
- **Notion citations format**: `url (edited: timestamp)`
- **Verification**: Automatic citation checking before output

### Idempotency
- **Content hashing** prevents duplicate indexing
- **Upsert operations** ensure data consistency
- **Deterministic chunking** for reproducible results
- **Marker-based comment updates** prevent duplicates

### Security
- **Redaction tool** removes sensitive information
- **Service role keys** for database operations
- **No secrets in logs** or outputs
- **Input validation** and sanitization

## Configuration

### Environment Variables
Each agent requires specific configuration:
- `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`: Database access
- `OPENAI_API_KEY`: AI operations and embeddings
- `NOTION_TOKEN`: Documentation indexing (optional)
- `NOTION_PAGE_IDS`: Comma-separated list of Notion page IDs
- `GITHUB_TOKEN`: PR operations
- `GITHUB_REPOSITORY`: Repository identifier (owner/repo)
- `GITHUB_PR_NUMBER`: PR number for analysis
- `GITHUB_WORKSPACE`: Repository root path
- `LOG_LEVEL`: Logging verbosity

### Chunking Parameters
- **Code chunks**: 1200 characters, 150 overlap
- **Document chunks**: 1000 characters, 150 overlap
- **Diff chunks**: 800 characters, 100 overlap

### Search Parameters
- **Default k**: 10 results per search
- **Minimum similarity**: 0.7 cosine similarity
- **Filters**: Path, language, symbol matching
- **Query strategies**: Implementation vs Policy vs General

## Deployment

### GitHub Actions Integration
- **factgap-pr-analysis.yml**: Triggers on PR events (opened, synchronized)
- **factgap-pr-chat.yml**: Triggers on PR comments

### CLI Entry Points
- `factgap-mcp`: Run MCP server locally
- `factgap-pr-analyze`: Manual PR analysis
- `factgap-pr-chat`: Manual chat testing

### Workflow Triggers
- **PR Analysis**: On push to PR branches
- **Chat Response**: On comment creation with @code-reviewer mention

## Monitoring and Debugging

### Logging
- **Structured logging** with configurable levels
- **Error tracking** with context preservation
- **Performance metrics** for optimization
- **Stderr output** for JSON-RPC compliance

### Testing
- **Unit tests** for individual agents
- **Integration tests** for agent coordination
- **End-to-end tests** for complete workflows

## Future Enhancements

### Planned Agent Improvements
1. **Multi-repository support**: Cross-repository context
2. **Advanced citation analysis**: Semantic citation matching
3. **Custom rule engines**: Project-specific Fact Gap rules
4. **Performance optimization**: Parallel processing and caching
5. **Enhanced UI**: Rich comment formatting and interactions

### Extensibility
The agent architecture is designed for easy extension:
- New indexing sources (Confluence, etc.)
- Additional analysis capabilities
- Custom citation formats
- Alternative embedding models
- Additional chunking strategies

## Security Considerations

### Agent Isolation
- **Separate credentials** for each service
- **Least privilege** access patterns
- **Input validation** and sanitization
- **Async operations** for non-blocking behavior

### Data Protection
- **No persistent storage** of sensitive content
- **Automatic redaction** of secrets
- **Audit logging** for compliance
- **Content hashing** for privacy

---

This agent architecture enables FactGap PR Reviewer to provide accurate, contextual, and citation-backed code reviews while maintaining security, performance, and extensibility standards.
