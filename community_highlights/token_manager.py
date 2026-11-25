"""Refresh provider credentials before opening chat transports."""
from __future__ import annotations

import os
import time

import httpx

from .credentials import CredentialStoreError, WindowsCredentialStore
from .google_oauth import GOOGLE_SCOPE, GOOGLE_TOKEN_URL, google_client_secret
from .twitch_oauth import TWITCH_SCOPES, TWITCH_TOKEN_URL, TWITCH_VALIDATE_URL
from .credential_lifecycle import provider_credential_lock, provider_is_disconnecting
from .diagnostics import log_event

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
    except CredentialStoreError as error:
        log_event("oauth.token_store.read_failed", level=40, provider=provider, error_type=type(error).__name__)
        raise ProviderTokenError("Could not read provider credentials from Windows Credential Manager.") from None
    if not bundle or not bundle.get("refresh_token"):
        log_event("oauth.token_unavailable", level=30, provider=provider, outcome="not_connected")
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
        log_event("oauth.token_unavailable", level=40, provider=provider, outcome="client_id_mismatch")
        raise ProviderTokenError(f"{provider.title()} app authorization is not configured correctly.")

    if access_token_current and provider == "youtube":
        log_event("oauth.token.reused", provider=provider, outcome="access_token_current")
        return bundle["access_token"]
    if access_token_current and provider == "twitch":
        last_validated = bundle.get("validated_at", 0)
        if isinstance(last_validated, int) and last_validated > now - 3600:
            log_event("oauth.token.reused", provider=provider, outcome="validated_access_token_current")
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
                if identity.get("client_id") == client_id and set(TWITCH_SCOPES).issubset(scopes):
                    store.save(provider, {
                        **bundle,
                        "scopes": sorted(scopes),
                        "user_id": identity.get("user_id"),
                        "login": identity.get("login"),
                        "validated_at": now,
                    })
                    return bundle["access_token"]
        except (httpx.HTTPError, ValueError, CredentialStoreError) as error:
            log_event("oauth.token.validation_failed", level=40, provider=provider, error_type=type(error).__name__)
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
            expires_in = refreshed.get("expires_in", 14400)
            if not isinstance(access_token, str) or not access_token:
                raise ProviderTokenError("Twitch did not return a refreshed access token.")
            if not isinstance(refresh_token, str) or not refresh_token:
                raise ProviderTokenError("Twitch did not return a replacement refresh token.")
            if type(expires_in) is not int or expires_in <= 0:
                raise ProviderTokenError("Twitch returned an invalid token lifetime.")
            updated = {
                **bundle,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": now + expires_in,
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
            if identity.get("client_id") != client_id or not set(TWITCH_SCOPES).issubset(scopes):
                raise ProviderTokenError("The refreshed Twitch token is missing chat access.")
            updated.update({
                "scopes": sorted(scopes),
                "user_id": identity.get("user_id"),
                "login": identity.get("login"),
                "validated_at": now,
            })
        else:
            google_refresh_data = {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": bundle["refresh_token"],
            }
            public_client_secret = google_client_secret()
            if public_client_secret:
                google_refresh_data["client_secret"] = public_client_secret
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data=google_refresh_data,
            )
            response.raise_for_status()
            refreshed = response.json()
            if not isinstance(refreshed, dict):
                raise ProviderTokenError("Google returned an invalid token response.")
            access_token = refreshed.get("access_token")
            token_type = refreshed.get("token_type")
            expires_in = refreshed.get("expires_in")
            if not isinstance(access_token, str) or not access_token:
                raise ProviderTokenError("Google did not return a refreshed access token.")
            if not isinstance(token_type, str) or token_type.lower() != "bearer":
                raise ProviderTokenError("Google returned an invalid access-token type.")
            if type(expires_in) is not int or expires_in <= 0:
                raise ProviderTokenError("Google returned an invalid access-token lifetime.")

            granted_scope = refreshed.get("scope")
            if granted_scope is None:
                stored_scopes = bundle.get("scopes")
                if not isinstance(stored_scopes, list) or not all(
                    isinstance(scope, str) for scope in stored_scopes
                ):
                    raise ProviderTokenError("The saved Google grant has invalid scope metadata.")
                scopes = set(stored_scopes)
            elif isinstance(granted_scope, str):
                scopes = set(granted_scope.split())
            else:
                raise ProviderTokenError("Google returned invalid granted YouTube permissions.")
            if GOOGLE_SCOPE not in scopes:
                raise ProviderTokenError("The refreshed Google token is missing YouTube read access.")

            if "refresh_token" in refreshed:
                refresh_token = refreshed["refresh_token"]
                if not isinstance(refresh_token, str) or not refresh_token:
                    raise ProviderTokenError("Google returned an invalid replacement refresh token.")
            else:
                refresh_token = bundle["refresh_token"]

            updated = {
                **bundle,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": now + expires_in,
                "scopes": sorted(scopes),
            }

        # Twitch refresh tokens are single-use. Persist the replacement before
        # returning the access token or allowing the chat transport to proceed.
        store.save(provider, updated)
        log_event("oauth.token.refreshed", provider=provider, outcome="success")
        return access_token
    except (httpx.HTTPError, ValueError, CredentialStoreError, ProviderTokenError) as error:
        log_event("oauth.token.refresh_failed", level=40, provider=provider, error_type=type(error).__name__)
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
            log_event("oauth.token.refresh_blocked", level=30, provider=provider, outcome="disconnect_in_progress")
            raise ProviderTokenError(f"{provider.title()} is being disconnected. Try again shortly.")
        return await _ensure_access_token_locked(
            provider,
            store_factory=store_factory,
            client=client,
            force_refresh=force_refresh,
        )
