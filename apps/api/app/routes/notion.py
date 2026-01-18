"""Notion pages management routes"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from app.auth import get_current_user
from app.database import get_db, DatabaseManager
from app.models import (
    NotionPageListItem,
    ConnectedNotionPage,
    NotionPageEnableRequest,
    IndexingStatus,
)
from app.services.notion_oauth import get_notion_service, NotionOAuthService
from app.services.indexing import get_indexing_service, IndexingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notion", tags=["notion"])


@router.get("/pages", response_model=List[NotionPageListItem])
async def list_notion_pages(
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
    notion_service: NotionOAuthService = Depends(get_notion_service),
):
    """List all Notion pages accessible to the user"""
    # Get user's Notion token
    notion_token = await db.get_user_notion_token(current_user["id"])

    if not notion_token:
        raise HTTPException(
            status_code=400,
            detail="Notion not connected. Please connect your Notion account first."
        )

    try:
        # Get pages from Notion
        pages = await notion_service.search_pages(notion_token)

        # Get connected pages
        connected_pages = await db.get_connected_notion_pages(current_user["id"])
        connected_page_ids = {p["notion_page_id"] for p in connected_pages}

        # Build response
        return [
            NotionPageListItem(
                id=page["id"],
                title=page["title"],
                url=page["url"],
                is_connected=page["id"] in connected_page_ids,
            )
            for page in pages
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing Notion pages: {e}")
        raise HTTPException(status_code=500, detail="Failed to list Notion pages")


@router.get("/connected", response_model=List[ConnectedNotionPage])
async def list_connected_pages(
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
):
    """List all connected Notion pages for the current user"""
    try:
        pages = await db.get_connected_notion_pages(current_user["id"])
        return [
            ConnectedNotionPage(
                id=p["id"],
                notion_page_id=p["notion_page_id"],
                notion_page_title=p.get("notion_page_title"),
                is_active=p["is_active"],
                indexing_status=p["indexing_status"],
            )
            for p in pages
        ]
    except Exception as e:
        logger.error(f"Error listing connected Notion pages: {e}")
        raise HTTPException(status_code=500, detail="Failed to list connected pages")


@router.post("/pages/{page_id}/enable", response_model=ConnectedNotionPage)
async def enable_notion_page(
    page_id: str,
    request: NotionPageEnableRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
    indexing_service: IndexingService = Depends(get_indexing_service),
):
    """Enable a Notion page for RAG"""
    # Get user's Notion token
    notion_token = await db.get_user_notion_token(current_user["id"])

    if not notion_token:
        raise HTTPException(
            status_code=400,
            detail="Notion not connected"
        )

    # Check if page is already connected
    existing = await db.get_connected_notion_page(current_user["id"], page_id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Notion page is already connected"
        )

    try:
        # Connect the page
        connected = await db.connect_notion_page(
            current_user["id"],
            page_id,
            request.page_title,
        )

        # Start background indexing
        background_tasks.add_task(
            indexing_service.index_notion_page,
            current_user["id"],
            connected["id"],
            page_id,
            notion_token,
        )

        return ConnectedNotionPage(
            id=connected["id"],
            notion_page_id=connected["notion_page_id"],
            notion_page_title=connected.get("notion_page_title"),
            is_active=connected["is_active"],
            indexing_status=connected["indexing_status"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error enabling Notion page: {e}")
        raise HTTPException(status_code=500, detail="Failed to enable Notion page")


@router.delete("/pages/{page_id}/disable")
async def disable_notion_page(
    page_id: str,
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
    indexing_service: IndexingService = Depends(get_indexing_service),
):
    """Disable a Notion page"""
    try:
        # Get the connected page
        connected = await db.get_connected_notion_page(current_user["id"], page_id)

        if not connected:
            raise HTTPException(
                status_code=404,
                detail="Notion page not connected"
            )

        # Delete chunks for this page (by source_id)
        from app.services.indexing import get_indexing_service
        service = get_indexing_service()
        service.supabase.table("rag_chunks").delete().eq(
            "user_id", current_user["id"]
        ).eq("source_type", "notion").eq("source_id", page_id).execute()

        # Disconnect the page
        await db.disconnect_notion_page(current_user["id"], page_id)

        return {"message": "Notion page disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling Notion page: {e}")
        raise HTTPException(status_code=500, detail="Failed to disable Notion page")


@router.post("/pages/{page_id}/reindex", response_model=IndexingStatus)
async def reindex_notion_page(
    page_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
    indexing_service: IndexingService = Depends(get_indexing_service),
):
    """Trigger reindexing of a Notion page"""
    # Get user's Notion token
    notion_token = await db.get_user_notion_token(current_user["id"])

    if not notion_token:
        raise HTTPException(
            status_code=400,
            detail="Notion not connected"
        )

    try:
        # Get the connected page
        connected = await db.get_connected_notion_page(current_user["id"], page_id)

        if not connected:
            raise HTTPException(
                status_code=404,
                detail="Notion page not connected"
            )

        # Delete existing chunks
        indexing_service.supabase.table("rag_chunks").delete().eq(
            "user_id", current_user["id"]
        ).eq("source_type", "notion").eq("source_id", page_id).execute()

        # Update status
        await db.update_notion_page_indexing_status(connected["id"], "pending")

        # Start background indexing
        background_tasks.add_task(
            indexing_service.index_notion_page,
            current_user["id"],
            connected["id"],
            page_id,
            notion_token,
        )

        return IndexingStatus(
            status="pending",
            message="Reindexing started"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reindexing Notion page: {e}")
        raise HTTPException(status_code=500, detail="Failed to start reindexing")
