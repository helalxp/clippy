from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from community_highlights.extraction import assemble_segments, probe_media_duration_seconds
from community_highlights.rolling_capture import RollingCaptureError, SegmentRecord


def _records(tmp_path):
    first = tmp_path / "segment-00000000.ts"
    second = tmp_path / "segment-00000001.ts"
    first.write_bytes(b"segment-one")
    second.write_bytes(b"segment-two")
    return [
        SegmentRecord(first.resolve(), 0.0, 4.0),
        SegmentRecord(second.resolve(), 4.0, 8.0),
    ]


def test_assembles_single_browser_preview_mp4_without_reencoding(tmp_path):
    records = _records(tmp_path)
    output = tmp_path / "highlights" / "candidate.mp4"
    invocation = {}

    def runner(args, **kwargs):
        invocation["args"] = args
        invocation["kwargs"] = kwargs
        Path(args[-1]).write_bytes(b"mp4")
        invocation["manifest"] = Path(args[args.index("-i") + 1]).read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0)

    result = assemble_segments(records, output, runner=runner)

    assert result == output
    assert result.read_bytes() == b"mp4"
    args = invocation["args"]
    assert args.count("-map") == 2
    mappings = [args[index + 1] for index, value in enumerate(args[:-1]) if value == "-map"]
    assert mappings == ["0:v?", "0:a?"]
    assert args[args.index("-c") + 1] == "copy"
    assert args[args.index("-movflags") + 1] == "+faststart"
    assert args[-4:-2] == ["-f", "mp4"]
    assert "segment-00000000.ts" in invocation["manifest"]
    assert "segment-00000001.ts" in invocation["manifest"]
    assert invocation["kwargs"]["shell"] is False
    assert invocation["kwargs"]["stdin"] == subprocess.DEVNULL
    assert invocation["kwargs"]["stderr"] == subprocess.PIPE
    assert not list(output.parent.glob("*.ffconcat"))


def test_failed_mp4_assembly_removes_partial_candidate(tmp_path):
    records = _records(tmp_path)
    output = tmp_path / "candidate.mp4"

    def runner(args, **_kwargs):
        Path(args[-1]).write_bytes(b"partial")
        return SimpleNamespace(returncode=1)

    with pytest.raises(RollingCaptureError, match="browser-playable MP4"):
        assemble_segments(records, output, runner=runner)
    assert not output.exists()


def test_failed_assembly_logs_a_redacted_ffmpeg_diagnostic(tmp_path, caplog):
    records = _records(tmp_path)
    output = tmp_path / "candidate.mp4"
    private_url = "https://viewer:password@example.test/live?access_token=do-not-log"
    private_path = "C:\\Users\\private\\candidate.ts"

    def runner(_args, **_kwargs):
        return SimpleNamespace(
            returncode=1,
            stderr=(
                f"Invalid data found when processing input from {private_url}\n"
                f"Error opening {private_path}\n"
            ).encode(),
        )

    with caplog.at_level(40, logger="clippy.community_highlights"):
        with pytest.raises(RollingCaptureError, match="browser-playable MP4"):
            assemble_segments(records, output, runner=runner)

    assert '"failure_code":"invalid_data"' in caplog.text
    assert "Invalid data found" in caplog.text
    assert "do-not-log" not in caplog.text
    assert "viewer:password@" not in caplog.text
    assert "C:\\Users" not in caplog.text
    assert not output.exists()


def test_successful_ffmpeg_exit_without_output_is_classified(tmp_path, caplog):
    records = _records(tmp_path)
    output = tmp_path / "candidate.mp4"

    def runner(_args, **_kwargs):
        return SimpleNamespace(returncode=0, stderr=b"")

    with caplog.at_level(40, logger="clippy.community_highlights"):
        with pytest.raises(RollingCaptureError, match="browser-playable MP4"):
            assemble_segments(records, output, runner=runner)

    assert '"failure_code":"output_missing"' in caplog.text
    assert not output.exists()


def test_assembly_rejects_non_mp4_output_and_duplicate_or_external_segments(tmp_path):
    records = _records(tmp_path)
    with pytest.raises(RollingCaptureError, match="requires an .mp4"):
        assemble_segments(records, tmp_path / "candidate.ts", runner=lambda *_a, **_k: None)

    duplicate = [records[0], records[0]]
    with pytest.raises(RollingCaptureError, match="duplicates"):
        assemble_segments(duplicate, tmp_path / "duplicate.mp4", runner=lambda *_a, **_k: None)



def test_probe_media_duration_returns_finite_positive_seconds(tmp_path):
    media = tmp_path / "candidate.mp4"
    media.write_bytes(b"assembled")
    invocation = {}

    def runner(args, **kwargs):
        invocation["args"] = args
        invocation["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"63.250\n")

    duration = probe_media_duration_seconds(
        media,
        ffmpeg_path="ffmpeg",
        runner=runner,
    )

    assert duration == pytest.approx(63.25)
    assert invocation["args"][1:8] == [
        "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(media)
    ]
    assert invocation["kwargs"]["shell"] is False
    assert invocation["kwargs"]["stdin"] == subprocess.DEVNULL
    assert invocation["kwargs"]["timeout"] == 15
    assert invocation["kwargs"]["check"] is False


@pytest.mark.parametrize("stdout", [b"", b"N/A", b"nan", b"inf", b"-4"])
def test_probe_media_duration_returns_none_for_invalid_duration(tmp_path, stdout):
    media = tmp_path / "candidate.mp4"
    media.write_bytes(b"assembled")

    result = probe_media_duration_seconds(
        media,
        runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=stdout),
    )

    assert result is None


def test_probe_media_duration_fails_open_when_probe_is_unavailable(tmp_path):
    media = tmp_path / "candidate.mp4"
    media.write_bytes(b"assembled")

    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError("ffprobe missing")

    assert probe_media_duration_seconds(media, runner=unavailable) is None
