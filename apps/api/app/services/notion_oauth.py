"""Notion OAuth service"""

import logging
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class NotionOAuthService:
    """Service for Notion OAuth operations"""

    def __init__(self):
        self.settings = get_settings()

    def get_oauth_url(self, state: str) -> str:
        """Generate Notion OAuth authorization URL"""
        params = {
            "client_id": self.settings.notion_client_id,
            "redirect_uri": f"{self.settings.api_url}/api/auth/notion/callback",
            "response_type": "code",
            "owner": "user",
            "state": state,
        }
        return f"https://api.notion.com/v1/oauth/authorize?{urlencode(params)}"

    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """Exchange OAuth code for access token"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.notion.com/v1/oauth/token",
                headers={
                    "Content-Type": "application/json",
                },
                auth=(self.settings.notion_client_id, self.settings.notion_client_secret),
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": f"{self.settings.api_url}/api/auth/notion/callback",
                },
            )
            response.raise_for_status()
            return response.json()

    async def search_pages(
        self,
        access_token: str,
        query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search for pages accessible to the user"""
        async with httpx.AsyncClient() as client:
            body: Dict[str, Any] = {
                "filter": {
                    "property": "object",
                    "value": "page"
                },
                "sort": {
                    "direction": "descending",
                    "timestamp": "last_edited_time"
                },
                "page_size": 100,
            }

            if query:
                body["query"] = query

            response = await client.post(
                "https://api.notion.com/v1/search",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            data = response.json()

            pages = []
            for result in data.get("results", []):
                if result.get("object") == "page":
                    # Extract title
                    title = "Untitled"
                    properties = result.get("properties", {})
                    for prop in properties.values():
                        if prop.get("type") == "title":
                            title_list = prop.get("title", [])
                            if title_list:
                                title = title_list[0].get("plain_text", "Untitled")
                            break

                    pages.append({
                        "id": result["id"],
                        "title": title,
                        "url": result.get("url", ""),
                        "last_edited_time": result.get("last_edited_time"),
                    })

            return pages

    async def get_page(self, access_token: str, page_id: str) -> Dict[str, Any]:
        """Get page details"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Notion-Version": "2022-06-28",
                },
            )
            response.raise_for_status()
            return response.json()

    async def get_page_content(
        self,
        access_token: str,
        page_id: str
    ) -> Dict[str, Any]:
        """Get page content as text"""
        async with httpx.AsyncClient() as client:
            # Get page metadata
            page = await self.get_page(access_token, page_id)

            # Get all blocks
            blocks = await self._get_all_blocks(client, access_token, page_id)

            # Convert to text
            content = self._blocks_to_text(blocks)

            # Extract title
            title = "Untitled"
            properties = page.get("properties", {})
            for prop in properties.values():
                if prop.get("type") == "title":
                    title_list = prop.get("title", [])
                    if title_list:
                        title = title_list[0].get("plain_text", "Untitled")
                    break

            return {
                "page_id": page_id,
                "title": title,
                "url": page.get("url", ""),
                "last_edited_time": page.get("last_edited_time"),
                "content": content,
            }

    async def _get_all_blocks(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        block_id: str
    ) -> List[Dict[str, Any]]:
        """Recursively get all blocks"""
        blocks = []
        cursor = None

        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor

            response = await client.get(
                f"https://api.notion.com/v1/blocks/{block_id}/children",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Notion-Version": "2022-06-28",
                },
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            for block in data.get("results", []):
                blocks.append(block)

                # Recursively get child blocks
                if block.get("has_children", False):
                    child_blocks = await self._get_all_blocks(
                        client, access_token, block["id"]
                    )
                    blocks.extend(child_blocks)

            if not data.get("has_more", False):
                break
            cursor = data.get("next_cursor")

        return blocks

    def _blocks_to_text(self, blocks: List[Dict[str, Any]]) -> str:
        """Convert blocks to plain text"""
        text_parts = []

        for block in blocks:
            block_type = block.get("type", "")
            block_data = block.get(block_type, {})

            if block_type == "paragraph":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(text)

            elif block_type in ["heading_1", "heading_2", "heading_3"]:
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                level = int(block_type[-1])
                prefix = "#" * level
                if text:
                    text_parts.append(f"{prefix} {text}")

            elif block_type in ["bulleted_list_item", "numbered_list_item"]:
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    prefix = "-" if block_type == "bulleted_list_item" else "1."
                    text_parts.append(f"{prefix} {text}")

            elif block_type == "to_do":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                checked = "[x]" if block_data.get("checked", False) else "[ ]"
                if text:
                    text_parts.append(f"{checked} {text}")

            elif block_type in ["toggle", "quote", "callout"]:
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(f"> {text}")

            elif block_type == "code":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                language = block_data.get("language", "")
                if text:
                    text_parts.append(f"```{language}\n{text}\n```")

            elif block_type == "divider":
                text_parts.append("---")

        return "\n\n".join(text_parts)

    def _rich_text_to_plain(self, rich_text: List[Dict[str, Any]]) -> str:
        """Convert rich text to plain text"""
        return "".join(item.get("plain_text", "") for item in rich_text)


# Singleton instance
_notion_service: Optional[NotionOAuthService] = None


def get_notion_service() -> NotionOAuthService:
    """Get Notion service instance"""
    global _notion_service
    if _notion_service is None:
        _notion_service = NotionOAuthService()
    return _notion_service
