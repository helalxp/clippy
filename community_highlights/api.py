"""Community Highlights API surface.

Only safe connection and flow metadata is returned to the frontend. Provider
credentials and device codes remain in the backend and Windows Credential Manager.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .chat import chat_sessions
from .urls import StreamUrlError

from .credentials import CredentialStoreError, WindowsCredentialStore
from .google_oauth import (
    GoogleOAuthError,
    cancel_google_flow,
    google_authorization_available,
    google_flow_status,
    start_google_flow,
)
from .twitch_oauth import (
    TwitchOAuthError,
    cancel_twitch_flow,
    poll_twitch_flow,
    start_twitch_flow,
    twitch_authorization_available,
)

router = APIRouter()


def connection_status(store_factory=WindowsCredentialStore) -> dict:
    """Return provider connection metadata without exposing stored credentials."""
    try:
        store = store_factory()
    except CredentialStoreError:
        return {
            "credential_storage_available": False,
            "providers": {
                provider: {
                    "provider": provider,
                    "connected": False,
                    "authorization_available": False,
                    "status": "storage_unavailable",
                }
                for provider in ("twitch", "youtube")
            },
        }

    providers = {}
    for provider in ("twitch", "youtube"):
        try:
            bundle = store.load(provider)
        except CredentialStoreError:
            status = "credential_error"
        else:
            connected = isinstance(bundle, dict) and isinstance(
                bundle.get("access_token"), str
            ) and bool(bundle["access_token"])
            status = "credentials_saved" if connected else "not_connected"

        providers[provider] = {
            "provider": provider,
            "connected": status == "credentials_saved",
            "authorization_available": (
                twitch_authorization_available() if provider == "twitch"
                else google_authorization_available()
            ),
            "status": status,
        }

    return {
        "credential_storage_available": True,
        "providers": providers,
    }


@router.get("/api/community-highlights/connections")
async def get_connections():
    return connection_status()


@router.post("/api/community-highlights/twitch/authorize")
async def begin_twitch_authorization():
    try:
        return await start_twitch_flow()
    except (TwitchOAuthError, CredentialStoreError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from None


@router.get("/api/community-highlights/twitch/authorize/{flow_id}")
async def get_twitch_authorization_status(flow_id: str):
    if len(flow_id) < 32 or len(flow_id) > 128:
        raise HTTPException(status_code=404, detail="Sign-in attempt not found.")
    try:
        return await poll_twitch_flow(flow_id)
    except TwitchOAuthError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None


@router.delete("/api/community-highlights/twitch/authorize/{flow_id}")
async def stop_twitch_authorization(flow_id: str):
    if len(flow_id) < 32 or len(flow_id) > 128:
        raise HTTPException(status_code=404, detail="Sign-in attempt not found.")
    await cancel_twitch_flow(flow_id)
    return {"cancelled": True}


@router.delete("/api/community-highlights/connections/twitch")
async def disconnect_twitch():
    try:
        WindowsCredentialStore().delete("twitch")
    except CredentialStoreError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    return {"connected": False}



@router.post("/api/community-highlights/youtube/authorize")
async def begin_google_authorization():
    try:
        return await start_google_flow()
    except (GoogleOAuthError, CredentialStoreError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from None


@router.get("/api/community-highlights/youtube/authorize/{flow_id}")
async def get_google_authorization_status(flow_id: str):
    if len(flow_id) < 32 or len(flow_id) > 128:
        raise HTTPException(status_code=404, detail="Sign-in attempt not found.")
    try:
        return await google_flow_status(flow_id)
    except GoogleOAuthError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None


@router.delete("/api/community-highlights/youtube/authorize/{flow_id}")
async def stop_google_authorization(flow_id: str):
    if len(flow_id) < 32 or len(flow_id) > 128:
        raise HTTPException(status_code=404, detail="Sign-in attempt not found.")
    await cancel_google_flow(flow_id)
    return {"cancelled": True}


@router.delete("/api/community-highlights/connections/youtube")
async def disconnect_youtube():
    try:
        WindowsCredentialStore().delete("youtube")
    except CredentialStoreError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    return {"connected": False}



class StartChatSessionRequest(BaseModel):
    stream_url: str = Field(min_length=1, max_length=2048)


@router.get("/api/community-highlights/sessions")
async def list_chat_sessions():
    return {"sessions": await chat_sessions.list()}


@router.post("/api/community-highlights/sessions")
async def start_chat_session(body: StartChatSessionRequest):
    try:
        return await chat_sessions.start(body.stream_url)
    except (StreamUrlError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.get("/api/community-highlights/sessions/{session_id}")
async def get_chat_session(session_id: str):
    session = await chat_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return session


@router.delete("/api/community-highlights/sessions/{session_id}")
async def stop_chat_session(session_id: str):
    stopped = await chat_sessions.stop(session_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    return {"stopped": True}
