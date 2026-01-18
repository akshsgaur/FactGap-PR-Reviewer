"""PR analysis and chat service"""

import logging
from typing import List, Dict, Any, Optional

import openai

from app.config import get_settings
from app.database import get_db
from app.services.github_app import get_github_service

logger = logging.getLogger(__name__)


class AnalysisService:
    """Service for PR analysis and chat responses"""

    def __init__(self):
        self.settings = get_settings()
        self.db = get_db()
        self.github_service = get_github_service()
        self.openai_client = openai.OpenAI(api_key=self.settings.openai_api_key)

        from supabase import create_client
        self.supabase = create_client(
            self.settings.supabase_url,
            self.settings.supabase_service_role_key
        )

    def _embed_text(self, text: str) -> List[float]:
        """Generate embedding for text"""
        response = self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding

    async def _search_chunks(
        self,
        user_id: str,
        query: str,
        repo: Optional[str] = None,
        pr_number: Optional[int] = None,
        source_types: Optional[List[str]] = None,
        k: int = 10,
        min_score: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """Search for relevant chunks"""
        query_embedding = self._embed_text(query)

        params = {
            "p_query_embedding": query_embedding,
            "p_k": k,
            "p_min_score": min_score,
            "p_user_id": user_id,
        }

        if repo:
            params["p_repo"] = repo
        if pr_number is not None:
            params["p_pr_number"] = pr_number
        if source_types:
            params["p_source_types"] = source_types

        response = self.supabase.rpc("match_chunks_user", params).execute()
        return response.data or []

    async def analyze_pr(
        self,
        user_id: str,
        installation_id: int,
        repo_full_name: str,
        pr_number: int,
    ) -> str:
        """Generate PR analysis"""
        try:
            # Get PR details
            pr = await self.github_service.get_pr_details(
                installation_id, repo_full_name, pr_number
            )

            pr_title = pr["title"]
            pr_body = pr.get("body") or ""
            head_sha = pr["head"]["sha"]

            # Retrieve evidence
            evidence = await self._retrieve_pr_evidence(
                user_id, repo_full_name, pr_number, pr_title, pr_body
            )

            # Generate analysis with GPT-4
            analysis = await self._generate_analysis(
                pr_title, pr_body, head_sha, evidence
            )

            return analysis

        except Exception as e:
            logger.error(f"Error analyzing PR: {e}")
            raise

    async def answer_question(
        self,
        user_id: str,
        installation_id: int,
        repo_full_name: str,
        pr_number: int,
        question: str,
    ) -> str:
        """Answer a @code-reviewer question"""
        try:
            # Get PR details
            pr = await self.github_service.get_pr_details(
                installation_id, repo_full_name, pr_number
            )
            head_sha = pr["head"]["sha"]

            # Retrieve evidence for the question
            evidence = await self._retrieve_chat_evidence(
                user_id, repo_full_name, pr_number, question
            )

            # Generate answer
            answer = await self._generate_answer(
                question, head_sha, evidence
            )

            return answer

        except Exception as e:
            logger.error(f"Error answering question: {e}")
            raise

    async def _retrieve_pr_evidence(
        self,
        user_id: str,
        repo_full_name: str,
        pr_number: int,
        pr_title: str,
        pr_body: str,
    ) -> List[Dict[str, Any]]:
        """Retrieve evidence for PR analysis"""
        evidence = []

        # Search queries
        queries = [
            pr_title,
            "security",
            "performance",
            "breaking change",
        ]

        # Add keywords from PR body
        if pr_body:
            body_lower = pr_body.lower()
            if "test" in body_lower:
                queries.append("testing")
            if "deploy" in body_lower:
                queries.append("deployment")

        for query in queries[:5]:
            try:
                # Search PR overlay
                pr_results = await self._search_chunks(
                    user_id, query,
                    repo=repo_full_name,
                    pr_number=pr_number,
                    source_types=["code", "diff"],
                    k=3,
                )
                evidence.extend(pr_results)

                # Search repo docs
                doc_results = await self._search_chunks(
                    user_id, query,
                    repo=repo_full_name,
                    source_types=["code"],
                    k=2,
                )
                evidence.extend(doc_results)

                # Search Notion
                notion_results = await self._search_chunks(
                    user_id, query,
                    source_types=["notion"],
                    k=2,
                )
                evidence.extend(notion_results)

            except Exception as e:
                logger.warning(f"Error searching for '{query}': {e}")

        # Deduplicate
        unique = {}
        for item in evidence:
            if item["id"] not in unique:
                unique[item["id"]] = item

        return sorted(
            unique.values(),
            key=lambda x: x.get("score", 0),
            reverse=True
        )[:10]

    async def _retrieve_chat_evidence(
        self,
        user_id: str,
        repo_full_name: str,
        pr_number: int,
        question: str,
    ) -> List[Dict[str, Any]]:
        """Retrieve evidence for chat question"""
        evidence = []
        question_lower = question.lower()

        # Implementation questions -> prioritize PR overlay
        if any(word in question_lower for word in ["how", "implement", "code", "function"]):
            pr_results = await self._search_chunks(
                user_id, question,
                repo=repo_full_name,
                pr_number=pr_number,
                source_types=["code", "diff"],
                k=5,
            )
            evidence.extend(pr_results)

        # Policy questions -> prioritize Notion
        if any(word in question_lower for word in ["policy", "standard", "should", "must"]):
            notion_results = await self._search_chunks(
                user_id, question,
                source_types=["notion"],
                k=3,
            )
            evidence.extend(notion_results)

        # General search if no specific strategy
        if not evidence:
            pr_results = await self._search_chunks(
                user_id, question,
                repo=repo_full_name,
                pr_number=pr_number,
                k=3,
            )
            evidence.extend(pr_results)

            notion_results = await self._search_chunks(
                user_id, question,
                source_types=["notion"],
                k=2,
            )
            evidence.extend(notion_results)

        # Deduplicate
        unique = {}
        for item in evidence:
            if item["id"] not in unique:
                unique[item["id"]] = item

        return sorted(
            unique.values(),
            key=lambda x: x.get("score", 0),
            reverse=True
        )[:8]

    async def _generate_analysis(
        self,
        pr_title: str,
        pr_body: str,
        head_sha: str,
        evidence: List[Dict[str, Any]],
    ) -> str:
        """Generate AI analysis"""
        # Format evidence for prompt
        evidence_text = self._format_evidence(evidence, head_sha)

        prompt = f"""You are an expert code reviewer. Analyze this PR and provide a review.

**IMPORTANT - Fact Gap Rules:**
- Every hard claim (using words like "must", "violates", "policy") MUST include a citation
- Repo citations format: `path:line-line @ sha`
- Notion citations format: `url (edited: timestamp)`
- If you cannot find evidence, say "no evidence found" instead of making claims

## PR Information
**Title:** {pr_title}
**Description:** {pr_body or "No description provided"}
**Head SHA:** {head_sha[:8]}

## Retrieved Evidence
{evidence_text}

## Your Task
1. Summarize the changes
2. Identify any security, performance, or breaking change risks (with citations)
3. Check alignment with team standards (cite Notion docs if applicable)
4. Provide actionable feedback

Format your response in Markdown. Include a "## How to Chat" section at the end explaining `@code-reviewer [question]`."""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are an expert code reviewer who follows the Fact Gap philosophy: hard claims must be backed by citations."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"GPT-4 error: {e}")
            return self._generate_fallback_analysis(pr_title, head_sha, evidence)

    async def _generate_answer(
        self,
        question: str,
        head_sha: str,
        evidence: List[Dict[str, Any]],
    ) -> str:
        """Generate AI answer for chat"""
        evidence_text = self._format_evidence(evidence, head_sha)

        prompt = f"""Answer this question about a PR. Use only the provided evidence.

**IMPORTANT - Fact Gap Rules:**
- Every claim MUST be backed by a citation from the evidence
- Repo citations: `path:line-line @ sha`
- Notion citations: `url`
- If you cannot answer from the evidence, say so

## Question
{question}

## Evidence
{evidence_text}

Provide a concise, well-cited answer."""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are an expert code reviewer. Cite your sources."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"GPT-4 error: {e}")
            return self._generate_fallback_answer(question, evidence)

    def _format_evidence(
        self,
        evidence: List[Dict[str, Any]],
        head_sha: str
    ) -> str:
        """Format evidence for prompt"""
        parts = []

        for i, item in enumerate(evidence[:8], 1):
            source_type = item.get("source_type", "unknown")
            content = item.get("content", "")[:500]
            score = item.get("score", 0)

            if source_type in ["code", "diff"]:
                path = item.get("path", "unknown")
                start = item.get("start_line")
                end = item.get("end_line")
                line_range = f"{start}-{end}" if start and end else "unknown"
                citation = f"{path}:{line_range} @ {head_sha[:8]}"
            elif source_type == "notion":
                url = item.get("url", "")
                citation = url
            else:
                citation = "unknown"

            parts.append(f"### Evidence {i} ({source_type}, score: {score:.2f})")
            parts.append(f"**Citation:** `{citation}`")
            parts.append(f"```\n{content}\n```\n")

        return "\n".join(parts) if parts else "No evidence found."

    def _generate_fallback_analysis(
        self,
        pr_title: str,
        head_sha: str,
        evidence: List[Dict[str, Any]]
    ) -> str:
        """Generate fallback analysis without AI"""
        parts = ["## PR Analysis Summary"]
        parts.append(f"- **PR:** {pr_title}")
        parts.append(f"- **SHA:** {head_sha[:8]}")
        parts.append("")
        parts.append("## Retrieved Evidence")

        if evidence:
            for i, item in enumerate(evidence[:5], 1):
                source_type = item.get("source_type", "unknown")
                content = item.get("content", "")[:300]
                parts.append(f"\n### {i}. {source_type.title()}")
                parts.append(f"```\n{content}\n```")
        else:
            parts.append("No relevant evidence found.")

        parts.append("")
        parts.append("## How to Chat")
        parts.append("Ask me: `@code-reviewer [your question about this PR]`")

        return "\n".join(parts)

    def _generate_fallback_answer(
        self,
        question: str,
        evidence: List[Dict[str, Any]]
    ) -> str:
        """Generate fallback answer without AI"""
        if not evidence:
            return "I couldn't find relevant evidence to answer your question. Please try rephrasing or check if the relevant code/docs are indexed."

        parts = [f"Based on the available evidence for your question: *{question}*\n"]

        for i, item in enumerate(evidence[:3], 1):
            source_type = item.get("source_type", "unknown")
            content = item.get("content", "")[:400]
            parts.append(f"**{i}. From {source_type}:**")
            parts.append(f"```\n{content}\n```\n")

        parts.append("If you need more specific information, please clarify your question.")

        return "\n".join(parts)


# Singleton
_analysis_service: Optional[AnalysisService] = None


def get_analysis_service() -> AnalysisService:
    """Get analysis service instance"""
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService()
    return _analysis_service
