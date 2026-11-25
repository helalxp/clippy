import asyncio
from datetime import datetime, timezone

from community_highlights.capture_sessions import CaptureSessionManager
from community_highlights.state_store import CommunityHighlightsStateStore, StateStoreError
from community_highlights.trigger_coordinator import TriggerCoordinator


SESSION_ID = "session_12345678901234567890"
READY_ID = "candidate_12345678901234567890"
PARTIAL_ID = "partial_12345678901234567890"


def test_trigger_settings_survive_coordinator_recreation(tmp_path):
    store = CommunityHighlightsStateStore(tmp_path)
    first = TriggerCoordinator(object(), state_store=store)
    saved = first.configure(
        phrases=["clip it", "clip that"],
        min_messages=3,
        min_unique_users=2,
        window_seconds=8,
        cooldown_seconds=45,
        pre_seconds=30,
        post_seconds=25,
    )

    second = TriggerCoordinator(object(), state_store=CommunityHighlightsStateStore(tmp_path))
    second.restore()

    assert second.settings() == saved


def test_failed_trigger_settings_write_does_not_change_active_configuration():
    class BrokenStore:
        def update_sections(self, **_sections):
            raise StateStoreError("disk unavailable")

    coordinator = TriggerCoordinator(object(), state_store=BrokenStore())
    before = coordinator.settings()

    try:
        coordinator.configure(
            phrases=["new phrase"],
            min_messages=4,
            min_unique_users=2,
            window_seconds=8,
            cooldown_seconds=45,
            pre_seconds=30,
            post_seconds=25,
        )
    except StateStoreError:
        pass
    else:
        raise AssertionError("A failed settings write must be reported.")

    assert coordinator.settings() == before


def test_restart_marks_active_capture_and_partial_candidate_and_preserves_approved_mp4(tmp_path):
    output_root = tmp_path / "community-highlights"
    store = CommunityHighlightsStateStore(tmp_path)
    session_dir = output_root / SESSION_ID
    highlights_dir = session_dir / "highlights"
    highlights_dir.mkdir(parents=True)

    ready_video = highlights_dir / f"{READY_ID}.mp4"
    ready_video.write_bytes(b"complete-approved-mp4")
    partial_video = highlights_dir / f"{PARTIAL_ID}.mp4"
    partial_video.write_bytes(b"partial-mp4")
    rolling_segment = session_dir / "segment-00000000.ts"
    rolling_segment.write_bytes(b"stale-rolling-segment")
    segment_index = session_dir / "segments.csv"
    segment_index.write_text("filename,duration\n", encoding="utf-8")
    abandoned_manifest = highlights_dir / "highlight-abandoned.ffconcat"
    abandoned_manifest.write_text("ffconcat version 1.0\n", encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    store.update_sections(
        capture_sessions=[{
            "session_id": SESSION_ID,
            "provider": "youtube",
            "stream_id": "abcdefghijk",
            "started_at": now,
            "status": "recording",
            "segment_seconds": 4,
            "retention_seconds": 180,
            "max_buffer_size_mb": 512,
            "quality": "best",
        }],
        candidates=[
            {
                "candidate_id": READY_ID,
                "capture_session_id": SESSION_ID,
                "triggered_at": now,
                "pre_seconds": 30,
                "post_seconds": 25,
                "reason": "phrase",
                "status": "ready",
                "review_status": "approved",
                "segment_count": 8,
                "trigger_count": 2,
            },
            {
                "candidate_id": PARTIAL_ID,
                "capture_session_id": SESSION_ID,
                "triggered_at": now,
                "pre_seconds": 20,
                "post_seconds": 30,
                "reason": "chat_volume",
                "status": "assembling",
                "review_status": "pending",
                "segment_count": 0,
                "trigger_count": 1,
            },
        ],
    )

    manager = CaptureSessionManager(output_root=output_root, state_store=store)
    manager.restore()

    sessions = manager.list()
    assert len(sessions) == 1
    assert sessions[0]["status"] == "interrupted"
    assert "restarted" in sessions[0]["error"].lower()

    ready = manager.get_candidate(READY_ID)
    assert ready is not None
    assert ready[0]["status"] == "ready"
    assert ready[0]["review_status"] == "approved"
    assert ready[0]["trigger_count"] == 2
    assert ready[1] == ready_video
    assert ready_video.read_bytes() == b"complete-approved-mp4"

    partial = manager.get_candidate(PARTIAL_ID)
    assert partial is not None
    assert partial[0]["status"] == "error"
    assert "restarted" in partial[0]["error"].lower()
    assert partial[1] is None
    assert partial_video.exists(), "partial media is preserved until explicitly deleted"

    # A restarted process has no live capture/candidate readers, so only the
    # disposable TS ring and FFmpeg work files are reconciled away.
    assert not rolling_segment.exists()
    assert not segment_index.exists()
    assert not abandoned_manifest.exists()
    assert ready_video.exists()

    assert manager.delete_candidate(PARTIAL_ID) is True
    assert not partial_video.exists()
    assert manager.get_candidate(PARTIAL_ID) is None
