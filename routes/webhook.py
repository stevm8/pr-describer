"""
routes/webhook.py — GitHub App webhook handler.

GitHub sends POST requests here for every event on installed repos.
We only care about:
  • pull_request → opened / reopened / synchronize (new commits pushed)
  • installation → created / deleted (app installed/uninstalled)
  • installation_repositories → added / removed

Security: every request is HMAC-SHA256 signed by GitHub using our webhook secret.
We verify this before doing anything else.
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Header
from config import get_settings
import db
from services.github import get_installation_token, get_pr_diff, update_pr_description, post_pr_comment
from services.groq_ai import generate_pr_description

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Signature verification ────────────────────────────────────────────────────

def verify_signature(payload: bytes, signature: str) -> bool:
    """
    GitHub signs every webhook with HMAC-SHA256.
    The header is: X-Hub-Signature-256: sha256=<hex>
    """
    secret = get_settings().github_webhook_secret.encode()
    expected = "sha256=" + hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Main webhook endpoint ─────────────────────────────────────────────────────

@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(...),
    x_hub_signature_256: str = Header(...),
):
    payload_bytes = await request.body()

    # Security check first — reject anything that doesn't match our secret
    if not verify_signature(payload_bytes, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    action = payload.get("action", "")

    logger.info(f"GitHub event: {x_github_event} / action: {action}")

    # Route to the right handler
    if x_github_event == "pull_request":
        await handle_pull_request(payload, action)

    elif x_github_event == "installation":
        await handle_installation(payload, action)

    elif x_github_event == "installation_repositories":
        await handle_installation_repositories(payload, action)

    # Always return 200 to GitHub — they retry on non-2xx responses
    return {"ok": True}


# ── Pull request handler ──────────────────────────────────────────────────────

async def handle_pull_request(payload: dict, action: str):
    """
    Triggered when a PR is opened, reopened, or gets new commits.
    We skip if the PR already has a description (body is non-empty)
    so we don't overwrite intentional descriptions.
    """
    # Only act on these actions
    if action not in ("opened", "reopened", "synchronize"):
        return

    pr = payload["pull_request"]
    installation_id = payload["installation"]["id"]
    repo = payload["repository"]

    pr_number = pr["number"]
    pr_title = pr.get("title", "")
    pr_body = pr.get("body") or ""
    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    base_branch = pr["base"]["ref"]

    # Skip draft PRs (uncomment to enable)
    # if pr.get("draft"):
    #     return

    # Skip if the PR already has a non-empty, non-template description
    # (We don't want to overwrite if the dev wrote something themselves)
    meaningful_body = pr_body.strip().replace("<!-- -->", "").strip()
    if action == "opened" and meaningful_body:
        logger.info(f"PR #{pr_number} already has a description — skipping")
        return

    # Check subscription is active
    if not await db.has_active_subscription(installation_id):
        logger.info(f"Installation {installation_id} has no active subscription — skipping")
        # Post a friendly comment pointing them to billing (only on first open)
        if action == "opened":
            token = await get_installation_token(installation_id)
            settings = get_settings()
            await post_pr_comment(
                owner, repo_name, pr_number,
                f"👋 **PR Describer** is installed but not yet active.\n\n"
                f"[Start your free 14-day trial →]({settings.app_url}/billing/checkout?installation_id={installation_id})",
                token,
            )
        return

    # Get installation token and fetch the diff
    try:
        token = await get_installation_token(installation_id)
        diff = await get_pr_diff(owner, repo_name, pr_number, token)
    except Exception as e:
        logger.error(f"Failed to fetch diff for PR #{pr_number}: {e}")
        return

    if not diff or not diff.strip():
        logger.info(f"PR #{pr_number} has empty diff — nothing to describe")
        return

    # Generate the description
    try:
        description = await generate_pr_description(
            diff=diff,
            pr_title=pr_title,
            repo_name=f"{owner}/{repo_name}",
            base_branch=base_branch,
        )
    except Exception as e:
        logger.error(f"Groq generation failed for PR #{pr_number}: {e}")
        return

    # Post it back to the PR
    try:
        await update_pr_description(owner, repo_name, pr_number, description, token)
        logger.info(f"✅ Updated description for {owner}/{repo_name}#{pr_number}")
    except Exception as e:
        logger.error(f"Failed to update PR description: {e}")


# ── Installation lifecycle ────────────────────────────────────────────────────

async def handle_installation(payload: dict, action: str):
    """Track when the GitHub App is installed or uninstalled."""
    installation = payload["installation"]
    installation_id = installation["id"]
    account = installation["account"]

    if action == "created":
        await db.upsert_installation(
            installation_id=installation_id,
            account_login=account["login"],
            account_type=account["type"],
        )
        logger.info(f"New installation: {account['login']} (#{installation_id})")

    elif action in ("deleted", "suspend"):
        await db.suspend_installation(installation_id)
        logger.info(f"Installation suspended: #{installation_id}")


async def handle_installation_repositories(payload: dict, action: str):
    """Called when repos are added/removed from an existing installation."""
    # For now we just log — all repos under an installation share one subscription
    installation_id = payload["installation"]["id"]
    repos_added = [r["full_name"] for r in payload.get("repositories_added", [])]
    repos_removed = [r["full_name"] for r in payload.get("repositories_removed", [])]
    if repos_added:
        logger.info(f"Installation {installation_id}: repos added: {repos_added}")
    if repos_removed:
        logger.info(f"Installation {installation_id}: repos removed: {repos_removed}")
