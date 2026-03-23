"""
services/stripe_svc.py — Stripe helpers for subscription management.

Flow:
  1. User installs GitHub App → /auth/callback saves them to DB
  2. We redirect to /billing/checkout?installation_id=X
  3. Stripe Checkout handles payment
  4. Stripe sends webhook to /billing/webhook → we mark subscription active
  5. User can manage billing at /billing/portal
"""

import stripe
from config import get_settings


def _stripe():
    stripe.api_key = get_settings().stripe_secret_key
    return stripe


async def create_checkout_session(
    installation_id: int,
    github_login: str,
    email: str | None,
) -> str:
    """
    Create a Stripe Checkout session and return the redirect URL.
    We embed installation_id in metadata so we know which install to activate.
    """
    s = get_settings()
    st = _stripe()

    session = st.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": s.stripe_price_id, "quantity": 1}],
        customer_email=email,
        metadata={
            "installation_id": str(installation_id),
            "github_login": github_login,
        },
        success_url=f"{s.app_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{s.app_url}/billing/cancel",
        # 14-day free trial — remove this line if you don't want a trial
        subscription_data={"trial_period_days": 14},
    )
    return session.url


async def create_portal_session(stripe_customer_id: str) -> str:
    """
    Create a Stripe Customer Portal session so users can manage/cancel their sub.
    Returns the redirect URL.
    """
    s = get_settings()
    st = _stripe()

    session = st.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=f"{s.app_url}/billing/success",
    )
    return session.url


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify and parse an incoming Stripe webhook."""
    s = get_settings()
    st = _stripe()
    return st.Webhook.construct_event(payload, sig_header, s.stripe_webhook_secret)
