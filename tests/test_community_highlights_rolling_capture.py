
import pytest
import threading
from pathlib import Path

from community_highlights.rolling_capture import (
    RollingCapture,
    RollingCaptureConfig,
    RollingCaptureError,
    build_ffmpeg_segment_args,
)


def config(tmp_path, **overrides):
    values = {
        "output_dir": tmp_path,
        "segment_seconds": 4,
        "retention_seconds": 40,
        "max_buffer_size_mb": 16,
        "quality": "best",
        "ffmpeg_path": "ffmpeg",
    }
    values.update(overrides)
    return RollingCaptureConfig(**values)


def test_builds_stream_copy_segment_command_without_shell(tmp_path):
    args = build_ffmpeg_segment_args(config(tmp_path))
    assert args[args.index("-i") + 1] == "pipe:0"
    assert args[args.index("-c") + 1] == "copy"
    assert args[args.index("-segment_time") + 1] == "4"
    assert args[args.index("-segment_list_type") + 1] == "csv"
    assert args[args.index("-segment_list_size") + 1] == "12"
    assert args[-1] == str(tmp_path / "segment-%08d.ts")


@pytest.mark.parametrize("kwargs", [
    {"segment_seconds": 0},
    {"segment_seconds": 61},
    {"retention_seconds": 4},
    {"max_buffer_size_mb": 1},
])
def test_rejects_invalid_capture_configuration(tmp_path, kwargs):
    with pytest.raises(ValueError):
        config(tmp_path, **kwargs).validate()


def test_prunes_oldest_segments_to_age_budget_but_keeps_newest(tmp_path):
    now = [1000.0]
    capture = RollingCapture(
        "https://twitch.tv/channel",
        config(tmp_path, retention_seconds=20),
        clock=lambda: now[0],
    )
    old = tmp_path / "segment-00000000.ts"
    recent = tmp_path / "segment-00000001.ts"
    newest = tmp_path / "segment-00000002.ts"
    for path in (old, recent, newest):
        path.write_bytes(b"segment")
    import os
    os.utime(old, (900, 900))
    os.utime(recent, (990, 990))
    os.utime(newest, (995, 995))

    capture._prune_segments()

    assert not old.exists()
    assert recent.exists()
    assert newest.exists()


def test_run_pipes_stream_and_finalizes_ffmpeg(tmp_path, monkeypatch):
    class FakeReader:
        def __init__(self):
            self.chunks = iter([b"one", b"two", b""])

        def read(self, _size):
            return next(self.chunks)

        def close(self):
            self.closed = True

    class FakeStream:
        def __init__(self):
            self.reader = FakeReader()

        def open(self):
            return self.reader

        def close(self):
            self.closed = True

    class FakeResolved:
        def __init__(self):
            self.stream = FakeStream()
            self.quality = "best"

        def open(self):
            return self.stream.open()

    class FakeStdin:
        def __init__(self):
            self.data = bytearray()
            self.closed = False

        def write(self, chunk):
            accepted = bytes(chunk[:2])
            self.data.extend(accepted)
            return len(accepted)

        def close(self):
            self.closed = True

    class FakeProcess:
        def __init__(self, *_args, **kwargs):
            self.stdin = FakeStdin()
            self.returncode = None
            self.kwargs = kwargs
            self.waited = False

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.waited = True
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    process = FakeProcess()
    opened = []

    def resolver(url, quality):
        opened.append((url, quality))
        return FakeResolved()

    def popen(*args, **kwargs):
        opened.append((args, kwargs))
        return process

    monkeypatch.setattr("community_highlights.rolling_capture.shutil.which", lambda _name: "C:/ffmpeg.exe")
    capture = RollingCapture(
        "https://twitch.tv/channel",
        config(tmp_path),
        resolver=resolver,
        popen=popen,
    )
    capture.run()

    assert opened[0] == ("https://twitch.tv/channel", "best")
    assert bytes(process.stdin.data) == b"onetwo"
    assert process.stdin.closed is True
    assert process.waited is True
    assert opened[1][1]["shell"] is False


def test_run_reports_missing_ffmpeg(tmp_path, monkeypatch):
    class Reader:
        def read(self, _size):
            return b""

        def close(self):
            pass

    class Resolved:
        stream = object()

        def open(self):
            return Reader()

    monkeypatch.setattr("community_highlights.rolling_capture.shutil.which", lambda _name: None)
    capture = RollingCapture(
        "https://twitch.tv/channel",
        config(tmp_path),
        resolver=lambda *_args, **_kwargs: Resolved(),
    )
    with pytest.raises(RollingCaptureError, match="FFmpeg was not found"):
        capture.run()

def test_protected_segments_are_not_pruned_until_released(tmp_path):
    now = [1000.0]
    capture = RollingCapture(
        "https://twitch.tv/channel",
        config(tmp_path, retention_seconds=20),
        clock=lambda: now[0],
    )
    pinned = tmp_path / "segment-00000000.ts"
    newest = tmp_path / "segment-00000001.ts"
    pinned.write_bytes(b"pinned")
    newest.write_bytes(b"newest")
    import os
    os.utime(pinned, (900, 900))
    os.utime(newest, (995, 995))

    protected = capture.protect_segments([pinned])
    capture._prune_segments()
    assert pinned.exists()

    capture.release_segments(protected)
    capture._prune_segments()
    assert not pinned.exists()

def test_write_all_handles_partial_pipe_writes():
    class PartialPipe:
        def __init__(self):
            self.data = bytearray()

        def write(self, chunk):
            accepted = bytes(chunk[:1])
            self.data.extend(accepted)
            return len(accepted)

    pipe = PartialPipe()
    RollingCapture._write_all(pipe, b"partial-write")
    assert bytes(pipe.data) == b"partial-write"


def test_write_all_reports_closed_pipe():
    class ClosedPipe:
        def write(self, _chunk):
            return 0

    with pytest.raises(RollingCaptureError, match="stopped accepting"):
        RollingCapture._write_all(ClosedPipe(), b"data")

def test_reads_only_existing_safe_segment_index_entries(tmp_path):
    capture = RollingCapture(
        "https://twitch.tv/channel",
        config(tmp_path),
    )
    first = tmp_path / "segment-00000000.ts"
    second = tmp_path / "segment-00000001.ts"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    outside = tmp_path.parent / "outside.ts"
    outside.write_bytes(b"outside")
    (tmp_path / "segments.csv").write_text(
        "segment-00000000.ts,0.0,4.0\n"
        "segment-00000001.ts,4.0,8.0\n"
        "../outside.ts,8.0,12.0\n"
        "segment-00000000.ts,nan,16.0\n"
        "partial-row\n",
        encoding="utf-8",
    )

    records = capture.read_segment_index()

    assert [(r.path, r.start_seconds, r.end_seconds) for r in records] == [
        (first.resolve(), 0.0, 4.0),
        (second.resolve(), 4.0, 8.0),
    ]
    outside.unlink()


def test_segment_index_ignores_files_removed_by_retention(tmp_path):
    capture = RollingCapture("https://twitch.tv/channel", config(tmp_path))
    (tmp_path / "segments.csv").write_text(
        "segment-00000000.ts,0.0,4.0\n",
        encoding="utf-8",
    )
    assert capture.read_segment_index() == []

def test_protected_segments_cannot_exceed_storage_budget(tmp_path):
    capture = RollingCapture("https://twitch.tv/channel", config(tmp_path))
    oversized = tmp_path / "segment-00000000.ts"
    with oversized.open("wb") as handle:
        handle.truncate(16 * 1024 * 1024 + 1)

    with pytest.raises(RollingCaptureError, match="storage budget"):
        capture.protect_segments([oversized])

def test_pruning_serializes_with_concurrent_segment_pinning(tmp_path, monkeypatch):
    now = [1000.0]
    capture = RollingCapture(
        "https://twitch.tv/channel",
        config(tmp_path, retention_seconds=20),
        clock=lambda: now[0],
    )
    stale = tmp_path / "segment-00000000.ts"
    newest = tmp_path / "segment-00000001.ts"
    stale.write_bytes(b"stale")
    newest.write_bytes(b"newest")
    import os
    os.utime(stale, (900, 900))
    os.utime(newest, (995, 995))

    unlink_started = threading.Event()
    allow_unlink = threading.Event()
    pin_finished = threading.Event()
    pin_result = []
    original_unlink = Path.unlink

    def blocked_unlink(path, *args, **kwargs):
        if path == stale:
            unlink_started.set()
            assert allow_unlink.wait(timeout=2)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", blocked_unlink)
    prune_worker = threading.Thread(target=capture._prune_segments)
    prune_worker.start()
    assert unlink_started.wait(timeout=1)

    def pin():
        pin_result.extend(capture.protect_segments([stale]))
        pin_finished.set()

    pin_worker = threading.Thread(target=pin)
    pin_worker.start()
    # protect_segments must wait for the in-progress prune decision. It cannot
    # report a segment as protected after prune has already committed to unlink it.
    assert not pin_finished.wait(timeout=0.05)

    allow_unlink.set()
    prune_worker.join(timeout=2)
    pin_worker.join(timeout=2)

    assert not prune_worker.is_alive()
    assert not pin_worker.is_alive()
    assert not stale.exists()
    assert pin_result == []
