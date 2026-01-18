"""Repository management routes"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from app.auth import get_current_user
from app.database import get_db, DatabaseManager
from app.models import RepoListItem, ConnectedRepo, RepoEnableRequest, IndexingStatus
from app.services.github_app import get_github_service, GitHubAppService
from app.services.indexing import get_indexing_service, IndexingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/repos", tags=["repos"])


@router.get("/", response_model=List[RepoListItem])
async def list_available_repos(
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
    github_service: GitHubAppService = Depends(get_github_service),
):
    """List all repositories available from GitHub App installation"""
    installation_id = current_user.get("github_app_installation_id")

    if not installation_id:
        raise HTTPException(
            status_code=400,
            detail="GitHub App not installed. Please install the app first."
        )

    try:
        # Get repos from GitHub
        github_repos = await github_service.get_installation_repos(installation_id)

        # Get connected repos for this user
        connected_repos = await db.get_connected_repos(current_user["id"])
        connected_repo_ids = {r["github_repo_id"] for r in connected_repos}

        # Build response
        repos = []
        for repo in github_repos:
            repos.append(RepoListItem(
                id=repo["id"],
                full_name=repo["full_name"],
                private=repo["private"],
                description=repo.get("description"),
                is_connected=repo["id"] in connected_repo_ids,
            ))

        return repos

    except Exception as e:
        logger.error(f"Error listing repos: {e}")
        raise HTTPException(status_code=500, detail="Failed to list repositories")


@router.get("/connected", response_model=List[ConnectedRepo])
async def list_connected_repos(
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
):
    """List all connected repositories for the current user"""
    try:
        repos = await db.get_connected_repos(current_user["id"])
        return [
            ConnectedRepo(
                id=r["id"],
                github_repo_id=r["github_repo_id"],
                repo_full_name=r["repo_full_name"],
                is_active=r["is_active"],
                indexing_status=r["indexing_status"],
                last_indexed_at=r.get("last_indexed_at"),
            )
            for r in repos
        ]
    except Exception as e:
        logger.error(f"Error listing connected repos: {e}")
        raise HTTPException(status_code=500, detail="Failed to list connected repos")


@router.post("/{repo_id}/enable", response_model=ConnectedRepo)
async def enable_repo(
    repo_id: int,
    request: RepoEnableRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
    github_service: GitHubAppService = Depends(get_github_service),
    indexing_service: IndexingService = Depends(get_indexing_service),
):
    """Enable a repository for PR analysis"""
    installation_id = current_user.get("github_app_installation_id")

    if not installation_id:
        raise HTTPException(
            status_code=400,
            detail="GitHub App not installed"
        )

    # Check if repo is already connected
    existing = await db.get_connected_repo_by_github_id(
        current_user["id"], repo_id
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Repository is already connected"
        )

    try:
        # Verify the repo is accessible
        repos = await github_service.get_installation_repos(installation_id)
        repo_data = next((r for r in repos if r["id"] == repo_id), None)

        if not repo_data:
            raise HTTPException(
                status_code=404,
                detail="Repository not found or not accessible"
            )

        # Connect the repo
        connected = await db.connect_repo(
            current_user["id"],
            repo_id,
            request.repo_full_name,
        )

        # Start background indexing
        background_tasks.add_task(
            indexing_service.index_repository,
            current_user["id"],
            connected["id"],
            installation_id,
            request.repo_full_name,
        )

        return ConnectedRepo(
            id=connected["id"],
            github_repo_id=connected["github_repo_id"],
            repo_full_name=connected["repo_full_name"],
            is_active=connected["is_active"],
            indexing_status=connected["indexing_status"],
            last_indexed_at=connected.get("last_indexed_at"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error enabling repo: {e}")
        raise HTTPException(status_code=500, detail="Failed to enable repository")


@router.delete("/{repo_id}/disable")
async def disable_repo(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
    indexing_service: IndexingService = Depends(get_indexing_service),
):
    """Disable a repository (removes from PR analysis)"""
    try:
        # Get the connected repo
        connected = await db.get_connected_repo_by_github_id(
            current_user["id"], repo_id
        )

        if not connected:
            raise HTTPException(
                status_code=404,
                detail="Repository not connected"
            )

        # Delete chunks for this repo
        await indexing_service.delete_user_chunks(
            current_user["id"],
            connected["repo_full_name"]
        )

        # Disconnect the repo
        await db.disconnect_repo(current_user["id"], repo_id)

        return {"message": "Repository disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling repo: {e}")
        raise HTTPException(status_code=500, detail="Failed to disable repository")


@router.post("/{repo_id}/reindex", response_model=IndexingStatus)
async def reindex_repo(
    repo_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
    indexing_service: IndexingService = Depends(get_indexing_service),
):
    """Trigger reindexing of a repository"""
    installation_id = current_user.get("github_app_installation_id")

    if not installation_id:
        raise HTTPException(
            status_code=400,
            detail="GitHub App not installed"
        )

    try:
        # Get the connected repo
        connected = await db.get_connected_repo_by_github_id(
            current_user["id"], repo_id
        )

        if not connected:
            raise HTTPException(
                status_code=404,
                detail="Repository not connected"
            )

        # Delete existing chunks
        await indexing_service.delete_user_chunks(
            current_user["id"],
            connected["repo_full_name"]
        )

        # Update status
        await db.update_repo_indexing_status(connected["id"], "pending")

        # Start background indexing
        background_tasks.add_task(
            indexing_service.index_repository,
            current_user["id"],
            connected["id"],
            installation_id,
            connected["repo_full_name"],
        )

        return IndexingStatus(
            status="pending",
            message="Reindexing started"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reindexing repo: {e}")
        raise HTTPException(status_code=500, detail="Failed to start reindexing")
