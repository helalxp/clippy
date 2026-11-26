"""Best-effort provider-side revocation for Community Highlights.

A failed provider request never prevents local credential removal. Callers
must report the difference between provider-confirmed revocation and local-only
disconnect; token material is never returned or logged.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from .diagnostics import log_event

GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
TWITCH_REVOKE_URL = "https://id.twitch.tv/oauth2/revoke"
REVOCATION_TIMEOUT_SECONDS = 15.0


async def _post_revocation(
    url: str,
    *,
    data: dict[str, str],
    client: httpx.AsyncClient | None = None,
) -> bool:
    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(REVOCATION_TIMEOUT_SECONDS))
    try:
        response = await client.post(url, data=data)
        confirmed = response.status_code == 200
        log_event("oauth.revocation.response", provider="google" if "google" in url else "twitch", outcome="confirmed" if confirmed else "not_confirmed", http_status=response.status_code)
        return confirmed
    except httpx.HTTPError as error:
        # Do not log the exception or request: an HTTP client exception can
        # contain URLs, provider metadata, or credentials.
        log_event("oauth.revocation.failed", level=30, provider="google" if "google" in url else "twitch", error_type=type(error).__name__)
        return False
    finally:
        if owned_client:
            await client.aclose()


async def revoke_google_credentials(
    bundle: dict[str, Any] | None,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Revoke the user's Google refresh token (or access token as fallback)."""
    client_id = os.environ.get("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "").strip()
    if not isinstance(bundle, dict) or not client_id or bundle.get("client_id") != client_id:
        return False
    token = bundle.get("refresh_token") or bundle.get("access_token")
    if not isinstance(token, str) or not token:
        return False
    # Use a form body, not a query string: tokens should not appear in URLs,
    # reverse-proxy access logs, or exception messages.
    return await _post_revocation(
        GOOGLE_REVOKE_URL,
        data={"token": token},
        client=client,
    )


async def revoke_twitch_credentials(
    bundle: dict[str, Any] | None,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Revoke the saved Twitch access token using Twitch's public-client API."""
    client_id = os.environ.get("CLIPPY_TWITCH_CLIENT_ID", "").strip()
    if not isinstance(bundle, dict) or not client_id or bundle.get("client_id") != client_id:
        return False
    token = bundle.get("access_token")
    if not isinstance(token, str) or not token:
        return False
    return await _post_revocation(
        TWITCH_REVOKE_URL,
        data={"client_id": client_id, "token": token},
        client=client,
    )
