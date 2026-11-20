import asyncio
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from community_highlights.capture_sessions import CaptureSessionManager
from community_highlights.rolling_capture import SegmentRecord


class FakeIndexedCapture:
    def __init__(self, _url, config, record):
        self.config = config
        self.record = record
        self.protected = []
        self.released = []
        self.finished = threading.Event()

    def run(self, stop_event, *, on_started=None):
        if on_started:
            on_started()
        self.finished.wait(2)

    def read_segment_index(self):
        return [self.record]

    def protect_segments(self, paths):
        self.protected.extend(paths)
        return list(paths)

    def release_segments(self, paths):
        self.released.extend(paths)

    def request_stop(self):
        self.finished.set()


def test_trigger_protects_pre_segments_and_builds_candidate(tmp_path, monkeypatch):
    segment = tmp_path / "segment-00000000.ts"
    segment.write_bytes(b"mpeg-ts")
    now = time.time()
    import os
    os.utime(segment, (now, now))
    record = SegmentRecord(segment.resolve(), 0, 4)
    made = []

    def factory(url, config):
        capture = FakeIndexedCapture(url, config, record)
        made.append(capture)
        return capture

    def assemble(records, output_path, **_kwargs):
        assert records == [record]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"assembled")
        return output_path

    monkeypatch.setattr("community_highlights.capture_sessions.assemble_segments", assemble)
    manager = CaptureSessionManager(capture_factory=factory, output_root=tmp_path / "sessions")
    started = manager.start("https://www.twitch.tv/channel")
    worker = manager._sessions[started["session_id"]].worker
    deadline = time.time() + 1
    while manager.get(started["session_id"])["status"] != "recording" and time.time() < deadline:
        time.sleep(0.01)

    candidate = manager.trigger(
        provider="twitch",
        stream_id="channel",
        triggered_at=datetime.fromtimestamp(now, timezone.utc),
        pre_seconds=0,
        post_seconds=0,
        reason="manual",
    )
    candidate_id = candidate["candidate_id"]
    candidate_worker = manager._candidates[candidate_id].worker
    candidate_worker.join(timeout=1)

    result = manager.get_candidate(candidate_id)
    assert result[0]["status"] == "ready"
    assert result[1].is_file()
    assert made[0].protected == [segment.resolve()]
    assert made[0].released == [segment.resolve()]

    asyncio.run(manager.stop(started["session_id"]))
    worker.join(timeout=1)


def test_trigger_requires_matching_active_recording_session(tmp_path):
    class IdleCapture:
        def __init__(self, _url, config):
            self.config = config

        def run(self, _event, *, on_started=None):
            if on_started:
                on_started()

    manager = CaptureSessionManager(capture_factory=IdleCapture, output_root=tmp_path)
    started = manager.start("https://www.twitch.tv/channel")
    result = manager.trigger(
        provider="youtube",
        stream_id="abcdefghijk",
        triggered_at=datetime.now(timezone.utc),
        pre_seconds=0,
        post_seconds=0,
    )
    assert result is None


def test_candidate_decision_requires_ready_candidate(tmp_path, monkeypatch):
    segment = tmp_path / "segment-00000000.ts"
    segment.write_bytes(b"mpeg-ts")
    now = time.time()
    import os
    os.utime(segment, (now, now))
    record = SegmentRecord(segment.resolve(), 0, 4)

    def factory(url, config):
        return FakeIndexedCapture(url, config, record)

    def assemble(_records, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"assembled")
        return output_path

    monkeypatch.setattr("community_highlights.capture_sessions.assemble_segments", assemble)
    manager = CaptureSessionManager(capture_factory=factory, output_root=tmp_path / "sessions")
    started = manager.start("https://www.twitch.tv/channel")
    deadline = time.time() + 1
    while manager.get(started["session_id"])["status"] != "recording" and time.time() < deadline:
        time.sleep(0.01)

    candidate = manager.trigger(
        provider="twitch",
        stream_id="channel",
        triggered_at=datetime.fromtimestamp(now, timezone.utc),
        pre_seconds=0,
        post_seconds=0,
        reason="manual",
    )
    candidate_id = candidate["candidate_id"]
    manager._candidates[candidate_id].worker.join(timeout=1)

    decision = manager.decide_candidate(candidate_id, approved=True)
    assert decision["review_status"] == "approved"
    output_path = manager.get_candidate(candidate_id)[1]
    assert output_path.is_file()
    assert manager.decide_candidate(candidate_id, approved=False)["review_status"] == "rejected"
    assert not output_path.exists()
    try:
        manager.decide_candidate(candidate_id, approved=True)
    except ValueError as error:
        assert "cannot be re-approved" in str(error)
    else:
        raise AssertionError("deleted candidate should not be re-approved")

    asyncio.run(manager.stop(started["session_id"]))
