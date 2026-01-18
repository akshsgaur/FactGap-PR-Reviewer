"""Authentication routes"""

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse

from app.auth import create_access_token, get_current_user
from app.config import get_settings
from app.database import get_db, DatabaseManager
from app.models import TokenResponse, GitHubAuthURL, NotionAuthURL, UserResponse
from app.services.github_app import get_github_service, GitHubAppService
from app.services.notion_oauth import get_notion_service, NotionOAuthService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# In-memory state storage (use Redis in production)
_oauth_states: dict = {}


@router.get("/github/authorize", response_model=GitHubAuthURL)
async def github_authorize():
    """Get GitHub OAuth authorization URL"""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"type": "github"}

    github_service = get_github_service()
    url = github_service.get_oauth_url(state)

    return GitHubAuthURL(url=url)


@router.get("/github/callback")
async def github_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: DatabaseManager = Depends(get_db),
    github_service: GitHubAppService = Depends(get_github_service),
):
    """Handle GitHub OAuth callback"""
    settings = get_settings()

    # Verify state
    if state not in _oauth_states or _oauth_states[state]["type"] != "github":
        raise HTTPException(status_code=400, detail="Invalid state")

    del _oauth_states[state]

    try:
        # Exchange code for token
        token_data = await github_service.exchange_code_for_token(code)

        if "error" in token_data:
            raise HTTPException(
                status_code=400,
                detail=token_data.get("error_description", "OAuth failed")
            )

        access_token = token_data["access_token"]

        # Get user info
        user_info = await github_service.get_user_info(access_token)
        github_id = user_info["id"]
        github_login = user_info["login"]

        # Get installation ID if available
        installations = await github_service.get_user_installations(access_token)
        installation_id = installations[0]["id"] if installations else None

        # Find or create user
        user = await db.get_user_by_github_id(github_id)

        if user:
            # Update existing user
            user = await db.update_user(
                user["id"],
                github_login=github_login,
                github_access_token=access_token,
                github_app_installation_id=installation_id,
            )
        else:
            # Create new user
            user = await db.create_user(
                github_id=github_id,
                github_login=github_login,
                github_access_token=access_token,
                github_app_installation_id=installation_id,
            )

        # Create JWT token
        jwt_token = create_access_token(user["id"])

        # Redirect to frontend with token
        redirect_url = f"{settings.app_url}/auth/callback?token={jwt_token}"
        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GitHub OAuth error: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")


@router.get("/notion/authorize", response_model=NotionAuthURL)
async def notion_authorize(
    current_user: dict = Depends(get_current_user),
):
    """Get Notion OAuth authorization URL (requires authentication)"""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"type": "notion", "user_id": current_user["id"]}

    notion_service = get_notion_service()
    url = notion_service.get_oauth_url(state)

    return NotionAuthURL(url=url)


@router.get("/notion/callback")
async def notion_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: DatabaseManager = Depends(get_db),
    notion_service: NotionOAuthService = Depends(get_notion_service),
):
    """Handle Notion OAuth callback"""
    settings = get_settings()

    # Verify state
    if state not in _oauth_states or _oauth_states[state]["type"] != "notion":
        raise HTTPException(status_code=400, detail="Invalid state")

    state_data = _oauth_states[state]
    user_id = state_data.get("user_id")
    del _oauth_states[state]

    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user context")

    try:
        # Exchange code for token
        token_data = await notion_service.exchange_code_for_token(code)

        access_token = token_data["access_token"]
        workspace_id = token_data.get("workspace_id")

        # Update user with Notion credentials
        await db.update_user(
            user_id,
            notion_access_token=access_token,
            notion_workspace_id=workspace_id,
        )

        # Redirect to frontend
        redirect_url = f"{settings.app_url}/dashboard/notion?connected=true"
        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Notion OAuth error: {e}")
        redirect_url = f"{settings.app_url}/dashboard/notion?error=auth_failed"
        return RedirectResponse(url=redirect_url)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: dict = Depends(get_current_user),
):
    """Get current user info"""
    return UserResponse(
        id=current_user["id"],
        github_login=current_user["github_login"],
        has_notion_connected=current_user.get("notion_access_token") is not None,
        created_at=current_user["created_at"],
    )


@router.post("/logout")
async def logout(response: Response):
    """Logout endpoint (client should clear token)"""
    # JWT tokens are stateless, so logout is handled client-side
    # This endpoint is for any server-side cleanup if needed
    return {"message": "Logged out successfully"}
