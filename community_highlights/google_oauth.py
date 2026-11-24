"""Google desktop OAuth (PKCE + loopback) for YouTube read-only access."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .credentials import CredentialStoreError, WindowsCredentialStore
from .credential_lifecycle import provider_credential_lock, provider_is_disconnecting, provider_operation_generation

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
_LOG = logging.getLogger(__name__)
_GOOGLE_FLOWS: dict[str, dict[str, Any]] = {}
_GOOGLE_LOCK = asyncio.Lock()
_GOOGLE_FLOW_TTL = 600
_GOOGLE_EXPIRY_TASKS: set[asyncio.Task] = set()


class GoogleOAuthError(RuntimeError):
    """Safe, user-displayable Google authorization failure."""


def google_client_id() -> str:
    return os.environ.get("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "").strip()


def google_token_info_matches_client(token_info: Any, client_id: str) -> bool:
    """Check the OAuth client that requested the access token.

    Google's tokeninfo contract distinguishes `aud` from `azp`: `azp`
    identifies the authorized party (the client that requested the token),
    while `aud` may differ for clients in the same Cloud project.
    """
    if not isinstance(token_info, dict):
        return False
    audience = token_info.get("aud")
    authorized_party = token_info.get("azp")
    return (
        isinstance(audience, str)
        and bool(audience)
        and audience.isascii()
        and isinstance(authorized_party, str)
        and authorized_party.isascii()
        and secrets.compare_digest(authorized_party, client_id)
    )


def google_authorization_available() -> bool:
    if not google_client_id():
        return False
    try:
        WindowsCredentialStore()
    except CredentialStoreError:
        return False
    return True


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _close_listener(flow: dict[str, Any]) -> None:
    flow["verifier"] = ""
    server = flow.get("server")
    if server:
        server.close()


async def start_google_flow(
    *,
    client_id: str | None = None,
    store_factory=WindowsCredentialStore,
) -> dict[str, Any]:
    client_id = (client_id or google_client_id()).strip()
    if not client_id:
        raise GoogleOAuthError("Google sign-in is not configured in this Clippy build.")
    if provider_is_disconnecting("youtube"):
        raise GoogleOAuthError("Google is being disconnected. Try again shortly.")
    start_generation = provider_operation_generation("youtube")
    store_factory()

    flow_id = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    loopback_path = "/"
    flow: dict[str, Any] = {
        "state": state,
        "verifier": verifier,
        "client_id": client_id,
        "status": "pending",
        "message": "Waiting for Google authorization.",
        "expires_at": time.monotonic() + _GOOGLE_FLOW_TTL,
        "server": None,
        "store_factory": store_factory,
    }

    async def callback_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5)
            parts = request_line.decode("ascii", "replace").strip().split(" ")
            if len(parts) != 3 or parts[0] != "GET":
                status, message = "400 Bad Request", "Invalid callback request."
            else:
                parsed = urlsplit(parts[1])
                if parsed.path != loopback_path:
                    status, message = "404 Not Found", "This Clippy callback is not available."
                else:
                    params = parse_qs(parsed.query, keep_blank_values=True)
                    await _complete_google_callback(flow_id, params)
                    current = _GOOGLE_FLOWS.get(flow_id, {})
                    status = "200 OK"
                    message = (
                        "Google authorization is complete. You can return to Clippy."
                        if current.get("status") == "connected"
                        else "Google authorization did not complete. You can return to Clippy."
                    )
            body = (
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width\">"
                "<title>Clippy authorization</title></head><body>"
                "<h2>Clippy</h2><p>" + message + "</p></body></html>"
            ).encode("utf-8")
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\nCache-Control: no-store\r\n"
                "Connection: close\r\n\r\n".encode("ascii") + body
            )
            await writer.drain()
        except (asyncio.TimeoutError, UnicodeError, ValueError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    try:
        server = await asyncio.start_server(callback_handler, "127.0.0.1", 0)
    except OSError:
        raise GoogleOAuthError("Clippy could not start its secure local sign-in callback.") from None

    port = server.sockets[0].getsockname()[1]
    redirect_uri = f"http://127.0.0.1:{port}"
    flow["server"] = server
    flow["redirect_uri"] = redirect_uri

    async with provider_credential_lock("youtube"):
        if (
            provider_is_disconnecting("youtube")
            or provider_operation_generation("youtube") != start_generation
        ):
            server.close()
            await server.wait_closed()
            raise GoogleOAuthError("Google sign-in was superseded by a disconnect.")
        async with _GOOGLE_LOCK:
            now = time.monotonic()
            for key, current in list(_GOOGLE_FLOWS.items()):
                if current["expires_at"] <= now or current["status"] != "pending":
                    old_server = current.get("server")
                    if old_server:
                        old_server.close()
                    _GOOGLE_FLOWS.pop(key, None)
            if len(_GOOGLE_FLOWS) >= 4:
                server.close()
                await server.wait_closed()
                raise GoogleOAuthError("Too many Google sign-in attempts are active.")
            _GOOGLE_FLOWS[flow_id] = flow

    expiry_task = asyncio.create_task(_expire_google_flow(flow_id))
    _GOOGLE_EXPIRY_TASKS.add(expiry_task)
    expiry_task.add_done_callback(_GOOGLE_EXPIRY_TASKS.discard)

    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    })
    return {
        "flow_id": flow_id,
        "authorization_url": f"{GOOGLE_AUTH_URL}?{query}",
        "expires_in": _GOOGLE_FLOW_TTL,
    }


async def _expire_google_flow(flow_id: str) -> None:
    await asyncio.sleep(_GOOGLE_FLOW_TTL)
    async with _GOOGLE_LOCK:
        flow = _GOOGLE_FLOWS.get(flow_id)
        if flow and flow["status"] == "pending" and time.monotonic() >= flow["expires_at"]:
            flow.update(status="expired", message="Google sign-in expired. Please try again.")
            _close_listener(flow)


async def _complete_google_callback(flow_id: str, params: dict[str, list[str]]) -> None:
    flow = _GOOGLE_FLOWS.get(flow_id)
    if not flow or flow["status"] != "pending" or time.monotonic() >= flow["expires_at"]:
        return
    returned_state = (params.get("state") or [""])[0]
    if not secrets.compare_digest(returned_state, flow["state"]):
        flow.update(status="error", message="Google sign-in state validation failed.")
        _close_listener(flow)
        return
    provider_error = (params.get("error") or [""])[0]
    if provider_error:
        flow.update(
            status="denied" if provider_error == "access_denied" else "error",
            message="Google authorization was declined." if provider_error == "access_denied"
            else "Google authorization could not be completed.",
        )
        _close_listener(flow)
        return
    code = (params.get("code") or [""])[0]
    if not code:
        flow.update(status="error", message="Google did not return an authorization code.")
        _close_listener(flow)
        return

    phase = "authorization_code_exchange"
    try:
        # Serialize the full authorization-code exchange with Disconnect. If
        # this exchange wins the lock, its new refresh token is stored before
        # disconnect revokes it. If Disconnect wins, it removes this flow and
        # the callback exits before contacting Google's token endpoint.
        async with provider_credential_lock("youtube"):
            if provider_is_disconnecting("youtube"):
                return
            async with _GOOGLE_LOCK:
                current = _GOOGLE_FLOWS.get(flow_id)
                if current is not flow or current.get("status") != "pending":
                    return

            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                response = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": flow["client_id"],
                        "code": code,
                        "code_verifier": flow["verifier"],
                        "grant_type": "authorization_code",
                        "redirect_uri": flow["redirect_uri"],
                    },
                )
                response.raise_for_status()
                phase = "token_response_validation"
                tokens = response.json()

            if not isinstance(tokens, dict):
                raise GoogleOAuthError("Google returned an invalid token response.")
            access_token = tokens.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise GoogleOAuthError("Google did not return an access token.")
            granted_scope = tokens.get("scope")
            if not isinstance(granted_scope, str):
                raise GoogleOAuthError("Google did not return the granted YouTube permissions.")
            scopes = set(granted_scope.split())

            # The authorization-code exchange is bound to this public client
            # ID and the one-time PKCE verifier. Google returns the granted
            # scopes with the token response, so an additional tokeninfo
            # request is unnecessary for initial authorization and would add
            # another network dependency to the sign-in path.
            phase = "scope_validation"
            if GOOGLE_SCOPE not in scopes:
                raise GoogleOAuthError("Google did not grant the required read-only YouTube permission.")

            phase = "token_expiry_validation"
            expires_in = int(tokens.get("expires_in", 3600))
            if expires_in <= 0:
                raise GoogleOAuthError("Google returned an invalid access-token lifetime.")

            async with _GOOGLE_LOCK:
                current = _GOOGLE_FLOWS.get(flow_id)
                if current is not flow or current.get("status") != "pending":
                    return

                # Keep cancellation atomic with the synchronous Credential
                # Manager read/write. Once this lock is acquired, cancellation
                # cannot remove the flow between the final check and save.
                phase = "credential_store_read"
                store = flow["store_factory"]()
                previous = store.load("youtube") or {}

                phase = "refresh_token_validation"
                refresh_token = tokens.get("refresh_token") or previous.get("refresh_token")
                if not isinstance(refresh_token, str) or not refresh_token:
                    raise GoogleOAuthError("Google did not provide offline access. Please sign in again.")

                phase = "credential_store_save"
                store.save("youtube", {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": int(time.time()) + expires_in,
                    "scopes": sorted(scopes),
                    "client_id": flow["client_id"],
                })
                flow.update(status="connected", message="YouTube is connected.")
    except Exception as error:
        # Log only the failing phase, exception class, HTTP status, and a
        # provider error identifier. Never log request URLs, response bodies,
        # authorization codes, access/refresh tokens, or PKCE material.
        http_status = None
        provider_code = None
        response = getattr(error, "response", None)
        if isinstance(response, httpx.Response):
            http_status = response.status_code
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                candidate = payload.get("error")
                if (
                    isinstance(candidate, str)
                    and 0 < len(candidate) <= 80
                    and candidate.isascii()
                    and candidate.replace("_", "").replace("-", "").isalnum()
                ):
                    provider_code = candidate

        safe_reason = str(error) if isinstance(error, (GoogleOAuthError, CredentialStoreError)) else type(error).__name__
        _LOG.warning(
            "Google OAuth callback failed (phase=%s, reason=%s, http_status=%s, provider_error=%s)",
            phase,
            safe_reason,
            http_status if http_status is not None else "-",
            provider_code or "-",
        )
        flow.update(
            status="error",
            message="Clippy could not verify or securely save Google access. Please try again.",
        )
    finally:
        _close_listener(flow)


async def google_flow_status(flow_id: str) -> dict[str, str]:
    flow = _GOOGLE_FLOWS.get(flow_id)
    if not flow:
        raise GoogleOAuthError("This sign-in attempt has expired. Start again.")
    if flow["status"] == "pending" and time.monotonic() >= flow["expires_at"]:
        flow.update(status="expired", message="Google sign-in expired. Please try again.")
        _close_listener(flow)
    return {"status": flow["status"], "message": flow["message"]}


async def cancel_all_google_flows() -> int:
    """Invalidate pending Google callbacks before local disconnect."""
    async with _GOOGLE_LOCK:
        flows = list(_GOOGLE_FLOWS.values())
        _GOOGLE_FLOWS.clear()
        servers = []
        for flow in flows:
            flow.update(status="cancelled", message="Google sign-in was cancelled.")
            server = flow.get("server")
            if server:
                server.close()
                servers.append(server)
            flow["verifier"] = ""
        for server in servers:
            await server.wait_closed()
        return len(flows)


async def cancel_google_flow(flow_id: str) -> bool:
    async with _GOOGLE_LOCK:
        flow = _GOOGLE_FLOWS.pop(flow_id, None)
        if not flow:
            return False
        server = flow.get("server")
        if server:
            server.close()
            await server.wait_closed()
        flow["verifier"] = ""
        return True
