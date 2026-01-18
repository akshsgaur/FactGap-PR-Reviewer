"""PR analysis and chat logic"""

import os
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

import openai
from mcp.server.fastmcp import FastMCP

from factgap.reviewer.github_api import GitHubClient
from factgap.reviewer.prompts import format_pr_analysis_prompt, format_pr_chat_prompt

logger = logging.getLogger(__name__)


class PRAnalyzer:
    """Analyzes PRs and handles chat interactions"""
    
    def __init__(self, mcp_client: FastMCP):
        self.mcp_client = mcp_client
        self.github_client = GitHubClient()
        self.openai_client = None
        
        if os.getenv("OPENAI_API_KEY"):
            self.openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    async def analyze_pr(self, pr_number: int, repo_root: str) -> str:
        """Generate PR Analysis comment"""
        try:
            # Get PR details
            pr_details = await self.github_client.get_pr_details(pr_number)
            head_sha = pr_details["head_sha"]
            
            # Get PR diff and changed files
            changed_files = await self.github_client.get_pr_changed_files(pr_number)
            
            # Build PR index
            diff_text = self._extract_diff_text(changed_files)
            
            await self.mcp_client.call_tool(
                "pr_index_build",
                {
                    "pr_number": pr_number,
                    "head_sha": head_sha,
                    "repo_root": repo_root,
                    "diff_text": diff_text,
                    "changed_files": changed_files
                }
            )
            
            # Build repo docs index
            await self.mcp_client.call_tool("repo_docs_build", {"repo_root": repo_root})
            
            # Build Notion index
            await self.mcp_client.call_tool("notion_index", {})
            
            # Retrieve evidence for analysis
            evidence = await self._retrieve_evidence(pr_details, head_sha)
            
            # Generate analysis
            if self.openai_client:
                analysis = await self._generate_ai_analysis(pr_details, head_sha, evidence)
            else:
                analysis = await self._generate_retrieval_analysis(pr_details, head_sha, evidence)
            
            # Verify citations
            citation_check = await self.mcp_client.call_tool(
                "review_verify_citations",
                {"draft_markdown": analysis}
            )
            
            # Add citation warnings if needed
            if citation_check.get("missing_citations"):
                warning = "\n\n⚠️ **Citation Warning**: Some hard claims lack citations. Please verify these statements."
                analysis += warning
            
            return analysis
            
        except Exception as e:
            logger.error(f"Failed to analyze PR #{pr_number}: {e}")
            raise
    
    async def handle_chat(
        self,
        pr_number: int,
        question: str,
        repo_root: str
    ) -> str:
        """Handle @code-reviewer chat question"""
        try:
            # Get PR details
            pr_details = await self.github_client.get_pr_details(pr_number)
            head_sha = pr_details["head_sha"]
            
            # Retrieve evidence for the question
            evidence = await self._retrieve_chat_evidence(
                pr_number, head_sha, question, repo_root
            )
            
            # Generate answer
            if self.openai_client:
                answer = await self._generate_ai_answer(
                    pr_details, head_sha, question, evidence
                )
            else:
                answer = await self._generate_retrieval_answer(question, evidence)
            
            # Verify citations
            citation_check = await self.mcp_client.call_tool(
                "review_verify_citations",
                {"draft_markdown": answer}
            )
            
            # Add citation warnings if needed
            if citation_check.get("missing_citations"):
                warning = "\n\n⚠️ **Note**: Some statements may need verification. Please check the provided evidence."
                answer += warning
            
            return answer
            
        except Exception as e:
            logger.error(f"Failed to handle chat for PR #{pr_number}: {e}")
            raise
    
    def _extract_diff_text(self, changed_files: List[Dict[str, Any]]) -> str:
        """Extract diff text from changed files"""
        diff_parts = []
        
        for file_info in changed_files:
            patch = file_info.get("patch", "")
            if patch:
                diff_parts.append(f"diff --git a/{file_info['path']} b/{file_info['path']}")
                diff_parts.append(patch)
        
        return "\n".join(diff_parts)
    
    async def _retrieve_evidence(
        self,
        pr_details: Dict[str, Any],
        head_sha: str
    ) -> List[Dict[str, Any]]:
        """Retrieve evidence for PR analysis"""
        evidence = []
        
        # Search queries based on PR title and body
        queries = [
            pr_details["title"],
            "security",
            "performance",
            "breaking change",
            "api",
            "database",
        ]
        
        # Add keywords from PR body
        if pr_details["body"]:
            body_lower = pr_details["body"].lower()
            if "test" in body_lower:
                queries.append("testing")
            if "deploy" in body_lower:
                queries.append("deployment")
            if "migration" in body_lower:
                queries.append("migration")
        
        # Search across all sources
        for query in queries[:5]:  # Limit to avoid too many calls
            try:
                # Search PR overlay
                pr_results = await self.mcp_client.call_tool(
                    "pr_index_search",
                    {
                        "pr_number": pr_details["number"],
                        "head_sha": head_sha,
                        "query": query,
                        "k": 3,
                        "source_types": ["code", "diff"]
                    }
                )
                evidence.extend(pr_results)
                
                # Search repo docs
                doc_results = await self.mcp_client.call_tool(
                    "repo_docs_search",
                    {"query": query, "k": 2}
                )
                evidence.extend(doc_results)
                
                # Search Notion
                notion_results = await self.mcp_client.call_tool(
                    "notion_search",
                    {"query": query, "k": 2}
                )
                evidence.extend(notion_results)
                
            except Exception as e:
                logger.warning(f"Failed to search for query '{query}': {e}")
                continue
        
        # Deduplicate and sort by score
        unique_evidence = {}
        for item in evidence:
            item_id = item.get("id")
            if item_id and item_id not in unique_evidence:
                unique_evidence[item_id] = item
        
        return sorted(
            unique_evidence.values(),
            key=lambda x: x.get("score", 0),
            reverse=True
        )[:10]  # Top 10 results
    
    async def _retrieve_chat_evidence(
        self,
        pr_number: int,
        head_sha: str,
        question: str,
        repo_root: str
    ) -> List[Dict[str, Any]]:
        """Retrieve evidence for chat question"""
        evidence = []
        
        # Determine search strategy based on question type
        question_lower = question.lower()
        
        # Implementation questions -> prioritize PR overlay
        if any(word in question_lower for word in ["how", "implement", "code", "function", "class"]):
            try:
                pr_results = await self.mcp_client.call_tool(
                    "pr_index_search",
                    {
                        "pr_number": pr_number,
                        "head_sha": head_sha,
                        "query": question,
                        "k": 5,
                        "source_types": ["code", "diff"]
                    }
                )
                evidence.extend(pr_results)
            except Exception as e:
                logger.warning(f"Failed to search PR overlay: {e}")
        
        # Policy/standard questions -> prioritize Notion and repo docs
        if any(word in question_lower for word in ["policy", "standard", "guideline", "how we", "should", "must"]):
            try:
                notion_results = await self.mcp_client.call_tool(
                    "notion_search",
                    {"query": question, "k": 3}
                )
                evidence.extend(notion_results)
                
                doc_results = await self.mcp_client.call_tool(
                    "repo_docs_search",
                    {"query": question, "k": 2}
                )
                evidence.extend(doc_results)
            except Exception as e:
                logger.warning(f"Failed to search docs/Notion: {e}")
        
        # General search if no specific strategy
        if not evidence:
            try:
                pr_results = await self.mcp_client.call_tool(
                    "pr_index_search",
                    {
                        "pr_number": pr_number,
                        "head_sha": head_sha,
                        "query": question,
                        "k": 3
                    }
                )
                evidence.extend(pr_results)
                
                doc_results = await self.mcp_client.call_tool(
                    "repo_docs_search",
                    {"query": question, "k": 2}
                )
                evidence.extend(doc_results)
                
            except Exception as e:
                logger.warning(f"Failed general search: {e}")
        
        # Deduplicate and sort
        unique_evidence = {}
        for item in evidence:
            item_id = item.get("id")
            if item_id and item_id not in unique_evidence:
                unique_evidence[item_id] = item
        
        return sorted(
            unique_evidence.values(),
            key=lambda x: x.get("score", 0),
            reverse=True
        )[:8]
    
    async def _generate_ai_analysis(
        self,
        pr_details: Dict[str, Any],
        head_sha: str,
        evidence: List[Dict[str, Any]]
    ) -> str:
        """Generate AI-powered PR analysis"""
        prompt = format_pr_analysis_prompt(
            pr_details["title"],
            pr_details["body"],
            head_sha,
            evidence
        )
        
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are an expert code reviewer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Failed to generate AI analysis: {e}")
            return await self._generate_retrieval_analysis(pr_details, head_sha, evidence)
    
    async def _generate_ai_answer(
        self,
        pr_details: Dict[str, Any],
        head_sha: str,
        question: str,
        evidence: List[Dict[str, Any]]
    ) -> str:
        """Generate AI-powered chat answer"""
        prompt = format_pr_chat_prompt(
            pr_details["number"],
            pr_details["title"],
            head_sha,
            question,
            evidence
        )
        
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are an expert code reviewer."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Failed to generate AI answer: {e}")
            return await self._generate_retrieval_answer(question, evidence)
    
    async def _generate_retrieval_analysis(
        self,
        pr_details: Dict[str, Any],
        head_sha: str,
        evidence: List[Dict[str, Any]]
    ) -> str:
        """Generate retrieval-only PR analysis"""
        analysis_parts = []
        
        # Summary
        analysis_parts.append("## Summary of Changes")
        analysis_parts.append(f"- PR: {pr_details['title']}")
        analysis_parts.append(f"- Files changed: {len(evidence)} relevant files found")
        analysis_parts.append("")
        
        # Risk flags based on evidence
        analysis_parts.append("## Risk Flags")
        risks = set()
        for item in evidence:
            content = item.get("content", "").lower()
            if any(word in content for word in ["security", "vulnerability", "auth"]):
                risks.add("Security concerns detected")
            if any(word in content for word in ["performance", "slow", "memory"]):
                risks.add("Performance impact possible")
            if any(word in content for word in ["breaking", "migration", "deprecated"]):
                risks.add("Breaking changes detected")
        
        if risks:
            for risk in risks:
                analysis_parts.append(f"- {risk} (needs confirmation)")
        else:
            analysis_parts.append("- No obvious risks detected in available evidence")
        analysis_parts.append("")
        
        # Review focus
        analysis_parts.append("## Review Focus Checklist")
        analysis_parts.append("- Review the provided evidence snippets")
        analysis_parts.append("- Verify security implications")
        analysis_parts.append("- Check for breaking changes")
        analysis_parts.append("- Validate test coverage")
        analysis_parts.append("")
        
        # Evidence snippets
        analysis_parts.append("## Relevant Context")
        for i, item in enumerate(evidence[:5], 1):
            source_type = item.get("source_type", "unknown")
            content = item.get("content", "")[:300]
            
            if source_type in ["code", "diff"]:
                path = item.get("path", "unknown")
                start_line = item.get("start_line")
                end_line = item.get("end_line")
                line_range = f"{start_line}-{end_line}" if start_line and end_line else "unknown"
                citation = f"{path}:{line_range} @ {head_sha}"
            elif source_type == "notion":
                url = item.get("url", "")
                citation = f"{url}"
            else:
                path = item.get("path", "unknown")
                citation = f"{path} @ {head_sha}"
            
            analysis_parts.append(f"{i}. **{source_type.title()}**: {citation}")
            analysis_parts.append(f"```\n{content}\n```")
            analysis_parts.append("")
        
        # Chat instructions
        analysis_parts.append("## How to Chat")
        analysis_parts.append("Ask me: `@code-reviewer [your question about this PR]`")
        
        return "\n".join(analysis_parts)
    
    async def _generate_retrieval_answer(
        self,
        question: str,
        evidence: List[Dict[str, Any]]
    ) -> str:
        """Generate retrieval-only chat answer"""
        if not evidence:
            return "Based on the available evidence, I cannot answer this question. No relevant information was found."
        
        answer_parts = [f"Based on the available evidence, here's what I found about your question:"]
        
        for i, item in enumerate(evidence[:3], 1):
            source_type = item.get("source_type", "unknown")
            content = item.get("content", "")[:400]
            
            if source_type in ["code", "diff"]:
                path = item.get("path", "unknown")
                start_line = item.get("start_line")
                end_line = item.get("end_line")
                line_range = f"{start_line}-{end_line}" if start_line and end_line else "unknown"
                citation = f"{path}:{line_range}"
            elif source_type == "notion":
                url = item.get("url", "")
                citation = f"{url}"
            else:
                path = item.get("path", "unknown")
                citation = f"{path}"
            
            answer_parts.append(f"\n{i}. From {source_type} ({citation}):")
            answer_parts.append(f"```\n{content}\n```")
        
        answer_parts.append("\nIf you need more specific information, please clarify your question.")
        
        return "\n".join(answer_parts)
