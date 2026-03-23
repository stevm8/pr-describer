"""
services/github.py — GitHub API helpers.

GitHub Apps authenticate via short-lived installation tokens (expire in 1hr).
We generate a JWT from the App's private key, exchange it for an installation
token, then use that token for all API calls on that repo.
"""

import time
import httpx
import jwt  # PyJWT
from config import get_settings


def _make_app_jwt() -> str:
    """
    Create a short-lived JWT signed with the App's private key.
    GitHub requires this to request installation tokens.
    """
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iat": now - 60,        # issued at (60s in the past to account for clock skew)
        "exp": now + 540,       # expires in 9 minutes (max 10)
        "iss": settings.github_app_id,
    }
    private_key = settings.github_app_private_key.replace("\\n", "\n")
    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    """
    Exchange the App JWT for an installation access token.
    These expire after 1 hour — we regenerate on every webhook (stateless).
    """
    app_jwt = _make_app_jwt()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
    return resp.json()["token"]


async def get_pr_diff(owner: str, repo: str, pr_number: int, token: str) -> str:
    """
    Fetch the raw unified diff for a pull request.
    Returns the diff as a plain string.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.diff",   # Magic header for diff format
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
    return resp.text


async def update_pr_description(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    token: str,
) -> None:
    """
    Update the body (description) of a pull request.
    This is a PATCH to the PR — it replaces whatever was there before.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"body": body},
        )
        resp.raise_for_status()


async def post_pr_comment(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    token: str,
) -> None:
    """
    Post a comment on a PR (used as fallback if description update fails,
    or for leaving a "subscription required" message).
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"body": body},
        )
        resp.raise_for_status()


async def get_github_user(access_token: str) -> dict:
    """Fetch the authenticated user's GitHub profile."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
    return resp.json()


async def exchange_code_for_token(code: str) -> str:
    """OAuth: exchange a GitHub callback code for a user access token."""
    settings = get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
        )
        resp.raise_for_status()
    return resp.json()["access_token"]
