"""Community Highlights API surface.

Only safe connection and flow metadata is returned to the frontend. Provider
credentials and device codes remain in the backend and Windows Credential Manager.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from .chat import chat_sessions
from .capture_sessions import CaptureSettings, capture_sessions
from .trigger_coordinator import trigger_coordinator
from .rolling_capture import RollingCaptureError
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


def connection_status(store_factory=None) -> dict:
    """Return provider connection metadata without exposing stored credentials."""
    if store_factory is None:
        store_factory = WindowsCredentialStore
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


class StartCaptureSessionRequest(BaseModel):
    stream_url: str = Field(min_length=1, max_length=2048)
    segment_seconds: int = Field(default=4, ge=1, le=60)
    retention_seconds: int = Field(default=180, ge=2, le=3600)
    max_buffer_size_mb: int = Field(default=512, ge=16, le=8192)
    quality: str = Field(default="best", min_length=1, max_length=16)


class TriggerSettingsRequest(BaseModel):
    phrases: list[str] = Field(default_factory=lambda: ["clip it", "clip that"], max_length=30)
    min_messages: int = Field(default=12, ge=2, le=500)
    min_unique_users: int = Field(default=5, ge=1, le=500)
    window_seconds: float = Field(default=10, ge=1, le=120)
    cooldown_seconds: float = Field(default=60, ge=0, le=3600)
    pre_seconds: int = Field(default=45, ge=0, le=300)
    post_seconds: int = Field(default=45, ge=0, le=300)


class ManualTriggerRequest(BaseModel):
    pre_seconds: int = Field(default=45, ge=0, le=300)
    post_seconds: int = Field(default=45, ge=0, le=300)
    reason: str = Field(default="manual", min_length=1, max_length=40)


class CandidateDecisionRequest(BaseModel):
    approved: bool


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


@router.get("/api/community-highlights/captures")
async def list_capture_sessions():
    return {"sessions": capture_sessions.list()}


@router.post("/api/community-highlights/captures")
async def start_capture_session(body: StartCaptureSessionRequest):
    settings = CaptureSettings(
        segment_seconds=body.segment_seconds,
        retention_seconds=body.retention_seconds,
        max_buffer_size_mb=body.max_buffer_size_mb,
        quality=body.quality,
    )
    try:
        return capture_sessions.start(body.stream_url, settings)
    except (StreamUrlError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.get("/api/community-highlights/captures/{session_id}")
async def get_capture_session(session_id: str):
    session = capture_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Capture session not found.")
    return session


@router.delete("/api/community-highlights/captures/{session_id}")
async def stop_capture_session(session_id: str):
    stopped = await capture_sessions.stop(session_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Capture session not found.")
    return {"stopped": True}


@router.on_event("shutdown")
async def stop_community_highlights_workers():
    """Stop owned background work before the backend process exits."""
    await capture_sessions.stop_all()
    for session in await chat_sessions.list():
        await chat_sessions.stop(session["session_id"])


@router.get("/api/community-highlights/triggers/settings")
async def get_trigger_settings():
    return trigger_coordinator.settings()


@router.put("/api/community-highlights/triggers/settings")
async def update_trigger_settings(body: TriggerSettingsRequest):
    try:
        return trigger_coordinator.configure(**body.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.get("/api/community-highlights/candidates")
async def list_highlight_candidates(capture_session_id: str | None = None):
    return {"candidates": capture_sessions.list_candidates(capture_session_id)}


@router.get("/api/community-highlights/candidates/{candidate_id}")
async def get_highlight_candidate(candidate_id: str):
    candidate = capture_sessions.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Highlight candidate not found.")
    return candidate[0]


@router.delete("/api/community-highlights/candidates/{candidate_id}")
async def delete_highlight_candidate(candidate_id: str):
    try:
        deleted = capture_sessions.delete_candidate(candidate_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except OSError:
        raise HTTPException(
            status_code=409,
            detail="The highlight file could not be deleted. Close any app using it and try again.",
        ) from None
    except RuntimeError:
        raise HTTPException(
            status_code=500,
            detail="The highlight file failed its storage safety check.",
        ) from None
    if not deleted:
        raise HTTPException(status_code=404, detail="Highlight candidate not found.")
    return {"deleted": True}


@router.get("/api/community-highlights/candidates/{candidate_id}/file")
async def download_highlight_candidate(candidate_id: str):
    candidate = capture_sessions.get_candidate(candidate_id)
    if candidate is None or candidate[1] is None or not candidate[1].is_file():
        raise HTTPException(status_code=404, detail="Highlight file is not ready.")
    return FileResponse(
        candidate[1],
        media_type="video/mp2t",
        filename=f"community-highlight-{candidate_id}.ts",
    )


@router.post("/api/community-highlights/captures/{session_id}/trigger")
async def trigger_highlight(session_id: str, body: ManualTriggerRequest):
    session = capture_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Capture session not found.")
    try:
        candidate = capture_sessions.trigger(
            provider=session["provider"],
            stream_id=session["stream_id"],
            triggered_at=datetime.now(timezone.utc),
            pre_seconds=body.pre_seconds,
            post_seconds=body.post_seconds,
            reason=body.reason,
        )
    except (ValueError, RollingCaptureError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    if candidate is None:
        raise HTTPException(status_code=409, detail="Capture is not recording.")
    return candidate


@router.post("/api/community-highlights/candidates/{candidate_id}/decision")
async def decide_highlight_candidate(candidate_id: str, body: CandidateDecisionRequest):
    try:
        candidate = capture_sessions.decide_candidate(candidate_id, approved=body.approved)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    if candidate is None:
        raise HTTPException(status_code=404, detail="Highlight candidate not found.")
    return candidate
