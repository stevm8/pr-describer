"""
config.py — All environment variables loaded once, used everywhere.
Copy .env.example to .env and fill in your values.
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── GitHub App ──────────────────────────────────────────────
    # From https://github.com/settings/apps/your-app
    github_app_id: str
    github_app_private_key: str          # Full PEM contents (use \n for newlines in env)
    github_client_id: str
    github_client_secret: str
    github_webhook_secret: str           # Random string you set when creating the App

    # ── Groq ─────────────────────────────────────────────────────
    # Free at https://console.groq.com
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"  # Best free model

    # ── Stripe ───────────────────────────────────────────────────
    # From https://dashboard.stripe.com/apikeys
    stripe_secret_key: str
    stripe_webhook_secret: str           # From Stripe dashboard → Webhooks
    stripe_price_id: str                 # Your $9/month price ID

    # ── Supabase ─────────────────────────────────────────────────
    # From https://supabase.com → your project → Settings → API
    supabase_url: str
    supabase_key: str                    # Use the service_role key (server-side only)

    # ── App ──────────────────────────────────────────────────────
    app_url: str = "http://localhost:8000"
    secret_key: str = "change-me-in-production"  # For signing session tokens

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
