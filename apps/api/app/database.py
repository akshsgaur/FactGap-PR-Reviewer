"""Database operations using Supabase"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from supabase import create_client, Client
from cryptography.fernet import Fernet

from app.config import get_settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database operations for the SaaS app"""

    def __init__(self):
        settings = get_settings()
        self.client: Client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key
        )

        # Set up encryption for tokens
        if settings.encryption_key:
            self.fernet = Fernet(settings.encryption_key.encode())
        else:
            # Generate a key for development (should be set in production)
            self.fernet = Fernet(Fernet.generate_key())
            logger.warning("No encryption key set, using generated key")

    def _encrypt(self, value: str) -> str:
        """Encrypt a sensitive value"""
        return self.fernet.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        """Decrypt a sensitive value"""
        return self.fernet.decrypt(value.encode()).decode()

    # User operations
    async def get_user_by_github_id(self, github_id: int) -> Optional[Dict[str, Any]]:
        """Get user by GitHub ID"""
        try:
            response = self.client.table("users").select("*").eq(
                "github_id", github_id
            ).execute()

            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get user by GitHub ID: {e}")
            raise

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        try:
            response = self.client.table("users").select("*").eq(
                "id", user_id
            ).execute()

            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get user by ID: {e}")
            raise

    async def create_user(
        self,
        github_id: int,
        github_login: str,
        github_access_token: Optional[str] = None,
        github_app_installation_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Create a new user"""
        try:
            data = {
                "github_id": github_id,
                "github_login": github_login,
            }

            if github_access_token:
                data["github_access_token"] = self._encrypt(github_access_token)
            if github_app_installation_id:
                data["github_app_installation_id"] = github_app_installation_id

            response = self.client.table("users").insert(data).execute()
            return response.data[0]
        except Exception as e:
            logger.error(f"Failed to create user: {e}")
            raise

    async def update_user(
        self,
        user_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Update user data"""
        try:
            # Encrypt sensitive fields
            if "github_access_token" in kwargs and kwargs["github_access_token"]:
                kwargs["github_access_token"] = self._encrypt(kwargs["github_access_token"])
            if "notion_access_token" in kwargs and kwargs["notion_access_token"]:
                kwargs["notion_access_token"] = self._encrypt(kwargs["notion_access_token"])

            response = self.client.table("users").update(kwargs).eq(
                "id", user_id
            ).execute()
            return response.data[0]
        except Exception as e:
            logger.error(f"Failed to update user: {e}")
            raise

    async def get_user_notion_token(self, user_id: str) -> Optional[str]:
        """Get decrypted Notion token for user"""
        try:
            response = self.client.table("users").select(
                "notion_access_token"
            ).eq("id", user_id).execute()

            if response.data and response.data[0].get("notion_access_token"):
                return self._decrypt(response.data[0]["notion_access_token"])
            return None
        except Exception as e:
            logger.error(f"Failed to get Notion token: {e}")
            return None

    async def get_user_github_token(self, user_id: str) -> Optional[str]:
        """Get decrypted GitHub token for user"""
        try:
            response = self.client.table("users").select(
                "github_access_token"
            ).eq("id", user_id).execute()

            if response.data and response.data[0].get("github_access_token"):
                return self._decrypt(response.data[0]["github_access_token"])
            return None
        except Exception as e:
            logger.error(f"Failed to get GitHub token: {e}")
            return None

    # Connected repos operations
    async def get_connected_repos(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all connected repos for a user"""
        try:
            response = self.client.table("connected_repos").select("*").eq(
                "user_id", user_id
            ).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Failed to get connected repos: {e}")
            raise

    async def get_connected_repo_by_github_id(
        self, user_id: str, github_repo_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get connected repo by GitHub repo ID"""
        try:
            response = self.client.table("connected_repos").select("*").eq(
                "user_id", user_id
            ).eq("github_repo_id", github_repo_id).execute()

            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get connected repo: {e}")
            raise

    async def connect_repo(
        self,
        user_id: str,
        github_repo_id: int,
        repo_full_name: str
    ) -> Dict[str, Any]:
        """Connect a repo for a user"""
        try:
            data = {
                "user_id": user_id,
                "github_repo_id": github_repo_id,
                "repo_full_name": repo_full_name,
                "is_active": True,
                "indexing_status": "pending",
            }

            response = self.client.table("connected_repos").insert(data).execute()
            return response.data[0]
        except Exception as e:
            logger.error(f"Failed to connect repo: {e}")
            raise

    async def disconnect_repo(self, user_id: str, github_repo_id: int) -> bool:
        """Disconnect a repo for a user"""
        try:
            self.client.table("connected_repos").delete().eq(
                "user_id", user_id
            ).eq("github_repo_id", github_repo_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect repo: {e}")
            raise

    async def update_repo_indexing_status(
        self,
        repo_id: str,
        status: str,
        last_indexed_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Update repo indexing status"""
        try:
            data = {"indexing_status": status}
            if last_indexed_at:
                data["last_indexed_at"] = last_indexed_at.isoformat()

            response = self.client.table("connected_repos").update(data).eq(
                "id", repo_id
            ).execute()
            return response.data[0]
        except Exception as e:
            logger.error(f"Failed to update repo indexing status: {e}")
            raise

    # Connected Notion pages operations
    async def get_connected_notion_pages(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all connected Notion pages for a user"""
        try:
            response = self.client.table("connected_notion_pages").select("*").eq(
                "user_id", user_id
            ).execute()
            return response.data or []
        except Exception as e:
            logger.error(f"Failed to get connected Notion pages: {e}")
            raise

    async def get_connected_notion_page(
        self, user_id: str, notion_page_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get connected Notion page"""
        try:
            response = self.client.table("connected_notion_pages").select("*").eq(
                "user_id", user_id
            ).eq("notion_page_id", notion_page_id).execute()

            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get connected Notion page: {e}")
            raise

    async def connect_notion_page(
        self,
        user_id: str,
        notion_page_id: str,
        notion_page_title: Optional[str] = None
    ) -> Dict[str, Any]:
        """Connect a Notion page for a user"""
        try:
            data = {
                "user_id": user_id,
                "notion_page_id": notion_page_id,
                "notion_page_title": notion_page_title,
                "is_active": True,
                "indexing_status": "pending",
            }

            response = self.client.table("connected_notion_pages").insert(data).execute()
            return response.data[0]
        except Exception as e:
            logger.error(f"Failed to connect Notion page: {e}")
            raise

    async def disconnect_notion_page(self, user_id: str, notion_page_id: str) -> bool:
        """Disconnect a Notion page for a user"""
        try:
            self.client.table("connected_notion_pages").delete().eq(
                "user_id", user_id
            ).eq("notion_page_id", notion_page_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect Notion page: {e}")
            raise

    async def update_notion_page_indexing_status(
        self,
        page_id: str,
        status: str
    ) -> Dict[str, Any]:
        """Update Notion page indexing status"""
        try:
            response = self.client.table("connected_notion_pages").update({
                "indexing_status": status
            }).eq("id", page_id).execute()
            return response.data[0]
        except Exception as e:
            logger.error(f"Failed to update Notion page indexing status: {e}")
            raise

    # Utility method for getting user by installation ID
    async def get_user_by_installation_id(
        self, installation_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get user by GitHub App installation ID"""
        try:
            response = self.client.table("users").select("*").eq(
                "github_app_installation_id", installation_id
            ).execute()

            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get user by installation ID: {e}")
            raise

    async def get_connected_repo_by_full_name(
        self, repo_full_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get connected repo by full name (owner/repo)"""
        try:
            response = self.client.table("connected_repos").select(
                "*, users(*)"
            ).eq("repo_full_name", repo_full_name).eq("is_active", True).execute()

            if response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get connected repo by full name: {e}")
            raise


# Singleton instance
_db_manager: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    """Get database manager instance"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
