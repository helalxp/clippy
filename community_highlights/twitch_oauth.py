"""Twitch Device Code Grant for the Community Highlights desktop feature.

The device code remains server-side. The UI receives only Twitch's prefilled
activation URL and an opaque flow ID; it never handles OAuth tokens.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import time
from typing import Any

import httpx

from .credentials import CredentialStoreError, WindowsCredentialStore

TWITCH_DEVICE_URL = "https://id.twitch.tv/oauth2/device"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
TWITCH_SCOPES = ("chat:read",)
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_MAX_FLOWS = 8

# Flow state is intentionally process-local and short-lived. The backend is a
# single supervised desktop process; a restart safely invalidates pending flows.
_flows: dict[str, dict[str, Any]] = {}
_flow_lock = asyncio.Lock()


class TwitchOAuthError(RuntimeError):
    """Safe, user-displayable Twitch authorization failure."""


def twitch_client_id() -> str:
    return os.environ.get("CLIPPY_TWITCH_CLIENT_ID", "").strip()


def twitch_authorization_available() -> bool:
    if not twitch_client_id():
        return False
    try:
        WindowsCredentialStore()
    except CredentialStoreError:
        return False
    return True


def _safe_activation_url(value: Any) -> str:
    from urllib.parse import urlparse

    if not isinstance(value, str):
        raise TwitchOAuthError("Twitch did not return an activation URL.")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"twitch.tv", "www.twitch.tv"}:
        raise TwitchOAuthError("Twitch returned an unexpected activation URL.")
    return value


async def start_twitch_flow(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    client_id = twitch_client_id()
    if not client_id:
        raise TwitchOAuthError("Twitch sign-in is not configured in this Clippy build.")
    WindowsCredentialStore()

    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    try:
        response = await client.post(
            TWITCH_DEVICE_URL,
            data={"client_id": client_id, "scopes": " ".join(TWITCH_SCOPES)},
        )
        if response.status_code >= 400:
            raise TwitchOAuthError("Twitch could not start authorization. Please try again.")
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise TwitchOAuthError("Could not reach Twitch. Check your connection and try again.") from None
    finally:
        if owned_client:
            await client.aclose()

    device_code = payload.get("device_code")
    expires_in = payload.get("expires_in")
    interval = payload.get("interval", 5)
    if not isinstance(device_code, str) or not device_code:
        raise TwitchOAuthError("Twitch returned an invalid authorization response.")
    if not isinstance(expires_in, int) or not 30 <= expires_in <= 3600:
        raise TwitchOAuthError("Twitch returned an invalid authorization expiry.")
    if not isinstance(interval, int) or not 1 <= interval <= 30:
        interval = 5
    activation_url = _safe_activation_url(payload.get("verification_uri"))

    now = time.monotonic()
    flow_id = secrets.token_urlsafe(32)
    async with _flow_lock:
        for key, flow in list(_flows.items()):
            if flow["expires_at"] <= now or flow["status"] != "pending":
                _flows.pop(key, None)
        if len(_flows) >= _MAX_FLOWS:
            raise TwitchOAuthError("Too many sign-in attempts are active. Cancel one and try again.")
        _flows[flow_id] = {
            "device_code": device_code,
            "client_id": client_id,
            "activation_url": activation_url,
            "expires_at": now + expires_in,
            "interval": interval,
            "next_poll": now + interval,
            "status": "pending",
            "message": "Waiting for Twitch authorization.",
        }
    return {
        "flow_id": flow_id,
        "verification_url": activation_url,
        "expires_in": expires_in,
        "poll_interval": interval,
    }


async def poll_twitch_flow(
    flow_id: str,
    *,
    client: httpx.AsyncClient | None = None,
    store_factory=WindowsCredentialStore,
) -> dict[str, str]:
    async with _flow_lock:
        flow = _flows.get(flow_id)
        if flow is None:
            raise TwitchOAuthError("This sign-in attempt has expired. Start again.")
        now = time.monotonic()
        if flow["status"] != "pending":
            return {"status": flow["status"], "message": flow["message"]}
        if now >= flow["expires_at"]:
            flow.update(status="expired", message="Twitch sign-in expired. Please try again.")
            return {"status": flow["status"], "message": flow["message"]}
        if now < flow["next_poll"]:
            return {"status": "pending", "message": flow["message"]}
        flow["next_poll"] = now + flow["interval"]
        device_code = flow["device_code"]
        client_id = flow["client_id"]
        interval = flow["interval"]

    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    try:
        response = await client.post(
            TWITCH_TOKEN_URL,
            data={
                "client_id": client_id,
                "scopes": " ".join(TWITCH_SCOPES),
                "device_code": device_code,
                "grant_type": DEVICE_GRANT,
            },
        )
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        if owned_client:
            await client.aclose()
        return {"status": "pending", "message": "Can't reach Twitch right now. Retrying shortly."}

    if owned_client:
        await client.aclose()

    error = payload.get("message") or payload.get("error")
    if error == "authorization_pending":
        return {"status": "pending", "message": "Waiting for you to approve access in Twitch."}
    if error == "slow_down":
        async with _flow_lock:
            current = _flows.get(flow_id)
            if current and current["status"] == "pending":
                current["interval"] = min(current["interval"] + 5, 60)
                current["next_poll"] = time.monotonic() + current["interval"]
        return {"status": "pending", "message": "Twitch asked Clippy to slow down. Still waiting."}
    if error in {"access_denied", "authorization_declined"}:
        return _finish(flow_id, "denied", "Twitch authorization was declined.")
    if error in {"expired_token", "invalid device code"}:
        return _finish(flow_id, "expired", "Twitch sign-in expired. Please try again.")
    if response.status_code >= 400 or not payload.get("access_token"):
        return _finish(flow_id, "error", "Twitch sign-in failed. Please start again.")

    access_token = payload["access_token"]
    refresh_token = payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        return _finish(flow_id, "error", "Twitch did not return a refresh token. Please start again.")

    try:
        if owned_client:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as validation_client:
                validation = await validation_client.get(
                    TWITCH_VALIDATE_URL,
                    headers={"Authorization": f"OAuth {access_token}"},
                )
        else:
            validation = await client.get(
                TWITCH_VALIDATE_URL,
                headers={"Authorization": f"OAuth {access_token}"},
            )
        validation.raise_for_status()
        identity = validation.json()
        scopes = set(identity.get("scopes") or [])
        if identity.get("client_id") != client_id or not set(TWITCH_SCOPES).issubset(scopes):
            raise TwitchOAuthError("Twitch authorization did not grant the required chat permission.")
        store_factory().save("twitch", {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": int(time.time()) + int(payload.get("expires_in", 14400)),
            "validated_at": int(time.time()),
            "scopes": sorted(scopes),
            "client_id": client_id,
            "user_id": identity.get("user_id"),
            "login": identity.get("login"),
        })
    except (httpx.HTTPError, ValueError, CredentialStoreError, TwitchOAuthError):
        return _finish(flow_id, "error", "Clippy could not verify or securely save Twitch access. Please try again.")
    return _finish(flow_id, "connected", "Twitch is connected.")


def _finish(flow_id: str, status: str, message: str) -> dict[str, str]:
    with_status = {"status": status, "message": message}
    # Device codes are one-time and must not remain in memory after completion.
    flow = _flows.get(flow_id)
    if flow is not None:
        flow.pop("device_code", None)
        flow.update(status=status, message=message)
    return with_status


async def cancel_twitch_flow(flow_id: str) -> bool:
    async with _flow_lock:
        flow = _flows.pop(flow_id, None)
        return flow is not None
