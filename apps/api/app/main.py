"""FastAPI application entry point"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes import auth, repos, notion, webhooks

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    settings = get_settings()
    if not settings.is_configured():
        logger.warning(
            "Using placeholder credentials. Set environment variables or create .env file "
            "in apps/api/ for full functionality."
        )
    logger.info("Starting FactGap PR Reviewer API")
    yield
    logger.info("Shutting down FactGap PR Reviewer API")


app = FastAPI(
    title="FactGap PR Reviewer API",
    description="API for the FactGap PR Reviewer SaaS",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware - allow common development origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(notion.router)
app.include_router(webhooks.router)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "factgap-pr-reviewer-api",
        "version": "0.1.0"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    from app.config import get_settings
    settings = get_settings()
    return {
        "status": "healthy",
        "configured": settings.is_configured()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
