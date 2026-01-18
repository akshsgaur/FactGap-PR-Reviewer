"""GitHub API client for PR operations"""

import os
import logging
from typing import List, Dict, Any, Optional

import github
from github import Github
from github import Auth

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub client for PR operations"""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GITHUB_TOKEN environment variable is required")
        
        self.client = Github(auth=github.Auth.Token(self.token))
        self.repo_name = os.getenv("GITHUB_REPOSITORY")
        if not self.repo_name:
            raise ValueError("GITHUB_REPOSITORY environment variable is required")
        
        self.repo = self.client.get_repo(self.repo_name)
    
    def get_pr_diff(self, pr_number: int) -> str:
        """Get PR diff text"""
        try:
            pr = self.repo.get_pull(pr_number)
            return pr.get_files().raw_data
        except Exception as e:
            logger.error(f"Failed to get PR diff for #{pr_number}: {e}")
            raise
    
    async def get_pr_changed_files(self, pr_number: int) -> List[Dict[str, Any]]:
        """Get list of changed files in PR"""
        try:
            pr = self.repo.get_pull(pr_number)
            files = []
            
            for file in pr.get_files():
                files.append({
                    "path": file.filename,
                    "status": file.status,  # added, removed, modified
                    "additions": file.additions,
                    "deletions": file.deletions,
                    "changes": file.changes,
                    "patch": file.patch,
                })
            
            return files
            
        except Exception as e:
            logger.error(f"Failed to get PR files for #{pr_number}: {e}")
            raise
    
    async def get_pr_details(self, pr_number: int) -> Dict[str, Any]:
        """Get PR details"""
        try:
            pr = self.repo.get_pull(pr_number)
            return {
                "number": pr.number,
                "title": pr.title,
                "body": pr.body or "",
                "head_sha": pr.head.sha,
                "base_sha": pr.base.sha,
                "state": pr.state,
                "author": pr.user.login,
                "created_at": pr.created_at.isoformat(),
                "updated_at": pr.updated_at.isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Failed to get PR details for #{pr_number}: {e}")
            raise
    
    def find_comment_by_marker(self, pr_number: int, marker: str) -> Optional[Any]:
        """Find comment by marker text"""
        try:
            pr = self.repo.get_pull(pr_number)
            comments = pr.get_issue_comments()
            
            for comment in comments:
                if marker in comment.body:
                    return comment
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to find comment for #{pr_number}: {e}")
            return None
    
    def create_or_update_comment(
        self,
        pr_number: int,
        body: str,
        marker: str
    ) -> Any:
        """Create or update comment with marker"""
        try:
            pr = self.repo.get_pull(pr_number)
            
            # Try to find existing comment
            existing_comment = self.find_comment_by_marker(pr_number, marker)
            
            if existing_comment:
                # Update existing comment
                existing_comment.edit(body)
                logger.info(f"Updated comment for PR #{pr_number}")
                return existing_comment
            else:
                # Create new comment
                comment = pr.create_issue_comment(body)
                logger.info(f"Created comment for PR #{pr_number}")
                return comment
                
        except Exception as e:
            logger.error(f"Failed to create/update comment for #{pr_number}: {e}")
            raise
    
    def reply_to_comment(self, pr_number: int, comment_id: int, body: str) -> Any:
        """Reply to a specific comment"""
        try:
            pr = self.repo.get_pull(pr_number)
            issue = pr.as_issue()
            
            # Create reply
            comment = issue.create_comment(body)
            logger.info(f"Replied to comment {comment_id} in PR #{pr_number}")
            return comment
            
        except Exception as e:
            logger.error(f"Failed to reply to comment {comment_id}: {e}")
            raise
    
    def parse_comment_mention(self, comment_body: str, bot_name: str = "code-reviewer") -> Optional[str]:
        """Parse @bot_name mention and extract question"""
        import re
        
        # Look for @bot_name pattern
        pattern = rf"@{re.escape(bot_name)}\s*(.+)"
        match = re.search(pattern, comment_body, re.IGNORECASE | re.DOTALL)
        
        if match:
            return match.group(1).strip()
        
        return None


def get_github_client() -> GitHubClient:
    """Get configured GitHub client"""
    return GitHubClient()
