# FactGap PR Reviewer

🤖 **Contextual PR Reviewer with RAG** that closes the Fact Gap between code changes and documentation.

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Type: FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)](https://fastapi.tiangolo.com/)
[![Type: Next.js](https://img.shields.io/badge/Next.js-14.2+-black.svg)](https://nextjs.org/)

**Two Deployment Options:**
- 🚀 **CLI/GitHub Actions** - Self-hosted, single repository
- ☁️ **SaaS Platform** - Multi-tenant web application

</div>

## ✨ What It Does

FactGap PR Reviewer provides intelligent code reviews by combining:

- **🔍 RAG over PR context** (diff + changed files)
- **📚 RAG over Notion documentation** ("how we do things here")
- **🎯 Fact Gap enforcement** - Every hard claim requires evidence
- **💬 Smart chat** - Ask questions with `@code-reviewer` in PR comments
- **🏗️ MCP server** - Centralized context gateway

## 🚀 Quick Start

### Option 1: CLI/GitHub Actions (Single Repo)

```bash
# 1. Clone and install
git clone https://github.com/yourusername/factgap-pr-reviewer.git
cd factgap-pr-reviewer
pip install -e .

# 2. Set up Supabase
# Create project at https://supabase.com
# Run migrations: supabase/migrations/001_*.sql, 002_*.sql

# 3. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 4. Add GitHub Secrets
# SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPENAI_API_KEY, NOTION_TOKEN

# 5. Enable GitHub Actions
# Copy .github/workflows/*.yml to your repo
```

### Option 2: SaaS Platform (Multi-Tenant)

```bash
# 1. Set up database
psql $DATABASE_URL -f supabase/migrations/003_*.sql
# ... up to 007_*.sql

# 2. Start backend
cd apps/api
pip install -r requirements.txt
uvicorn app.main:app --reload

# 3. Start frontend  
cd apps/web
npm install
npm run dev
```

## 🎯 Core Features

### 🤖 Automatic PR Analysis
- **Risk flags** with evidence citations
- **Review focus checklist** based on context
- **Relevant snippets** from code, docs, and Notion
- **Fact Gap compliance** - all claims verified

### 💬 Interactive PR Chat
```
@code-reviewer How does this authentication flow work?
```
- **Context-aware answers** with citations
- **Smart source prioritization** - PR overlay for implementation, docs for policy
- **Real-time responses** via GitHub webhooks

### 🔒 Fact Gap Rules
1. **Hard claims require citations** - "must", "violates", "policy" → evidence required
2. **Freshness awareness** - SHA timestamps for code, edit times for docs
3. **Permission safety** - Only accessible sources, secrets redacted
4. **Low noise** - One analysis comment, replies only when mentioned

## 🏗️ Architecture

### CLI/GitHub Actions Flow
```
GitHub Event → CLI → MCP Server → Supabase (pgvector)
                      ↓
                 OpenAI Embeddings
                      ↓
               LangChain Chunking
                      ↓
         PR Overlay + Repo Docs + Notion Index
```

### SaaS Platform Flow
```
Web Frontend (Next.js) ↔ API Backend (FastAPI)
                          ↓
                     MCP Server
                          ↓
                 Supabase (Multi-tenant)
```

## 📊 RAG Pipeline

### 1. **Indexing Phase**
```python
# Multi-source content ingestion
PR diff → chunks → embeddings → database
Changed files → chunks → embeddings → database  
Repo docs → chunks → embeddings → database
Notion pages → chunks → embeddings → database
```

### 2. **Retrieval Phase**
```python
# Semantic search with citations
query → embedding → vector search → ranked results
# Source-aware prioritization
implementation_questions → PR_overlay
policy_questions → docs + notion
```

### 3. **Generation Phase**
```python
# AI-powered or retrieval-only
evidence → GPT-4 analysis → citation verification
# Fact Gap enforcement
hard_claims → citation_check → compliance_warnings
```

## 🛠️ MCP Server Tools

### Indexing Tools
- `pr_index_build` - Index PR diff and changed files
- `repo_docs_build` - Index repository documentation  
- `notion_index` - Index Notion pages

### Search Tools
- `pr_index_search` - Search PR overlay chunks
- `repo_docs_search` - Search repository docs
- `notion_search` - Search Notion pages

### Utility Tools
- `snippet_get_repo` - Get exact code snippet
- `snippet_get_notion` - Get Notion page snippet
- `review_verify_citations` - Verify citations in markdown
- `redact` - Redact secrets from text

## 📋 Citation Formats

### Repository Citations
```
src/main.py:123-125 @ abc123def456
```

### Notion Citations
```
https://notion.so/page-id (edited: 2024-01-15T10:30:00.000Z)
```

## 🧪 Development

### Running Tests
```bash
pytest --cov=factgap
```

### Code Quality
```bash
black factgap/ tests/
ruff check factgap/ tests/
mypy factgap/
```

### Manual Testing
```bash
# Start MCP server
factgap-mcp

# Test PR analysis
export GITHUB_PR_NUMBER=123
factgap-pr-analyze

# Test chat
echo '{"comment":{"body":"@code-reviewer How does this work?"}}' | factgap-pr-chat
```

## 🔒 Security

- **Service Role Key**: Full database access - keep secure
- **Secret Redaction**: Automatic pattern detection and removal
- **Permission Safety**: Only indexes accessible content
- **No Background Workers**: GitHub Actions only, no persistent processes

## 📚 Documentation

- **[AGENTS.md](./AGENTS.md)** - Detailed agent architecture
- **[CLI Usage](./docs/cli.md)** - Command-line interface guide
- **[API Reference](./docs/api.md)** - MCP server API docs
- **[Deployment Guide](./docs/deployment.md)** - Production deployment

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Built with ❤️ by the FactGap team**

[⭐ Star this repo](https://github.com/yourusername/factgap-pr-reviewer) • 
[🐛 Report Issues](https://github.com/yourusername/factgap-pr-reviewer/issues) • 
[💬 Discussions](https://github.com/yourusername/factgap-pr-reviewer/discussions)

</div>
