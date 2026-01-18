"""Pydantic models for API requests/responses"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# User models
class UserBase(BaseModel):
    github_id: int
    github_login: str


class UserCreate(UserBase):
    github_access_token: Optional[str] = None
    github_app_installation_id: Optional[int] = None


class User(UserBase):
    id: str
    notion_workspace_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    id: str
    github_login: str
    has_notion_connected: bool
    created_at: datetime


# Auth models
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class GitHubAuthURL(BaseModel):
    url: str


class NotionAuthURL(BaseModel):
    url: str


# Repository models
class RepoBase(BaseModel):
    github_repo_id: int
    repo_full_name: str


class ConnectedRepo(RepoBase):
    id: str
    is_active: bool
    indexing_status: str
    last_indexed_at: Optional[datetime] = None


class RepoListItem(BaseModel):
    id: int
    full_name: str
    private: bool
    description: Optional[str] = None
    is_connected: bool = False


class RepoEnableRequest(BaseModel):
    repo_id: int
    repo_full_name: str


# Notion models
class NotionPageBase(BaseModel):
    notion_page_id: str
    notion_page_title: Optional[str] = None


class ConnectedNotionPage(NotionPageBase):
    id: str
    is_active: bool
    indexing_status: str


class NotionPageListItem(BaseModel):
    id: str
    title: str
    url: str
    is_connected: bool = False


class NotionPageEnableRequest(BaseModel):
    page_id: str
    page_title: Optional[str] = None


# Webhook models
class GitHubWebhookPayload(BaseModel):
    action: str
    repository: dict
    sender: dict
    installation: Optional[dict] = None
    pull_request: Optional[dict] = None
    issue: Optional[dict] = None
    comment: Optional[dict] = None


# Indexing models
class IndexingStatus(BaseModel):
    status: str
    message: Optional[str] = None
    chunks_indexed: Optional[int] = None


# Analysis models
class PRAnalysisResult(BaseModel):
    pr_number: int
    repo_full_name: str
    analysis: str
    created_at: datetime
