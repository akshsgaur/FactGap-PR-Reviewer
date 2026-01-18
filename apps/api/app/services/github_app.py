"""GitHub App service for OAuth and API operations"""

import logging
import time
from typing import Optional, List, Dict, Any

import httpx
import jwt

from app.config import get_settings

logger = logging.getLogger(__name__)


class GitHubAppService:
    """Service for GitHub App operations"""

    def __init__(self):
        self.settings = get_settings()
        self._installation_tokens: Dict[int, Dict[str, Any]] = {}

    def get_oauth_url(self, state: str) -> str:
        """Generate GitHub OAuth authorization URL"""
        params = {
            "client_id": self.settings.github_app_client_id,
            "redirect_uri": f"{self.settings.api_url}/api/auth/github/callback",
            "scope": "user:email",
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"https://github.com/login/oauth/authorize?{query}"

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange OAuth code for access token"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": self.settings.github_app_client_id,
                    "client_secret": self.settings.github_app_client_secret,
                    "code": code,
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """Get GitHub user info"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            return response.json()

    def _generate_app_jwt(self) -> str:
        """Generate JWT for GitHub App authentication"""
        now = int(time.time())
        payload = {
            "iat": now - 60,  # Issued 60 seconds ago
            "exp": now + (10 * 60),  # Expires in 10 minutes
            "iss": self.settings.github_app_id,
        }
        return jwt.encode(
            payload,
            self.settings.github_app_private_key,
            algorithm="RS256"
        )

    async def get_installation_token(self, installation_id: int) -> str:
        """Get installation access token for a GitHub App installation"""
        # Check cache
        cached = self._installation_tokens.get(installation_id)
        if cached and cached["expires_at"] > time.time() + 60:
            return cached["token"]

        # Generate new token
        app_jwt = self._generate_app_jwt()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            data = response.json()

        # Cache the token
        self._installation_tokens[installation_id] = {
            "token": data["token"],
            "expires_at": time.time() + 3600,  # Tokens are valid for 1 hour
        }

        return data["token"]

    async def get_user_installations(self, access_token: str) -> List[Dict[str, Any]]:
        """Get GitHub App installations accessible to the user"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user/installations",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("installations", [])

    async def get_installation_repos(
        self, installation_id: int
    ) -> List[Dict[str, Any]]:
        """Get repositories accessible to a GitHub App installation"""
        token = await self.get_installation_token(installation_id)

        repos = []
        page = 1

        async with httpx.AsyncClient() as client:
            while True:
                response = await client.get(
                    "https://api.github.com/installation/repositories",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                    params={"per_page": 100, "page": page},
                )
                response.raise_for_status()
                data = response.json()

                repos.extend(data.get("repositories", []))

                if len(data.get("repositories", [])) < 100:
                    break
                page += 1

        return repos

    async def get_repo_contents(
        self,
        installation_id: int,
        repo_full_name: str,
        path: str = "",
        ref: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get repository contents"""
        token = await self.get_installation_token(installation_id)

        async with httpx.AsyncClient() as client:
            params = {}
            if ref:
                params["ref"] = ref

            response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/contents/{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            # Single file returns dict, directory returns list
            if isinstance(data, dict):
                return [data]
            return data

    async def get_file_content(
        self,
        installation_id: int,
        repo_full_name: str,
        path: str,
        ref: Optional[str] = None
    ) -> Optional[str]:
        """Get file content from repository"""
        token = await self.get_installation_token(installation_id)

        async with httpx.AsyncClient() as client:
            params = {}
            if ref:
                params["ref"] = ref

            response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/contents/{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.raw+json",
                },
                params=params,
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()
            return response.text

    async def get_pr_details(
        self,
        installation_id: int,
        repo_full_name: str,
        pr_number: int
    ) -> Dict[str, Any]:
        """Get pull request details"""
        token = await self.get_installation_token(installation_id)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_pr_diff(
        self,
        installation_id: int,
        repo_full_name: str,
        pr_number: int
    ) -> str:
        """Get pull request diff"""
        token = await self.get_installation_token(installation_id)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.diff",
                },
            )
            response.raise_for_status()
            return response.text

    async def get_pr_files(
        self,
        installation_id: int,
        repo_full_name: str,
        pr_number: int
    ) -> List[Dict[str, Any]]:
        """Get files changed in a pull request"""
        token = await self.get_installation_token(installation_id)

        files = []
        page = 1

        async with httpx.AsyncClient() as client:
            while True:
                response = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/files",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                    params={"per_page": 100, "page": page},
                )
                response.raise_for_status()
                data = response.json()

                files.extend(data)

                if len(data) < 100:
                    break
                page += 1

        return files

    async def create_pr_comment(
        self,
        installation_id: int,
        repo_full_name: str,
        pr_number: int,
        body: str
    ) -> Dict[str, Any]:
        """Create a comment on a pull request"""
        token = await self.get_installation_token(installation_id)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"body": body},
            )
            response.raise_for_status()
            return response.json()

    async def clone_repo_files(
        self,
        installation_id: int,
        repo_full_name: str,
        ref: Optional[str] = None
    ) -> Dict[str, str]:
        """Get all indexable files from a repository (returns path -> content map)"""
        token = await self.get_installation_token(installation_id)

        # File extensions to index
        indexable_extensions = {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
            ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift",
            ".kt", ".scala", ".md", ".txt", ".yaml", ".yml", ".json",
            ".toml", ".ini", ".cfg", ".sh", ".bash", ".zsh",
        }

        files: Dict[str, str] = {}

        async def fetch_tree(path: str = "") -> None:
            contents = await self.get_repo_contents(
                installation_id, repo_full_name, path, ref
            )

            for item in contents:
                if item["type"] == "file":
                    # Check if file should be indexed
                    ext = "." + item["name"].split(".")[-1] if "." in item["name"] else ""
                    if ext.lower() in indexable_extensions or item["name"] in {
                        "README", "LICENSE", "Makefile", "Dockerfile"
                    }:
                        # Skip large files
                        if item.get("size", 0) < 100000:  # 100KB limit
                            content = await self.get_file_content(
                                installation_id,
                                repo_full_name,
                                item["path"],
                                ref
                            )
                            if content:
                                files[item["path"]] = content

                elif item["type"] == "dir":
                    # Skip common non-code directories
                    skip_dirs = {
                        "node_modules", ".git", "__pycache__", ".venv",
                        "venv", "dist", "build", ".next", ".cache",
                        "vendor", "target", ".idea", ".vscode",
                    }
                    if item["name"] not in skip_dirs:
                        await fetch_tree(item["path"])

        await fetch_tree()
        return files


# Singleton instance
_github_service: Optional[GitHubAppService] = None


def get_github_service() -> GitHubAppService:
    """Get GitHub service instance"""
    global _github_service
    if _github_service is None:
        _github_service = GitHubAppService()
    return _github_service
