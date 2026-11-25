import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from community_highlights.capture_sessions import CaptureSessionManager
from community_highlights.rolling_capture import SegmentRecord
from community_highlights.state_store import StateStoreError


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


def test_post_trigger_segments_are_pinned_as_soon_as_they_arrive(tmp_path, monkeypatch):
    import os

    trigger_time = time.time() - 10
    pre_path = tmp_path / "segment-pre.ts"
    post_path = tmp_path / "segment-post.ts"
    pre_path.write_bytes(b"pre")
    post_path.write_bytes(b"post")
    os.utime(pre_path, (trigger_time, trigger_time))
    os.utime(post_path, (trigger_time + 4, trigger_time + 4))
    pre_record = SegmentRecord(pre_path.resolve(), 0, 4)
    post_record = SegmentRecord(post_path.resolve(), 4, 8)

    class IncrementalCapture(FakeIndexedCapture):
        def __init__(self, url, config):
            super().__init__(url, config, pre_record)
            self.index_reads = 0

        def read_segment_index(self):
            self.index_reads += 1
            return [pre_record] if self.index_reads == 1 else [pre_record, post_record]

    made = []

    def factory(url, config):
        capture = IncrementalCapture(url, config)
        made.append(capture)
        return capture

    def assemble(records, output_path, **_kwargs):
        assert records == [pre_record, post_record]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"preview mp4")
        return output_path

    monkeypatch.setattr("community_highlights.capture_sessions.assemble_segments", assemble)
    manager = CaptureSessionManager(capture_factory=factory, output_root=tmp_path / "sessions")
    started = manager.start("https://www.twitch.tv/channel")
    session_worker = manager._sessions[started["session_id"]].worker
    deadline = time.time() + 1
    while manager.get(started["session_id"])["status"] != "recording" and time.time() < deadline:
        time.sleep(0.01)

    candidate = manager.trigger(
        provider="twitch",
        stream_id="channel",
        triggered_at=datetime.fromtimestamp(trigger_time, timezone.utc),
        pre_seconds=4,
        post_seconds=1,
        reason="manual",
    )
    candidate_id = candidate["candidate_id"]
    candidate_worker = manager._candidates[candidate_id].worker
    candidate_worker.join(timeout=3)

    result = manager.get_candidate(candidate_id)
    assert result[0]["status"] == "ready"
    assert result[1].suffix == ".mp4"
    assert made[0].protected == [pre_path.resolve(), post_path.resolve()]
    assert made[0].released == [pre_path.resolve(), post_path.resolve()]

    asyncio.run(manager.stop(started["session_id"]))
    session_worker.join(timeout=1)



class BlockingCapture:
    def __init__(self, _url, config):
        self.config = config
        self.stop_requested = threading.Event()
        self.protected = []
        self.released = []

    def run(self, _stop_event, *, on_started=None):
        if on_started:
            on_started()
        self.stop_requested.wait(5)

    def read_segment_index(self):
        return []

    def protect_segments(self, paths):
        self.protected.extend(paths)
        return list(paths)

    def release_segments(self, paths):
        self.released.extend(paths)

    def request_stop(self):
        self.stop_requested.set()


def _recording_manager(tmp_path):
    manager = CaptureSessionManager(capture_factory=BlockingCapture, output_root=tmp_path)
    started = manager.start("https://www.twitch.tv/merge-channel")
    deadline = time.time() + 1
    while manager.get(started["session_id"])["status"] != "recording" and time.time() < deadline:
        time.sleep(0.01)
    assert manager.get(started["session_id"])["status"] == "recording"
    return manager, started["session_id"]


def test_overlapping_trigger_windows_merge_into_one_candidate(tmp_path):
    manager, session_id = _recording_manager(tmp_path)
    first_time = datetime.now(timezone.utc) + timedelta(seconds=5)

    first = manager.trigger(
        provider="twitch",
        stream_id="merge-channel",
        triggered_at=first_time,
        pre_seconds=20,
        post_seconds=20,
        reason="phrase",
    )
    second = manager.trigger(
        provider="twitch",
        stream_id="merge-channel",
        triggered_at=first_time + timedelta(seconds=30),
        pre_seconds=20,
        post_seconds=20,
        reason="chat_volume",
    )

    assert second["candidate_id"] == first["candidate_id"]
    assert second["trigger_count"] == 2
    assert second["pre_seconds"] == 20
    assert second["post_seconds"] == 50
    assert len(manager.list_candidates(session_id)) == 1

    assert asyncio.run(manager.stop(session_id)) is True
    candidate_worker = manager._candidates[first["candidate_id"]].worker
    candidate_worker.join(timeout=2)
    assert not candidate_worker.is_alive()


def test_disjoint_trigger_windows_remain_separate_candidates(tmp_path):
    manager, session_id = _recording_manager(tmp_path)
    first_time = datetime.now(timezone.utc) + timedelta(seconds=5)

    first = manager.trigger(
        provider="twitch",
        stream_id="merge-channel",
        triggered_at=first_time,
        pre_seconds=10,
        post_seconds=10,
    )
    second = manager.trigger(
        provider="twitch",
        stream_id="merge-channel",
        triggered_at=first_time + timedelta(seconds=30),
        pre_seconds=10,
        post_seconds=10,
    )

    assert second["candidate_id"] != first["candidate_id"]
    assert len(manager.list_candidates(session_id)) == 2

    assert asyncio.run(manager.stop(session_id)) is True
    for candidate in manager._candidates.values():
        if candidate.capture_session_id == session_id and candidate.worker:
            candidate.worker.join(timeout=2)


def test_overlapping_trigger_union_is_bounded_by_capture_retention(tmp_path):
    manager, session_id = _recording_manager(tmp_path)
    first_time = datetime.now(timezone.utc) + timedelta(seconds=5)

    first = manager.trigger(
        provider="twitch",
        stream_id="merge-channel",
        triggered_at=first_time,
        pre_seconds=60,
        post_seconds=60,
    )
    second = manager.trigger(
        provider="twitch",
        stream_id="merge-channel",
        triggered_at=first_time + timedelta(seconds=80),
        pre_seconds=60,
        post_seconds=60,
    )

    assert second["candidate_id"] != first["candidate_id"]
    assert len(manager.list_candidates(session_id)) == 2

    assert asyncio.run(manager.stop(session_id)) is True
    for candidate in manager._candidates.values():
        if candidate.capture_session_id == session_id and candidate.worker:
            candidate.worker.join(timeout=2)

def test_merged_window_selects_and_assembles_exact_union_once_and_seals(tmp_path, monkeypatch):
    import os

    origin = datetime.now(timezone.utc) - timedelta(seconds=8)
    records = []
    for index, end_offset in enumerate((0, 4, 8, 12)):
        path = tmp_path / f"merge-segment-{index:02d}.ts"
        path.write_bytes(b"mpeg-ts")
        end_time = origin + timedelta(seconds=end_offset)
        os.utime(path, (end_time.timestamp(), end_time.timestamp()))
        records.append(SegmentRecord(path.resolve(), 0, 4))

    class IndexedCapture:
        def __init__(self, _url, _config):
            self.protected = []
            self.released = []
            self.stop_requested = threading.Event()

        def run(self, _stop_event, *, on_started=None):
            if on_started:
                on_started()
            self.stop_requested.wait(5)

        def read_segment_index(self):
            return list(records)

        def protect_segments(self, paths):
            self.protected.extend(paths)
            return list(paths)

        def release_segments(self, paths):
            self.released.extend(paths)

        def request_stop(self):
            self.stop_requested.set()

    made = []

    def factory(url, config):
        capture = IndexedCapture(url, config)
        made.append(capture)
        return capture

    assembly_started = threading.Event()
    allow_assembly = threading.Event()
    assembled = []

    def assemble(selected, output_path, **_kwargs):
        assembled.append(list(selected))
        assembly_started.set()
        assert allow_assembly.wait(4), "test did not release the candidate assembler"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"merged candidate")
        return output_path

    monkeypatch.setattr("community_highlights.capture_sessions.assemble_segments", assemble)
    manager = CaptureSessionManager(capture_factory=factory, output_root=tmp_path / "captures")
    started = manager.start("https://www.twitch.tv/merge-e2e")
    session_id = started["session_id"]
    deadline = time.time() + 1
    while manager.get(session_id)["status"] != "recording" and time.time() < deadline:
        time.sleep(0.01)
    assert manager.get(session_id)["status"] == "recording"

    first = manager.trigger(
        provider="twitch",
        stream_id="merge-e2e",
        triggered_at=origin,
        pre_seconds=4,
        post_seconds=4,
        reason="phrase",
    )
    merged = manager.trigger(
        provider="twitch",
        stream_id="merge-e2e",
        triggered_at=origin + timedelta(seconds=6),
        pre_seconds=4,
        post_seconds=4,
        reason="chat_volume",
    )
    assert merged["candidate_id"] == first["candidate_id"]
    assert merged["trigger_count"] == 2

    # Expedite only this test's merge-grace boundary. Production still uses
    # the same locked capturing -> assembling transition.
    with manager._lock:
        manager._candidates[first["candidate_id"]].merge_until = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )

    assert assembly_started.wait(3), "merged candidate did not reach assembly"
    sealed = manager._candidates[first["candidate_id"]]
    assert sealed.status == "assembling"

    later = manager.trigger(
        provider="twitch",
        stream_id="merge-e2e",
        triggered_at=origin + timedelta(seconds=30),
        pre_seconds=0,
        post_seconds=0,
        reason="manual",
    )
    assert later["candidate_id"] != first["candidate_id"]
    assert sealed.trigger_count == 2

    allow_assembly.set()
    sealed.worker.join(timeout=3)
    assert not sealed.worker.is_alive()
    assert sealed.status == "ready"
    assert assembled == [records]
    assert made[0].protected == [record.path for record in records]
    assert made[0].released == [record.path for record in records]

    assert asyncio.run(manager.stop(session_id)) is True
    later_worker = manager._candidates[later["candidate_id"]].worker
    if later_worker:
        later_worker.join(timeout=3)

def test_candidate_is_not_ready_when_durable_ready_transition_fails(tmp_path, monkeypatch):
    import os

    class ReadyFailingStore:
        def __init__(self):
            self.state = {
                "trigger_settings": None,
                "capture_sessions": [],
                "candidates": [],
            }

        def read(self):
            return dict(self.state)

        def update_sections(self, **sections):
            candidates = sections.get("candidates")
            if candidates is not None and any(row.get("status") == "ready" for row in candidates):
                raise StateStoreError("disk unavailable")
            self.state.update(sections)

    stamp = time.time()
    segment = tmp_path / "ready-durability.ts"
    segment.write_bytes(b"mpeg-ts")
    os.utime(segment, (stamp, stamp))
    record = SegmentRecord(segment.resolve(), 0, 4)

    def factory(url, config):
        return FakeIndexedCapture(url, config, record)

    def assemble(_records, output_path, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"completed mp4")
        return output_path

    monkeypatch.setattr("community_highlights.capture_sessions.assemble_segments", assemble)
    store = ReadyFailingStore()
    manager = CaptureSessionManager(
        capture_factory=factory,
        output_root=tmp_path / "captures",
        state_store=store,
    )
    started = manager.start("https://www.twitch.tv/ready-durability")
    session_id = started["session_id"]
    deadline = time.time() + 1
    while manager.get(session_id)["status"] != "recording" and time.time() < deadline:
        time.sleep(0.01)

    candidate = manager.trigger(
        provider="twitch",
        stream_id="ready-durability",
        triggered_at=datetime.fromtimestamp(stamp, timezone.utc),
        pre_seconds=0,
        post_seconds=0,
        reason="manual",
    )
    candidate_id = candidate["candidate_id"]
    worker = manager._candidates[candidate_id].worker
    worker.join(timeout=3)

    snapshot, preview_path = manager.get_candidate(candidate_id)
    assert snapshot["status"] == "error"
    assert "could not save its ready status" in snapshot["error"]
    assert preview_path is None
    assert manager._candidates[candidate_id].output_path.is_file()
    assert store.state["candidates"][0]["status"] == "error"

    assert asyncio.run(manager.stop(session_id)) is True
