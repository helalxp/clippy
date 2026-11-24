from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from community_highlights.extraction import assemble_segments
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


def test_assembly_rejects_non_mp4_output_and_duplicate_or_external_segments(tmp_path):
    records = _records(tmp_path)
    with pytest.raises(RollingCaptureError, match="requires an .mp4"):
        assemble_segments(records, tmp_path / "candidate.ts", runner=lambda *_a, **_k: None)

    duplicate = [records[0], records[0]]
    with pytest.raises(RollingCaptureError, match="duplicates"):
        assemble_segments(duplicate, tmp_path / "duplicate.mp4", runner=lambda *_a, **_k: None)
