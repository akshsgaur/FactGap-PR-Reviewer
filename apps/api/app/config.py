"""Application configuration"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


# Find the .env file - check multiple locations
def find_env_file() -> Optional[str]:
    """Find .env file in current dir, api dir, or project root"""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).parent.parent / ".env",  # apps/api/.env
        Path(__file__).parent.parent.parent.parent / ".env",  # project root .env
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase
    supabase_url: str = "http://localhost:54321"
    supabase_service_role_key: str = "your-service-role-key"

    # OpenAI
    openai_api_key: str = "sk-placeholder"

    # GitHub App
    github_app_id: str = "123456"
    github_app_private_key: str = "-----BEGIN RSA PRIVATE KEY-----\nplaceholder\n-----END RSA PRIVATE KEY-----"
    github_app_client_id: str = "Iv1.placeholder"
    github_app_client_secret: str = "placeholder"
    github_webhook_secret: str = "placeholder"

    # Notion OAuth
    notion_client_id: str = "placeholder"
    notion_client_secret: str = "placeholder"

    # JWT
    jwt_secret: str = "dev-jwt-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24 * 7  # 1 week

    # App
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"

    # Encryption key for storing tokens
    encryption_key: Optional[str] = None

    def is_configured(self) -> bool:
        """Check if real credentials are configured"""
        return (
            self.supabase_url != "http://localhost:54321"
            and self.openai_api_key != "sk-placeholder"
        )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
