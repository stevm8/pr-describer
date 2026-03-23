"""
db.py — Supabase client + schema initialisation.

Tables created on first boot if they don't exist:
  • users       — GitHub users who installed the app
  • installations — GitHub App installations (one per org/user)
  • subscriptions — Stripe subscription state per installation
"""

from supabase import create_async_client, AsyncClient
from config import get_settings

_client: AsyncClient | None = None


async def get_db() -> AsyncClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = await create_async_client(s.supabase_url, s.supabase_key)
    return _client


async def init_db():
    """
    Create tables via Supabase SQL if they don't already exist.
    Run once at startup. Supabase uses PostgreSQL under the hood.
    """
    db = await get_db()

    # We use Supabase's rpc() to run raw SQL.
    # Alternatively, run these in the Supabase dashboard SQL editor.
    schema_sql = """
    CREATE TABLE IF NOT EXISTS users (
        id              BIGSERIAL PRIMARY KEY,
        github_id       BIGINT UNIQUE NOT NULL,
        github_login    TEXT NOT NULL,
        email           TEXT,
        access_token    TEXT,          -- GitHub OAuth token
        created_at      TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS installations (
        id                  BIGSERIAL PRIMARY KEY,
        installation_id     BIGINT UNIQUE NOT NULL,   -- GitHub App installation ID
        account_login       TEXT NOT NULL,            -- org or user name
        account_type        TEXT NOT NULL,            -- 'User' or 'Organization'
        user_id             BIGINT REFERENCES users(id),
        created_at          TIMESTAMPTZ DEFAULT NOW(),
        suspended_at        TIMESTAMPTZ              -- set when app is uninstalled
    );

    CREATE TABLE IF NOT EXISTS subscriptions (
        id                      BIGSERIAL PRIMARY KEY,
        installation_id         BIGINT REFERENCES installations(id) UNIQUE,
        stripe_customer_id      TEXT,
        stripe_subscription_id  TEXT,
        status                  TEXT DEFAULT 'inactive',  -- inactive | active | canceled
        trial_end               TIMESTAMPTZ,
        current_period_end      TIMESTAMPTZ,
        created_at              TIMESTAMPTZ DEFAULT NOW(),
        updated_at              TIMESTAMPTZ DEFAULT NOW()
    );
    """
    try:
        await db.rpc("exec_sql", {"sql": schema_sql}).execute()
    except Exception:
        # Tables may already exist or rpc not set up — that's fine.
        # You can also run the SQL above manually in Supabase dashboard.
        pass


# ── Helpers ──────────────────────────────────────────────────────────────────

async def get_installation(installation_id: int) -> dict | None:
    db = await get_db()
    res = await (
        db.table("installations")
        .select("*, subscriptions(*)")
        .eq("installation_id", installation_id)
        .single()
        .execute()
    )
    return res.data


async def upsert_installation(installation_id: int, account_login: str, account_type: str, user_id: int | None = None):
    db = await get_db()
    await (
        db.table("installations")
        .upsert({
            "installation_id": installation_id,
            "account_login": account_login,
            "account_type": account_type,
            "user_id": user_id,
            "suspended_at": None,
        }, on_conflict="installation_id")
        .execute()
    )


async def suspend_installation(installation_id: int):
    db = await get_db()
    from datetime import datetime, timezone
    await (
        db.table("installations")
        .update({"suspended_at": datetime.now(timezone.utc).isoformat()})
        .eq("installation_id", installation_id)
        .execute()
    )


async def upsert_user(github_id: int, login: str, email: str | None, access_token: str) -> dict:
    db = await get_db()
    res = await (
        db.table("users")
        .upsert({
            "github_id": github_id,
            "github_login": login,
            "email": email,
            "access_token": access_token,
        }, on_conflict="github_id")
        .select()
        .single()
        .execute()
    )
    return res.data


async def get_subscription(installation_id: int) -> dict | None:
    db = await get_db()
    # First get our internal installation row ID
    inst = await get_installation(installation_id)
    if not inst:
        return None
    res = await (
        db.table("subscriptions")
        .select("*")
        .eq("installation_id", inst["id"])
        .maybe_single()
        .execute()
    )
    return res.data


async def set_subscription_active(stripe_subscription_id: str, stripe_customer_id: str, period_end: str):
    db = await get_db()
    await (
        db.table("subscriptions")
        .upsert({
            "stripe_subscription_id": stripe_subscription_id,
            "stripe_customer_id": stripe_customer_id,
            "status": "active",
            "current_period_end": period_end,
            "updated_at": "NOW()",
        }, on_conflict="stripe_subscription_id")
        .execute()
    )


async def set_subscription_canceled(stripe_subscription_id: str):
    db = await get_db()
    await (
        db.table("subscriptions")
        .update({"status": "canceled", "updated_at": "NOW()"})
        .eq("stripe_subscription_id", stripe_subscription_id)
        .execute()
    )


async def has_active_subscription(installation_id: int) -> bool:
    sub = await get_subscription(installation_id)
    if not sub:
        return False
    return sub.get("status") == "active"
