import asyncio
import threading
from pathlib import Path

import pytest

from community_highlights.capture_sessions import CaptureSessionManager, CaptureSettings


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
