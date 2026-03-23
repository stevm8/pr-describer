"""
routes/auth.py — GitHub OAuth flow.

After a user installs the GitHub App, GitHub redirects them to our
/auth/callback with a code. We exchange it for a token, save the user,
then redirect to Stripe billing.
"""

import logging
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from config import get_settings
from services.github import exchange_code_for_token, get_github_user
import db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/login")
async def login(installation_id: int | None = None):
    """
    Start the GitHub OAuth flow.
    We pass installation_id through state so we can link it after auth.
    """
    settings = get_settings()
    state = str(installation_id) if installation_id else "none"
    github_oauth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        f"&scope=read:user,user:email"
        f"&state={state}"
    )
    return RedirectResponse(github_oauth_url)


@router.get("/callback")
async def callback(request: Request, code: str, state: str = "none"):
    """
    GitHub redirects here after the user approves OAuth.
    We:
      1. Exchange code for access token
      2. Fetch user profile
      3. Save/update user in DB
      4. Link to installation if state contains one
      5. Redirect to Stripe billing
    """
    settings = get_settings()

    # Step 1 & 2: Exchange code, get user
    try:
        access_token = await exchange_code_for_token(code)
        gh_user = await get_github_user(access_token)
    except Exception as e:
        logger.error(f"OAuth failed: {e}")
        return RedirectResponse(f"{settings.app_url}/?error=oauth_failed")

    # Step 3: Save user
    user = await db.upsert_user(
        github_id=gh_user["id"],
        login=gh_user["login"],
        email=gh_user.get("email"),
        access_token=access_token,
    )

    # Step 4: Link installation to user
    installation_id = None
    if state != "none":
        try:
            installation_id = int(state)
            installation = await db.get_installation(installation_id)
            if installation:
                await db.upsert_installation(
                    installation_id=installation_id,
                    account_login=installation["account_login"],
                    account_type=installation["account_type"],
                    user_id=user["id"],
                )
        except (ValueError, Exception) as e:
            logger.warning(f"Could not link installation: {e}")

    # Step 5: Redirect to billing
    if installation_id:
        return RedirectResponse(
            f"{settings.app_url}/billing/checkout?installation_id={installation_id}"
        )

    # Fallback: no installation ID — send to dashboard
    return RedirectResponse(f"{settings.app_url}/billing/success")


@router.get("/install")
async def install():
    """
    Direct link to install the GitHub App.
    Update APP_SLUG to your app's slug from the GitHub App settings page.
    """
    settings = get_settings()
    app_slug = "pr-describer"  # ← Change this to your GitHub App slug
    install_url = f"https://github.com/apps/{app_slug}/installations/new"
    return RedirectResponse(install_url)
