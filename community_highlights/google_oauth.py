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
GOOGLE_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
GOOGLE_ISSUER = "https://accounts.google.com"
_LOG = logging.getLogger(__name__)
_GOOGLE_FLOWS: dict[str, dict[str, Any]] = {}
_GOOGLE_FLOW_TTL = 600
_GOOGLE_EXPIRY_TASKS: set[asyncio.Task] = set()


class GoogleOAuthError(RuntimeError):
    """Safe, user-displayable Google authorization failure."""


def google_client_id() -> str:
    return os.environ.get("CLIPPY_GOOGLE_OAUTH_CLIENT_ID", "").strip()



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


def _close_listener(flow: dict[str, Any]):
    flow["verifier"] = ""
    server = flow.get("server")
    if server:
        server.close()
    return server


def _google_callback_values(params: Any) -> tuple[str, str, str | None, str | None] | None:
    """Return one unambiguous Google callback, or reject it without consuming the flow."""
    if not isinstance(params, dict):
        return None
    values = {}
    for name in ("state", "iss", "code", "error"):
        entries = params.get(name, [])
        if not isinstance(entries, list) or len(entries) > 1:
            return None
        values[name] = entries
    if len(values["state"]) != 1 or not values["state"][0]:
        return None
    if len(values["iss"]) != 1 or not values["iss"][0]:
        return None
    if bool(values["code"]) == bool(values["error"]):
        return None
    state, issuer = values["state"][0], values["iss"][0]
    code = values["code"][0] if values["code"] else None
    error = values["error"][0] if values["error"] else None
    if not isinstance(state, str) or not isinstance(issuer, str):
        return None
    if code is not None and (not isinstance(code, str) or not code):
        return None
    if error is not None and (not isinstance(error, str) or not error):
        return None
    return state, issuer, code, error


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
                    try:
                        params = parse_qs(
                            parsed.query, keep_blank_values=True,
                            strict_parsing=True, max_num_fields=32,
                        )
                    except ValueError:
                        params = {}
                    result = await _complete_google_callback(flow_id, params)
                    status = "200 OK" if result is not None else "400 Bad Request"
                    message = (
                        "Google authorization is complete. You can return to Clippy."
                        if result == "connected"
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
        now = time.monotonic()
        for key, current in list(_GOOGLE_FLOWS.items()):
            if current["expires_at"] <= now or current["status"] != "pending":
                _close_listener(current)
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
    })
    return {
        "flow_id": flow_id,
        "authorization_url": f"{GOOGLE_AUTH_URL}?{query}",
        "expires_in": _GOOGLE_FLOW_TTL,
    }


def _expire_google_flow_if_due(flow: dict[str, Any] | None) -> None:
    if flow and flow["status"] == "pending" and time.monotonic() >= flow["expires_at"]:
        flow.update(status="expired", message="Google sign-in expired. Please try again.")
        _close_listener(flow)


async def _expire_google_flow(flow_id: str) -> None:
    await asyncio.sleep(_GOOGLE_FLOW_TTL)
    async with provider_credential_lock("youtube"):
        _expire_google_flow_if_due(_GOOGLE_FLOWS.get(flow_id))


async def _complete_google_callback(flow_id: str, params: dict[str, list[str]]) -> str | None:
    callback = _google_callback_values(params)
    if callback is None:
        return None
    returned_state, issuer, code, provider_error = callback
    if issuer != GOOGLE_ISSUER:
        return None

    phase = "authorization_code_exchange"
    flow = None
    try:
        async with provider_credential_lock("youtube"):
            if provider_is_disconnecting("youtube"):
                return None
            flow = _GOOGLE_FLOWS.get(flow_id)
            if flow is None or flow["status"] != "pending":
                return None
            _expire_google_flow_if_due(flow)
            if flow["status"] != "pending":
                return None
            if not secrets.compare_digest(returned_state, flow["state"]):
                return None

            if provider_error:
                flow.update(
                    status="denied" if provider_error == "access_denied" else "error",
                    message="Google authorization was declined." if provider_error == "access_denied"
                    else "Google authorization could not be completed.",
                )
                return flow["status"]

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
            refresh_token = tokens.get("refresh_token")
            token_type = tokens.get("token_type")
            expires_in = tokens.get("expires_in")
            if not isinstance(access_token, str) or not access_token:
                raise GoogleOAuthError("Google did not return an access token.")
            if not isinstance(refresh_token, str) or not refresh_token:
                raise GoogleOAuthError("Google did not provide offline access. Please sign in again.")
            if not isinstance(token_type, str) or token_type.lower() != "bearer":
                raise GoogleOAuthError("Google returned an invalid access-token type.")
            if type(expires_in) is not int or expires_in <= 0:
                raise GoogleOAuthError("Google returned an invalid access-token lifetime.")

            granted_scope = tokens.get("scope")
            if granted_scope is None:
                scopes = {GOOGLE_SCOPE}
            elif isinstance(granted_scope, str):
                scopes = set(granted_scope.split())
            else:
                raise GoogleOAuthError("Google returned invalid granted YouTube permissions.")

            phase = "scope_validation"
            if GOOGLE_SCOPE not in scopes:
                raise GoogleOAuthError("Google did not grant the required read-only YouTube permission.")

            phase = "credential_store_save"
            store = flow["store_factory"]()
            store.save("youtube", {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": int(time.time()) + expires_in,
                "scopes": sorted(scopes),
                "client_id": flow["client_id"],
            })
            flow.update(status="connected", message="YouTube is connected.")
            return "connected"
    except Exception as error:
        http_status = None
        provider_code = None
        provider_description = None
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
                candidate_description = payload.get("error_description")
                if (
                    isinstance(candidate_description, str)
                    and 0 < len(candidate_description) <= 180
                    and candidate_description.isascii()
                    and all(char.isalnum() or char in " .,;:_()/-" for char in candidate_description)
                ):
                    provider_description = " ".join(candidate_description.split())

        safe_reason = str(error) if isinstance(error, (GoogleOAuthError, CredentialStoreError)) else type(error).__name__
        _LOG.warning(
            "Google OAuth callback failed (phase=%s, reason=%s, http_status=%s, provider_error=%s, provider_error_description=%s)",
            phase, safe_reason, http_status if http_status is not None else "-",
            provider_code or "-", provider_description or "-",
        )
        if flow is not None and flow.get("status") == "pending":
            flow.update(
                status="error",
                message="Clippy could not verify or securely save Google access. Please try again.",
            )
        return "error" if flow is not None else None
    finally:
        if flow is not None and flow.get("status") != "pending":
            _close_listener(flow)


async def google_flow_status(flow_id: str) -> dict[str, str]:
    async with provider_credential_lock("youtube"):
        flow = _GOOGLE_FLOWS.get(flow_id)
        if not flow:
            raise GoogleOAuthError("This sign-in attempt has expired. Start again.")
        _expire_google_flow_if_due(flow)
        return {"status": flow["status"], "message": flow["message"]}


async def cancel_all_google_flows() -> int:
    """Invalidate all outstanding flows while the caller owns the provider lock."""
    flows = list(_GOOGLE_FLOWS.values())
    _GOOGLE_FLOWS.clear()
    servers = []
    for flow in flows:
        flow.update(status="cancelled", message="Google sign-in was cancelled.")
        server = _close_listener(flow)
        if server:
            servers.append(server)
    for server in servers:
        await server.wait_closed()
    return len(flows)


async def cancel_google_flow(flow_id: str) -> bool:
    async with provider_credential_lock("youtube"):
        flow = _GOOGLE_FLOWS.get(flow_id)
        if not flow or flow["status"] != "pending":
            return False
        _GOOGLE_FLOWS.pop(flow_id, None)
        flow.update(status="cancelled", message="Google sign-in was cancelled.")
        server = _close_listener(flow)
        if server:
            await server.wait_closed()
        return True
