"""
routes/billing.py — Stripe checkout, customer portal, and webhook handling.

The Stripe webhook is the source of truth for subscription state.
Never trust the checkout success URL alone — always wait for the webhook.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import RedirectResponse, HTMLResponse
from config import get_settings
import db
from services.stripe_svc import (
    create_checkout_session,
    create_portal_session,
    construct_webhook_event,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Checkout ──────────────────────────────────────────────────────────────────

@router.get("/checkout")
async def checkout(installation_id: int):
    """
    Create a Stripe Checkout session and redirect the user there.
    Called after GitHub OAuth completes.
    """
    # Look up the installation to get the account login
    installation = await db.get_installation(installation_id)
    if not installation:
        raise HTTPException(status_code=404, detail="Installation not found")

    # Get the user's email if available
    email = None
    if installation.get("user_id"):
        db_client = await db.get_db()
        res = await (
            db_client.table("users")
            .select("email")
            .eq("id", installation["user_id"])
            .single()
            .execute()
        )
        email = res.data.get("email") if res.data else None

    checkout_url = await create_checkout_session(
        installation_id=installation_id,
        github_login=installation["account_login"],
        email=email,
    )
    return RedirectResponse(checkout_url)


@router.get("/portal")
async def portal(installation_id: int):
    """
    Redirect to Stripe Customer Portal for managing/canceling subscription.
    """
    sub = await db.get_subscription(installation_id)
    if not sub or not sub.get("stripe_customer_id"):
        raise HTTPException(status_code=404, detail="No active subscription found")

    portal_url = await create_portal_session(sub["stripe_customer_id"])
    return RedirectResponse(portal_url)


# ── Post-checkout pages ───────────────────────────────────────────────────────

@router.get("/success", response_class=HTMLResponse)
async def success():
    """Shown after successful subscription. Simple page — customize as needed."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>You're all set — PR Describer</title>
        <style>
            body { font-family: system-ui, sans-serif; max-width: 520px; margin: 120px auto; text-align: center; padding: 0 24px; }
            h1 { font-size: 2rem; margin-bottom: 8px; }
            p { color: #666; line-height: 1.6; }
            a { display: inline-block; margin-top: 24px; background: #1a1a1a; color: #fff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 500; }
        </style>
    </head>
    <body>
        <h1>🎉 You're all set!</h1>
        <p>PR Describer is now active. Open your next pull request and watch the magic happen.</p>
        <a href="https://github.com">Back to GitHub →</a>
    </body>
    </html>
    """


@router.get("/cancel", response_class=HTMLResponse)
async def cancel():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>Cancelled — PR Describer</title>
    <style>body{font-family:system-ui,sans-serif;max-width:520px;margin:120px auto;text-align:center;padding:0 24px;}p{color:#666;}a{display:inline-block;margin-top:24px;background:#1a1a1a;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;}</style>
    </head>
    <body><h1>No worries</h1><p>You cancelled the checkout. You can come back any time.</p><a href="/">Back to home</a></body>
    </html>
    """


# ── Stripe webhook ────────────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(...),
):
    """
    Stripe sends events here for payment lifecycle events.
    We update subscription status in our DB based on these.

    Key events:
      • checkout.session.completed     → subscription created, start trial
      • customer.subscription.updated  → renewal, plan change
      • customer.subscription.deleted  → cancellation
      • invoice.payment_failed         → payment failed (optional: notify user)
    """
    payload = await request.body()

    try:
        event = construct_webhook_event(payload, stripe_signature)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook error: {e}")

    event_type = event["type"]
    logger.info(f"Stripe event: {event_type}")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        installation_id = int(session["metadata"].get("installation_id", 0))
        stripe_customer_id = session.get("customer")
        subscription_id = session.get("subscription")

        if installation_id and stripe_customer_id and subscription_id:
            # Get subscription details for period end
            import stripe
            stripe.api_key = get_settings().stripe_secret_key
            sub = stripe.Subscription.retrieve(subscription_id)
            period_end = datetime.fromtimestamp(
                sub["current_period_end"], tz=timezone.utc
            ).isoformat()

            # Get our internal installation row
            inst = await db.get_installation(installation_id)
            if inst:
                db_client = await db.get_db()
                await (
                    db_client.table("subscriptions")
                    .upsert({
                        "installation_id": inst["id"],
                        "stripe_customer_id": stripe_customer_id,
                        "stripe_subscription_id": subscription_id,
                        "status": "active",
                        "current_period_end": period_end,
                    }, on_conflict="installation_id")
                    .execute()
                )
                logger.info(f"Activated subscription for installation {installation_id}")

    elif event_type in ("customer.subscription.updated",):
        sub = event["data"]["object"]
        status = sub["status"]
        period_end = datetime.fromtimestamp(
            sub["current_period_end"], tz=timezone.utc
        ).isoformat()
        await db.set_subscription_active(
            stripe_subscription_id=sub["id"],
            stripe_customer_id=sub["customer"],
            period_end=period_end,
        )

    elif event_type in ("customer.subscription.deleted",):
        sub = event["data"]["object"]
        await db.set_subscription_canceled(sub["id"])
        logger.info(f"Subscription canceled: {sub['id']}")

    elif event_type == "invoice.payment_failed":
        # Optional: send an email to the user to update payment method
        invoice = event["data"]["object"]
        logger.warning(f"Payment failed for customer: {invoice.get('customer')}")

    return {"received": True}
