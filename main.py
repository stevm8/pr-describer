"""
PR Describer — GitHub App that auto-writes PR descriptions using AI.
Entry point: FastAPI app wiring all routes together.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from routes.webhook import router as webhook_router
from routes.auth import router as auth_router
from routes.billing import router as billing_router
from db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB migrations on startup."""
    await init_db()
    yield


app = FastAPI(
    title="PR Describer",
    description="AI-powered GitHub PR description generator",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount landing page static files
app.mount("/static", StaticFiles(directory="landing"), name="static")

# Register routers
app.include_router(webhook_router, prefix="/webhook", tags=["GitHub Webhooks"])
app.include_router(auth_router, prefix="/auth", tags=["GitHub OAuth"])
app.include_router(billing_router, prefix="/billing", tags=["Stripe Billing"])


@app.get("/", include_in_schema=False)
async def landing():
    """Serve the landing page."""
    return FileResponse("landing/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}
