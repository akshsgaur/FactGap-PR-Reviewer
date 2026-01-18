"""Authentication utilities"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from app.config import get_settings
from app.database import get_db, DatabaseManager

logger = logging.getLogger(__name__)

security = HTTPBearer()


def create_access_token(user_id: str) -> str:
    """Create a JWT access token for a user"""
    settings = get_settings()
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_expiration_hours)

    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.utcnow(),
    }

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[str]:
    """Decode and validate a JWT access token, returns user_id"""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm]
        )
        return payload.get("sub")
    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: DatabaseManager = Depends(get_db)
) -> dict:
    """Get current authenticated user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise credentials_exception

    user = await db.get_user_by_id(user_id)
    if user is None:
        raise credentials_exception

    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: DatabaseManager = Depends(get_db)
) -> Optional[dict]:
    """Get current user if authenticated, None otherwise"""
    if credentials is None:
        return None

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        return None

    return await db.get_user_by_id(user_id)
