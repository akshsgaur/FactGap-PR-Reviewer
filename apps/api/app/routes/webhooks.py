"""GitHub webhook handlers"""

import hmac
import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from app.config import get_settings
from app.database import get_db
from app.services.github_app import get_github_service
from app.services.indexing import get_indexing_service
from app.services.analysis import get_analysis_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def verify_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature"""
    if not signature.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature, expected)


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Handle GitHub webhooks"""
    settings = get_settings()

    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    payload = await request.body()

    if not verify_github_signature(payload, signature, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse event
    event_type = request.headers.get("X-GitHub-Event", "")
    data = await request.json()

    logger.info(f"Received GitHub webhook: {event_type}")

    # Route to appropriate handler
    if event_type == "pull_request":
        await handle_pull_request(data, background_tasks)
    elif event_type == "issue_comment":
        await handle_issue_comment(data, background_tasks)
    elif event_type == "installation":
        await handle_installation(data)
    else:
        logger.debug(f"Ignoring event type: {event_type}")

    return {"status": "ok"}


async def handle_pull_request(data: dict, background_tasks: BackgroundTasks):
    """Handle pull_request events"""
    action = data.get("action")

    # Only handle opened, reopened, and synchronize events
    if action not in ["opened", "reopened", "synchronize"]:
        logger.debug(f"Ignoring PR action: {action}")
        return

    repo_full_name = data["repository"]["full_name"]
    pr_number = data["pull_request"]["number"]
    installation_id = data.get("installation", {}).get("id")

    if not installation_id:
        logger.warning("No installation ID in webhook")
        return

    db = get_db()

    # Find connected repo
    connected_repo = await db.get_connected_repo_by_full_name(repo_full_name)

    if not connected_repo:
        logger.debug(f"Repo {repo_full_name} not connected, skipping")
        return

    user_id = connected_repo["user_id"]

    logger.info(f"Processing PR #{pr_number} in {repo_full_name}")

    # Schedule background analysis
    background_tasks.add_task(
        process_pr_analysis,
        user_id,
        installation_id,
        repo_full_name,
        pr_number,
    )


async def handle_issue_comment(data: dict, background_tasks: BackgroundTasks):
    """Handle issue_comment events (for @code-reviewer mentions)"""
    action = data.get("action")

    if action != "created":
        return

    # Check if this is a PR comment
    issue = data.get("issue", {})
    if not issue.get("pull_request"):
        return

    comment = data.get("comment", {})
    comment_body = comment.get("body", "")

    # Check for @code-reviewer mention
    if "@code-reviewer" not in comment_body:
        return

    repo_full_name = data["repository"]["full_name"]
    pr_number = issue["number"]
    installation_id = data.get("installation", {}).get("id")
    comment_user = comment.get("user", {}).get("login", "unknown")

    if not installation_id:
        logger.warning("No installation ID in webhook")
        return

    db = get_db()

    # Find connected repo
    connected_repo = await db.get_connected_repo_by_full_name(repo_full_name)

    if not connected_repo:
        logger.debug(f"Repo {repo_full_name} not connected, skipping")
        return

    user_id = connected_repo["user_id"]

    # Extract question (text after @code-reviewer)
    question = comment_body.split("@code-reviewer", 1)[1].strip()

    if not question:
        logger.debug("Empty question, skipping")
        return

    logger.info(f"Processing @code-reviewer question in PR #{pr_number}")

    # Schedule background chat response
    background_tasks.add_task(
        process_chat_response,
        user_id,
        installation_id,
        repo_full_name,
        pr_number,
        question,
        comment_user,
    )


async def handle_installation(data: dict):
    """Handle installation events"""
    action = data.get("action")
    installation_id = data.get("installation", {}).get("id")

    if action == "deleted":
        logger.info(f"Installation {installation_id} deleted")
        # Could clean up user data here if needed

    elif action == "created":
        logger.info(f"New installation {installation_id} created")
        # User will connect via OAuth flow


async def process_pr_analysis(
    user_id: str,
    installation_id: int,
    repo_full_name: str,
    pr_number: int,
):
    """Process PR analysis in background"""
    try:
        indexing_service = get_indexing_service()
        github_service = get_github_service()
        analysis_service = get_analysis_service()

        # Index PR content
        await indexing_service.index_pr(
            user_id,
            installation_id,
            repo_full_name,
            pr_number,
        )

        # Generate analysis
        analysis = await analysis_service.analyze_pr(
            user_id,
            installation_id,
            repo_full_name,
            pr_number,
        )

        # Post comment
        await github_service.create_pr_comment(
            installation_id,
            repo_full_name,
            pr_number,
            analysis,
        )

        logger.info(f"Posted analysis for PR #{pr_number} in {repo_full_name}")

    except Exception as e:
        logger.error(f"Error processing PR analysis: {e}")


async def process_chat_response(
    user_id: str,
    installation_id: int,
    repo_full_name: str,
    pr_number: int,
    question: str,
    asker_username: str,
):
    """Process chat response in background"""
    try:
        github_service = get_github_service()
        analysis_service = get_analysis_service()

        # Generate answer
        answer = await analysis_service.answer_question(
            user_id,
            installation_id,
            repo_full_name,
            pr_number,
            question,
        )

        # Format response with mention
        response = f"@{asker_username}\n\n{answer}"

        # Post comment
        await github_service.create_pr_comment(
            installation_id,
            repo_full_name,
            pr_number,
            response,
        )

        logger.info(f"Posted chat response for PR #{pr_number} in {repo_full_name}")

    except Exception as e:
        logger.error(f"Error processing chat response: {e}")
