import asyncio
import threading
import time
from pathlib import Path

import pytest

from community_highlights.capture_sessions import CaptureSessionManager, CaptureSettings, HighlightCandidate
from community_highlights.state_store import StateStoreError


class FakeCapture:
    def __init__(self, _url, config):
        self.config = config
        self.stop_requested = False
        self.finished = threading.Event()

    def run(self, stop_event, *, on_started=None):
        if on_started:
            on_started()
        self.finished.wait(2)
        if stop_event.is_set():
            return
        self.finished.set()

    def request_stop(self):
        self.stop_requested = True
        self.finished.set()


def test_capture_session_uses_unique_directory_and_settings_snapshot(tmp_path):
    made = []

    def factory(url, config):
        capture = FakeCapture(url, config)
        made.append(capture)
        return capture

    manager = CaptureSessionManager(capture_factory=factory, output_root=tmp_path)
    settings = CaptureSettings(segment_seconds=6, retention_seconds=90, max_buffer_size_mb=128, quality="720p")
    started = manager.start("https://www.twitch.tv/example", settings)
    session = manager.get(started["session_id"])

    assert session["provider"] == "twitch"
    assert session["stream_id"] == "example"
    assert session["segment_seconds"] == 6
    assert session["retention_seconds"] == 90
    assert session["max_buffer_size_mb"] == 128
    assert session["quality"] == "720p"
    assert Path(made[0].config.output_dir).parent == tmp_path


def test_repeated_capture_start_for_same_stream_reuses_the_active_session(tmp_path):
    made = []

    def factory(url, config):
        capture = FakeCapture(url, config)
        made.append(capture)
        return capture

    manager = CaptureSessionManager(capture_factory=factory, output_root=tmp_path)
    first = manager.start("https://www.twitch.tv/example")
    second = manager.start(
        "https://m.twitch.tv/EXAMPLE",
        CaptureSettings(quality="720p"),
    )

    assert second["session_id"] == first["session_id"]
    assert second["quality"] == "best"
    assert len(made) == 1
    assert len(manager.list()) == 1
    assert asyncio.run(manager.stop(first["session_id"])) is True


def test_capture_session_rejects_unsupported_url(tmp_path):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    with pytest.raises(ValueError):
        manager.start("https://example.com/live")


def test_capture_session_enforces_concurrency_limit(tmp_path):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path, max_sessions=1)
    manager.start("https://www.twitch.tv/one")
    with pytest.raises(ValueError, match="up to 1"):
        manager.start("https://www.twitch.tv/two")


def test_capture_session_stop_requests_worker_shutdown(tmp_path):
    made = []

    def factory(url, config):
        capture = FakeCapture(url, config)
        made.append(capture)
        return capture

    manager = CaptureSessionManager(capture_factory=factory, output_root=tmp_path)
    started = manager.start("https://www.twitch.tv/example")
    assert asyncio.run(manager.stop(started["session_id"])) is True
    assert made[0].stop_requested is True
    assert manager.get(started["session_id"])["status"] == "stopped"


def test_capture_session_status_does_not_echo_original_url(tmp_path):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    started = manager.start("https://www.youtube.com/watch?v=abcdefghijk&token=secret")
    snapshot = manager.get(started["session_id"])
    assert "youtube.com" not in repr(snapshot)
    assert "secret" not in repr(snapshot)


def test_finished_capture_releases_concurrency_slot(tmp_path):
    class FinishedCapture:
        def __init__(self, _url, _config):
            pass

        def run(self, _stop_event, *, on_started=None):
            if on_started:
                on_started()
            return

        def request_stop(self):
            pass

    manager = CaptureSessionManager(
        capture_factory=FinishedCapture, output_root=tmp_path, max_sessions=1
    )
    first = manager.start("https://www.twitch.tv/first")
    worker = manager._sessions[first["session_id"]].worker
    worker.join(timeout=1)
    assert manager.get(first["session_id"])["status"] == "ended"

    second = manager.start("https://www.twitch.tv/second")
    assert second["stream_id"] == "second"


def test_capture_settings_reject_invalid_quality_and_retention(tmp_path):
    with pytest.raises(ValueError, match="supported stream quality"):
        CaptureSettings(quality="not-a-quality").snapshot(tmp_path)
    with pytest.raises(ValueError, match="at least two segments"):
        CaptureSettings(segment_seconds=10, retention_seconds=10).snapshot(tmp_path)


def test_finished_capture_remains_visible_until_capacity_is_reused(tmp_path):
    class FinishedCapture:
        def __init__(self, _url, _config):
            pass

        def run(self, _stop_event, *, on_started=None):
            if on_started:
                on_started()

        def request_stop(self):
            pass

    manager = CaptureSessionManager(
        capture_factory=FinishedCapture, output_root=tmp_path, max_sessions=1
    )
    started = manager.start("https://www.twitch.tv/finished")
    manager._sessions[started["session_id"]].worker.join(timeout=1)

    assert manager.list()[0]["status"] == "ended"
    assert manager.get(started["session_id"])["status"] == "ended"
    manager.start("https://www.twitch.tv/next")
    assert manager.get(started["session_id"]) is None


def _ready_candidate(candidate_id, session_id, output_path=None, worker=None):
    from datetime import datetime, timezone

    return HighlightCandidate(
        candidate_id=candidate_id,
        capture_session_id=session_id,
        triggered_at=datetime.now(timezone.utc),
        pre_seconds=10,
        post_seconds=10,
        reason="manual",
        status="ready",
        review_status="approved",
        output_path=output_path,
        worker=worker,
    )


def test_delete_approved_candidate_removes_media_and_frees_queue_slot(tmp_path):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    candidate_id = "candidate-safe-delete"
    session_id = "session-safe-delete"
    output_dir = tmp_path / session_id / "highlights"
    output_dir.mkdir(parents=True)
    media = output_dir / f"{candidate_id}.mp4"
    media.write_bytes(b"candidate media")
    manager._candidates[candidate_id] = _ready_candidate(candidate_id, session_id, media)

    assert manager.delete_candidate(candidate_id) is True
    assert not media.exists()
    assert candidate_id not in manager._candidates


def test_delete_candidate_keeps_metadata_when_file_is_locked_or_unwritable(tmp_path, monkeypatch):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    candidate_id = "candidate-delete-failure"
    session_id = "session-delete-failure"
    output_dir = tmp_path / session_id / "highlights"
    output_dir.mkdir(parents=True)
    media = output_dir / f"{candidate_id}.mp4"
    media.write_bytes(b"candidate media")
    manager._candidates[candidate_id] = _ready_candidate(candidate_id, session_id, media)

    def fail_replace(_path, *_args, **_kwargs):
        raise PermissionError("file is in use")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError):
        manager.delete_candidate(candidate_id)
    assert candidate_id in manager._candidates


def test_delete_candidate_refuses_while_worker_is_running(tmp_path):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    candidate_id = "candidate-busy"
    session_id = "session-busy"
    release = threading.Event()
    worker = threading.Thread(target=release.wait)
    worker.start()
    manager._candidates[candidate_id] = _ready_candidate(candidate_id, session_id, worker=worker)

    try:
        with pytest.raises(ValueError, match="still being created"):
            manager.delete_candidate(candidate_id)
        assert candidate_id in manager._candidates
    finally:
        release.set()
        worker.join(timeout=2)


def test_delete_candidate_rejects_media_path_outside_capture_root(tmp_path):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path / "captures")
    outside = tmp_path / "outside.ts"
    outside.write_bytes(b"must survive")
    candidate_id = "candidate-path-check"
    session_id = "session-path-check"
    manager._candidates[candidate_id] = _ready_candidate(candidate_id, session_id, outside)

    with pytest.raises(RuntimeError, match="storage-boundary"):
        manager.delete_candidate(candidate_id)
    assert outside.exists()
    assert candidate_id in manager._candidates


def test_delete_unknown_candidate_returns_false(tmp_path):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    assert manager.delete_candidate("missing") is False


def test_stopped_capture_deletes_rolling_sources_but_preserves_candidate_mp4(tmp_path):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    started = manager.start("https://www.twitch.tv/cleanup")
    session = manager._sessions[started["session_id"]]
    source_dir = session.config.output_dir
    source_dir.mkdir(parents=True, exist_ok=True)
    segment = source_dir / "segment-00000000.ts"
    index = source_dir / "segments.csv"
    segment.write_bytes(b"rolling source")
    index.write_text("segment-00000000.ts,0,4\n", encoding="utf-8")
    highlights = source_dir / "highlights"
    highlights.mkdir()
    approved = highlights / "candidate-approved.mp4"
    approved.write_bytes(b"approved media")
    abandoned_manifest = highlights / "highlight-abandoned.ffconcat"
    abandoned_manifest.write_text("ffconcat version 1.0\\n", encoding="utf-8")

    assert asyncio.run(manager.stop(started["session_id"])) is True

    assert not segment.exists()
    assert not index.exists()
    assert not abandoned_manifest.exists()
    assert approved.is_file()


def test_cleanup_waits_for_capture_worker_after_stop_timeout(tmp_path):
    class SlowCapture:
        def __init__(self, _url, config):
            self.config = config
            self.release = threading.Event()

        def run(self, _stop_event, *, on_started=None):
            if on_started:
                on_started()
            self.release.wait(5)

        def request_stop(self):
            # Simulate a Streamlink/FFmpeg worker that has not yet unwound.
            pass

    made = []

    def factory(url, config):
        capture = SlowCapture(url, config)
        made.append(capture)
        return capture

    manager = CaptureSessionManager(capture_factory=factory, output_root=tmp_path)
    started = manager.start("https://www.twitch.tv/slowcleanup")
    session = manager._sessions[started["session_id"]]
    deadline = time.time() + 1
    while session.status != "recording" and time.time() < deadline:
        time.sleep(0.01)

    segment = session.config.output_dir / "segment-00000000.ts"
    segment.parent.mkdir(parents=True, exist_ok=True)
    segment.write_bytes(b"still in use")
    # This is the state stop() records if its worker-join timeout expires.
    session.status = "error"

    manager._cleanup_rolling_segments_if_finished(session)
    assert segment.exists()

    made[0].release.set()
    session.worker.join(timeout=2)
    assert not session.worker.is_alive()
    assert not segment.exists()

def test_delete_candidate_rolls_back_media_when_metadata_commit_fails(tmp_path, monkeypatch):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    candidate_id = "candidate-delete-rollback"
    session_id = "session-delete-rollback"
    output_dir = tmp_path / session_id / "highlights"
    output_dir.mkdir(parents=True)
    media = output_dir / f"{candidate_id}.mp4"
    media.write_bytes(b"candidate media")
    manager._candidates[candidate_id] = _ready_candidate(candidate_id, session_id, media)

    def fail_persist(*, strict=False):
        if strict:
            raise StateStoreError("storage unavailable")

    monkeypatch.setattr(manager, "_persist_locked", fail_persist)

    with pytest.raises(StateStoreError):
        manager.delete_candidate(candidate_id)

    pending = output_dir / f".{candidate_id}.delete-pending.mp4"
    assert candidate_id in manager._candidates
    assert media.read_bytes() == b"candidate media"
    assert not pending.exists()


def test_rejected_candidate_is_not_exposed_for_preview_when_windows_keeps_media_open(tmp_path, monkeypatch):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    candidate_id = "candidate-rejected-open"
    session_id = "session-rejected-open"
    output_dir = tmp_path / session_id / "highlights"
    output_dir.mkdir(parents=True)
    media = output_dir / f"{candidate_id}.mp4"
    media.write_bytes(b"rejected media")
    manager._candidates[candidate_id] = _ready_candidate(candidate_id, session_id, media)

    original_unlink = Path.unlink

    def fail_media_unlink(path, *args, **kwargs):
        if path == media:
            raise PermissionError("file is in use")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_media_unlink)

    decision = manager.decide_candidate(candidate_id, approved=False)
    candidate, preview_path = manager.get_candidate(candidate_id)

    assert decision["review_status"] == "rejected"
    assert candidate["review_status"] == "rejected"
    assert preview_path is None
    assert media.is_file()


def test_get_candidate_does_not_expose_symlinked_media(tmp_path):
    manager = CaptureSessionManager(capture_factory=FakeCapture, output_root=tmp_path)
    candidate_id = "candidate-preview-symlink"
    session_id = "session-preview-symlink"
    output_dir = tmp_path / session_id / "highlights"
    output_dir.mkdir(parents=True)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside media")
    media = output_dir / f"{candidate_id}.mp4"
    try:
        media.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("This Windows environment does not grant symlink creation.")
    manager._candidates[candidate_id] = _ready_candidate(candidate_id, session_id, media)

    candidate, preview_path = manager.get_candidate(candidate_id)

    assert candidate["status"] == "ready"
    assert preview_path is None
    assert outside.read_bytes() == b"outside media"


def test_natural_end_cleans_rolling_sources_after_simultaneous_candidate_workers(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    class FiniteCapture:
        def __init__(self, _url, config):
            self.config = config
            self.finish = threading.Event()

        def run(self, _stop_event, *, on_started=None):
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            (self.config.output_dir / "segment-00000000.ts").write_bytes(b"rolling source")
            (self.config.output_dir / "segments.csv").write_text(
                "segment-00000000.ts,0,4\n", encoding="utf-8"
            )
            if on_started:
                on_started()
            self.finish.wait(3)

        def request_stop(self):
            self.finish.set()

    made = []

    def factory(url, config):
        capture = FiniteCapture(url, config)
        made.append(capture)
        return capture

    manager = CaptureSessionManager(capture_factory=factory, output_root=tmp_path)
    started = manager.start("https://www.twitch.tv/natural_cleanup")
    session = manager._sessions[started["session_id"]]
    deadline = time.time() + 1
    while session.status != "recording" and time.time() < deadline:
        time.sleep(0.01)
    assert session.status == "recording"

    segment = session.config.output_dir / "segment-00000000.ts"
    index = session.config.output_dir / "segments.csv"
    assert segment.is_file() and index.is_file()

    barrier = threading.Barrier(3)
    original_cleanup = manager._cleanup_rolling_segments_if_finished

    def synchronized_cleanup(target_session):
        barrier.wait(timeout=3)
        original_cleanup(target_session)

    monkeypatch.setattr(manager, "_cleanup_rolling_segments_if_finished", synchronized_cleanup)

    candidate_workers = []
    for suffix in ("first", "second"):
        candidate = HighlightCandidate(
            candidate_id=f"candidate-cleanup-{suffix}",
            capture_session_id=session.session_id,
            triggered_at=datetime.now(timezone.utc),
            pre_seconds=1,
            post_seconds=1,
            reason="manual",
            status="capturing",
        )

        def finish_candidate(item=candidate):
            session.stop_event.wait(3)
            with manager._lock:
                item.status = "error"
            synchronized_cleanup(session)

        candidate.worker = threading.Thread(
            target=finish_candidate,
            name=f"candidate-cleanup-{suffix}",
            daemon=True,
        )
        manager._candidates[candidate.candidate_id] = candidate
        candidate_workers.append(candidate.worker)
        candidate.worker.start()

    made[0].finish.set()
    session.worker.join(timeout=3)
    for worker in candidate_workers:
        worker.join(timeout=3)

    assert session.capture_finished.is_set()
    assert not session.worker.is_alive()
    assert all(not worker.is_alive() for worker in candidate_workers)
    assert not segment.exists()
    assert not index.exists()



def test_trigger_rejects_when_pre_roll_has_not_warmed_up(tmp_path):
    class WarmingCapture(FakeCapture):
        def buffer_status(self):
            return {
                "buffered_seconds": 20.0,
                "latest_segment_age_seconds": 1.0,
            }

        def read_segment_index(self):
            return []

    manager = CaptureSessionManager(
        capture_factory=WarmingCapture,
        output_root=tmp_path,
    )
    started = manager.start("https://www.twitch.tv/warming")
    session_id = started["session_id"]
    session = manager._sessions[session_id]
    deadline = time.time() + 1
    while session.status != "recording" and time.time() < deadline:
        time.sleep(0.01)

    from datetime import datetime, timezone
    with pytest.raises(ValueError, match="still warming up"):
        manager.trigger(
            provider="twitch",
            stream_id="warming",
            triggered_at=datetime.now(timezone.utc),
            pre_seconds=45,
            post_seconds=15,
        )

    assert manager.list_candidates(session_id) == []
    assert asyncio.run(manager.stop(session_id)) is True
