import io
import subprocess
import threading
from pathlib import Path

import pytest

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
    tmp_path.mkdir()
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

    class FakeStdin(io.BytesIO):
        pass

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
    assert process.stdin.getvalue() == b"onetwo"
    assert process.waited is True
    assert process.kwargs["shell"] is False


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
    tmp_path.mkdir()
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
