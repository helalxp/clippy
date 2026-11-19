"""Runtime-mode boundaries shared by the local desktop backend.

Desktop mode is deliberately local-only. This module is kept dependency-free so
its environment policy can be tested without importing the full FastAPI app.
"""
from __future__ import annotations

import os
from collections.abc import MutableMapping
from typing import Optional


# These values configure the retired hosted service or grant access to its
# infrastructure. They are not part of the local desktop runtime.
HOSTED_ENV_DENYLIST = frozenset({
    "DATABASE_URL",
    "POSTGRES_URL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "PGHOST",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "REDIS_URL",
    "JWT_SECRET",
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_API_KEY",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "EMAIL_FROM",
    "ADMIN_EMAIL",
    "REVIEW_LOGIN_EMAIL",
    "REVIEW_LOGIN_PASSWORD",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "OPENAI_APPS_CHALLENGE",
    "FRONTEND_URL",
    "PUBLIC_API_URL",
    "ALLOWED_ORIGINS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "AGENTLEDGER_API_URL",
    "AGENTLEDGER_API_KEY",
    "AGENTLEDGER_TREASURY_ID",
    "MANAGED_GEMINI_API_KEY",
    "MANAGED_UPLOAD_POST_API_KEY",
    "OPENSHORTS_LOGO_URL",
    "R2_ENDPOINT",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_PUBLIC_BASE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_SECURITY_TOKEN",
    "AWS_PROFILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_CONFIG_FILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_S3_BUCKET",
    "AWS_S3_PUBLIC_BUCKET",
    "AWS_ENDPOINT_URL",
    "AWS_ENDPOINT_URL_S3",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "OPENPANEL_CLIENT_SECRET",
})


def _environment(environ: Optional[MutableMapping[str, str]] = None):
    return os.environ if environ is None else environ


def is_desktop_mode(environ: Optional[MutableMapping[str, str]] = None) -> bool:
    env = _environment(environ)
    return env.get("CLIPPY_DESKTOP_MODE", "").strip().lower() in {
        "1", "true", "yes"
    }


def configure_desktop_environment(
    environ: Optional[MutableMapping[str, str]] = None,
) -> None:
    """Force desktop processes into local mode and drop inherited hosted config.

    Call after dotenv loading: a developer's or stale installation's .env file
    must not be able to turn a desktop launch back into hosted billing mode.
    """
    env = _environment(environ)
    if not is_desktop_mode(env):
        return

    env["BILLING_ENABLED"] = "0"
    for name in HOSTED_ENV_DENYLIST:
        env.pop(name, None)


def billing_enabled(
    environ: Optional[MutableMapping[str, str]] = None,
) -> bool:
    """Return hosted billing mode, except desktop mode always fails closed."""
    env = _environment(environ)
    if is_desktop_mode(env):
        return False
    return env.get("BILLING_ENABLED", "").strip().lower() in {
        "1", "true", "yes"
    }
