"""Prompts for PR analysis and chat"""

import os
from typing import List, Dict, Any

# System prompts
CONTEXTUAL_PR_ANALYSIS_PROMPT = """You are an expert code reviewer analyzing a GitHub Pull Request. 
Your task is to provide a comprehensive PR Analysis that helps reviewers focus on what matters most.

CRITICAL RULES:
1. ALL hard claims (using words like "must", "violates", "policy", "standard", "breaks", "required", "we do X") MUST include citations
2. Citations must reference the provided evidence with:
   - For code: repo path @ SHA (e.g., `src/main.py:123-125 @ abc123`)
   - For Notion: page URL + last edited time
3. If no evidence is available for a claim, say "unknown / needs confirmation" and explain what's missing
4. Be concise and actionable
5. Focus on real risks, not style nitpicks

Based on the PR context and retrieved evidence, provide:

## Summary of Changes
- 3-5 bullet points describing what this PR actually does

## Risk Flags
- List potential issues with citations (security, performance, breaking changes, etc.)
- Each risk must have a citation or be marked as "needs confirmation"

## Review Focus Checklist
- Top 5 areas reviewers should prioritize
- Include specific files, functions, or concerns

## Relevant Context
- 3-8 cited snippets from PR overlay, repo docs, and Notion
- Each snippet should help reviewers understand the changes

## How to Chat
Ask me: `@code-reviewer [your question about this PR]`

PR Context:
Title: {pr_title}
Body: {pr_body}
Head SHA: {head_sha}

Retrieved Evidence:
{evidence}
"""

PR_CHAT_PROMPT = """You are an expert code reviewer answering questions about a GitHub Pull Request.

CRITICAL RULES:
1. Answer ONLY using the provided evidence and PR context
2. ALL hard claims (using words like "must", "violates", "policy", "standard", "breaks", "required", "we do X") MUST include citations
3. Citations must reference the provided evidence with:
   - For code: repo path @ SHA (e.g., `src/main.py:123-125 @ abc123`)
   - For Notion: page URL + last edited time
4. If evidence doesn't support an answer, say "Based on the available evidence, I cannot confirm..." and explain what's missing
5. Be concise and actionable
6. Prioritize recent PR changes over general repo docs
7. For "how we do X" questions, prioritize Notion and repo docs

PR Context:
PR #{pr_number} - {pr_title}
Head SHA: {head_sha}

Question: {question}

Retrieved Evidence:
{evidence}

Provide a helpful answer with proper citations. If you're uncertain, clearly state what information is missing."""


def format_pr_analysis_prompt(
    pr_title: str,
    pr_body: str,
    head_sha: str,
    evidence: List[Dict[str, Any]]
) -> str:
    """Format PR analysis prompt with context"""
    
    evidence_text = ""
    for i, ev in enumerate(evidence, 1):
        source_type = ev.get("source_type", "unknown")
        content = ev.get("content", "")[:500]  # Truncate for prompt
        
        if source_type in ["code", "diff"]:
            path = ev.get("path", "unknown")
            start_line = ev.get("start_line")
            end_line = ev.get("end_line")
            line_range = f"{start_line}-{end_line}" if start_line and end_line else "unknown"
            citation = f"{path}:{line_range} @ {head_sha}"
        elif source_type == "notion":
            url = ev.get("url", "")
            last_edited = ev.get("last_edited_time", "")
            citation = f"{url} (edited: {last_edited})"
        else:  # repo_doc
            path = ev.get("path", "unknown")
            citation = f"{path} @ {head_sha}"
        
        evidence_text += f"\n{i}. [{source_type.upper()}] {citation}\n{content}\n"
    
    return CONTEXTUAL_PR_ANALYSIS_PROMPT.format(
        pr_title=pr_title,
        pr_body=pr_body or "No description provided",
        head_sha=head_sha,
        evidence=evidence_text
    )


def format_pr_chat_prompt(
    pr_number: int,
    pr_title: str,
    head_sha: str,
    question: str,
    evidence: List[Dict[str, Any]]
) -> str:
    """Format PR chat prompt with context"""
    
    evidence_text = ""
    for i, ev in enumerate(evidence, 1):
        source_type = ev.get("source_type", "unknown")
        content = ev.get("content", "")[:500]  # Truncate for prompt
        
        if source_type in ["code", "diff"]:
            path = ev.get("path", "unknown")
            start_line = ev.get("start_line")
            end_line = ev.get("end_line")
            line_range = f"{start_line}-{end_line}" if start_line and end_line else "unknown"
            citation = f"{path}:{line_range} @ {head_sha}"
        elif source_type == "notion":
            url = ev.get("url", "")
            last_edited = ev.get("last_edited_time", "")
            citation = f"{url} (edited: {last_edited})"
        else:  # repo_doc
            path = ev.get("path", "unknown")
            citation = f"{path} @ {head_sha}"
        
        evidence_text += f"\n{i}. [{source_type.upper()}] {citation}\n{content}\n"
    
    return PR_CHAT_PROMPT.format(
        pr_number=pr_number,
        pr_title=pr_title,
        head_sha=head_sha,
        question=question,
        evidence=evidence_text
    )
