"""Notion client for page content extraction"""

import logging
from typing import Dict, Any, List
from datetime import datetime

from notion_client import Client as NotionAPIClient

logger = logging.getLogger(__name__)


class NotionClient:
    """Client for extracting content from Notion pages"""
    
    def __init__(self, notion_token: str):
        self.client = NotionAPIClient(auth=notion_token)
    
    async def get_page_content(self, page_id: str) -> Dict[str, Any]:
        """Get page content as plain text with metadata"""
        try:
            # Get page metadata
            page = self.client.pages.retrieve(page_id=page_id)
            
            # Get page content blocks
            blocks = self._get_all_blocks(page_id)
            
            # Convert blocks to plain text
            content = self._blocks_to_text(blocks)
            
            return {
                "page_id": page_id,
                "url": page.get("url", ""),
                "last_edited_time": page.get("last_edited_time"),
                "content": content,
                "title": self._extract_title(page),
            }
            
        except Exception as e:
            logger.error(f"Failed to get Notion page content for {page_id}: {e}")
            raise
    
    def _get_all_blocks(self, block_id: str) -> List[Dict[str, Any]]:
        """Recursively get all blocks in a page"""
        blocks = []
        
        try:
            response = self.client.blocks.children.list(block_id=block_id)
            blocks.extend(response.get("results", []))
            
            # Handle pagination
            while response.get("has_more", False):
                response = self.client.blocks.children.list(
                    block_id=block_id,
                    start_cursor=response.get("next_cursor")
                )
                blocks.extend(response.get("results", []))
            
            # Recursively get child blocks
            all_blocks = []
            for block in blocks:
                all_blocks.append(block)
                
                # If block has children, get them too
                if block.get("has_children", False):
                    child_blocks = self._get_all_blocks(block["id"])
                    all_blocks.extend(child_blocks)
            
            return all_blocks
            
        except Exception as e:
            logger.error(f"Failed to get blocks for {block_id}: {e}")
            return []
    
    def _blocks_to_text(self, blocks: List[Dict[str, Any]]) -> str:
        """Convert Notion blocks to plain text"""
        text_parts = []
        
        for block in blocks:
            block_type = block.get("type", "")
            block_data = block.get(block_type, {})
            
            if block_type == "paragraph":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(text)
            
            elif block_type == "heading_1":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(f"# {text}")
            
            elif block_type == "heading_2":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(f"## {text}")
            
            elif block_type == "heading_3":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(f"### {text}")
            
            elif block_type == "bulleted_list_item":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(f"- {text}")
            
            elif block_type == "numbered_list_item":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(f"1. {text}")
            
            elif block_type == "to_do":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                checked = block_data.get("checked", False)
                checkbox = "[x]" if checked else "[ ]"
                if text:
                    text_parts.append(f"{checkbox} {text}")
            
            elif block_type == "toggle":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(f"> {text}")
            
            elif block_type == "quote":
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
            
            elif block_type == "callout":
                text = self._rich_text_to_plain(block_data.get("rich_text", []))
                if text:
                    text_parts.append(f"> **Note:** {text}")
            
            # Add spacing between blocks
            if text_parts and not text_parts[-1].endswith("\n"):
                text_parts[-1] += "\n"
        
        return "\n".join(text_parts)
    
    def _rich_text_to_plain(self, rich_text: List[Dict[str, Any]]) -> str:
        """Convert Notion rich text to plain text"""
        text_parts = []
        
        for text_item in rich_text:
            text = text_item.get("plain_text", "")
            
            # Handle annotations
            annotations = text_item.get("annotations", {})
            
            if annotations.get("bold", False):
                text = f"**{text}**"
            elif annotations.get("italic", False):
                text = f"*{text}*"
            elif annotations.get("strikethrough", False):
                text = f"~~{text}~~"
            elif annotations.get("underline", False):
                text = f"_{text}_"
            elif annotations.get("code", False):
                text = f"`{text}`"
            
            # Handle links
            if text_item.get("href"):
                href = text_item["href"]
                text = f"[{text}]({href})"
            
            text_parts.append(text)
        
        return "".join(text_parts)
    
    def _extract_title(self, page: Dict[str, Any]) -> str:
        """Extract page title from page properties"""
        properties = page.get("properties", {})
        
        # Look for common title property names
        title_keys = ["Name", "Title", "title", "name"]
        
        for key in title_keys:
            if key in properties:
                prop = properties[key]
                if prop.get("type") == "title":
                    title_text = prop.get("title", [])
                    if title_text:
                        return title_text[0].get("plain_text", "")
        
        return "Untitled"
