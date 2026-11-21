"""Refresh provider credentials before opening chat transports."""
from __future__ import annotations

import asyncio
import os
import time

import httpx

from .credentials import CredentialStoreError, WindowsCredentialStore
from .google_oauth import google_token_info_matches_client
from .credential_lifecycle import provider_credential_lock, provider_is_disconnecting

TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


class ProviderTokenError(RuntimeError):
    """Raised when a saved provider grant cannot be refreshed safely."""


async def _ensure_access_token_locked(
    provider: str,
    *,
    store_factory=WindowsCredentialStore,
    client: httpx.AsyncClient | None = None,
    force_refresh: bool = False,
) -> str:
    if provider not in {"twitch", "youtube"}:
        raise ProviderTokenError("Unsupported chat provider.")
    try:
        store = store_factory()
        bundle = store.load(provider)
    except CredentialStoreError:
        raise ProviderTokenError("Could not read provider credentials from Windows Credential Manager.") from None
    if not bundle or not bundle.get("refresh_token"):
        raise ProviderTokenError(f"{provider.title()} is not connected. Sign in first.")

    now = int(time.time())
    access_token_current = (
        not force_refresh
        and isinstance(bundle.get("expires_at"), int)
        and bundle["expires_at"] > now + 300
    )
    client_id = (
        os.environ.get("CLIPPY_TWITCH_CLIENT_ID", "").strip()
        if provider == "twitch"
        else os.environ.get("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "").strip()
    )
    if not client_id or bundle.get("client_id") != client_id:
        raise ProviderTokenError(f"{provider.title()} app authorization is not configured correctly.")

    if access_token_current and provider == "youtube":
        return bundle["access_token"]
    if access_token_current and provider == "twitch":
        last_validated = bundle.get("validated_at", 0)
        if isinstance(last_validated, int) and last_validated > now - 3600:
            return bundle["access_token"]
        validation_client_owned = client is None
        validation_client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        try:
            validation = await validation_client.get(
                TWITCH_VALIDATE_URL,
                headers={"Authorization": f"OAuth {bundle['access_token']}"},
            )
            if validation.status_code != 401:
                validation.raise_for_status()
                identity = validation.json()
                if not isinstance(identity, dict) or not isinstance(identity.get("scopes"), list):
                    raise ProviderTokenError("Twitch returned invalid token validation details.")
                scopes = set(identity.get("scopes") or [])
                if identity.get("client_id") == client_id and "chat:read" in scopes:
                    store.save(provider, {
                        **bundle,
                        "scopes": sorted(scopes),
                        "user_id": identity.get("user_id"),
                        "login": identity.get("login"),
                        "validated_at": now,
                    })
                    return bundle["access_token"]
        except (httpx.HTTPError, ValueError, CredentialStoreError):
            raise ProviderTokenError(
                "Could not validate Twitch access. Check your connection and try again."
            ) from None
        finally:
            if validation_client_owned:
                await validation_client.aclose()
        # An invalid/revoked access token falls through to refresh. The refresh
        # token is still independent and may be used to obtain a replacement.

    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0))
    try:
        if provider == "twitch":
            response = await client.post(
                TWITCH_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": bundle["refresh_token"],
                },
            )
            response.raise_for_status()
            refreshed = response.json()
            if not isinstance(refreshed, dict):
                raise ProviderTokenError("Twitch returned an invalid token response.")
            access_token = refreshed.get("access_token")
            refresh_token = refreshed.get("refresh_token")
            if not access_token or not refresh_token:
                raise ProviderTokenError("Twitch did not return a replacement refresh token.")
            updated = {
                **bundle,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": now + int(refreshed.get("expires_in", 14400)),
                "scopes": sorted(refreshed.get("scope") or bundle.get("scopes") or []),
                "validated_at": 0,
            }
            # Twitch invalidates the previous refresh token as soon as it
            # issues a replacement. Save the replacement immediately, before
            # the separate validation request can fail due to a network issue.
            store.save(provider, updated)
            validation = await client.get(
                TWITCH_VALIDATE_URL,
                headers={"Authorization": f"OAuth {access_token}"},
            )
            validation.raise_for_status()
            identity = validation.json()
            scopes = set(identity.get("scopes") or [])
            if identity.get("client_id") != client_id or "chat:read" not in scopes:
                raise ProviderTokenError("The refreshed Twitch token is missing chat access.")
            updated.update({
                "scopes": sorted(scopes),
                "user_id": identity.get("user_id"),
                "login": identity.get("login"),
                "validated_at": now,
            })
        else:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": bundle["refresh_token"],
                },
            )
            response.raise_for_status()
            refreshed = response.json()
            if not isinstance(refreshed, dict):
                raise ProviderTokenError("Google returned an invalid token response.")
            access_token = refreshed.get("access_token")
            if not access_token:
                raise ProviderTokenError("Google did not return a refreshed access token.")
            info = await client.get(
                GOOGLE_TOKEN_INFO_URL,
                params={"access_token": access_token},
            )
            info.raise_for_status()
            token_info = info.json()
            if not isinstance(token_info, dict):
                raise ProviderTokenError("Google returned invalid token details.")
            scopes = set((token_info.get("scope") or "").split())
            if not google_token_info_matches_client(token_info, client_id):
                raise ProviderTokenError("Google returned a token for an unexpected OAuth client.")
            if YOUTUBE_SCOPE not in scopes:
                raise ProviderTokenError("The refreshed Google token is missing YouTube read access.")
            updated = {
                **bundle,
                "access_token": access_token,
                "refresh_token": refreshed.get("refresh_token") or bundle["refresh_token"],
                "expires_at": now + int(refreshed.get("expires_in", 3600)),
                "scopes": sorted(scopes),
            }

        # Twitch refresh tokens are single-use. Persist the replacement before
        # returning the access token or allowing the chat transport to proceed.
        store.save(provider, updated)
        return access_token
    except (httpx.HTTPError, ValueError, CredentialStoreError, ProviderTokenError):
        raise ProviderTokenError(
            f"Could not refresh {provider.title()} access. Reconnect the account and try again."
        ) from None
    finally:
        if owned_client:
            await client.aclose()



async def ensure_access_token(
    provider: str,
    *,
    store_factory=WindowsCredentialStore,
    client: httpx.AsyncClient | None = None,
    force_refresh: bool = False,
) -> str:
    if provider not in {"twitch", "youtube"}:
        raise ProviderTokenError("Unsupported chat provider.")
    # Use the same per-provider lock as Disconnect. This ensures a token refresh
    # cannot persist a newly rotated credential after local disconnect removes it.
    async with provider_credential_lock(provider):
        if provider_is_disconnecting(provider):
            raise ProviderTokenError(f"{provider.title()} is being disconnected. Try again shortly.")
        return await _ensure_access_token_locked(
            provider,
            store_factory=store_factory,
            client=client,
            force_refresh=force_refresh,
        )
