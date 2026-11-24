from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from community_highlights.extraction import assemble_segments
from community_highlights.rolling_capture import SegmentRecord, RollingCaptureError
from community_highlights.timeline import (
    segment_wall_interval,
    select_segments_for_window,
    validate_contiguous_window,
)


def make_record(path: Path, start: float, end: float, wall_end: float) -> SegmentRecord:
    path.write_bytes(b"ts")
    import os
    os.utime(path, (wall_end, wall_end))
    return SegmentRecord(path.resolve(), start, end)


def test_selects_segments_overlapping_pre_and_post_trigger_window(tmp_path):
    trigger = datetime.fromtimestamp(1_000, timezone.utc)
    records = [
        make_record(tmp_path / "s0.ts", 0, 4, 984),
        make_record(tmp_path / "s1.ts", 4, 8, 988),
        make_record(tmp_path / "s2.ts", 8, 12, 992),
        make_record(tmp_path / "s3.ts", 12, 16, 996),
        make_record(tmp_path / "s4.ts", 16, 20, 1_000),
        make_record(tmp_path / "s5.ts", 20, 24, 1_004),
    ]

    selected = select_segments_for_window(
        records, triggered_at=trigger, pre_seconds=10, post_seconds=3
    )

    assert [item.path.name for item in selected] == ["s2.ts", "s3.ts", "s4.ts", "s5.ts"]


def test_segment_wall_interval_uses_file_mtime_and_media_duration(tmp_path):
    record = make_record(tmp_path / "segment.ts", 4, 8, 1000)
    start, end = segment_wall_interval(record)
    assert start.timestamp() == pytest.approx(996)
    assert end.timestamp() == pytest.approx(1000)


def test_rejects_naive_trigger_and_negative_windows(tmp_path):
    record = make_record(tmp_path / "segment.ts", 0, 4, 1000)
    with pytest.raises(ValueError, match="timezone-aware"):
        select_segments_for_window([record], triggered_at=datetime.now(), pre_seconds=1, post_seconds=1)
    with pytest.raises(ValueError, match="cannot be negative"):
        select_segments_for_window([record], triggered_at=datetime.now(timezone.utc), pre_seconds=-1, post_seconds=1)


def test_validates_window_coverage_and_gaps(tmp_path):
    trigger = datetime.fromtimestamp(1000, timezone.utc)
    complete = [
        make_record(tmp_path / "a.ts", 0, 4, 996),
        make_record(tmp_path / "b.ts", 4, 8, 1000),
        make_record(tmp_path / "c.ts", 8, 12, 1004),
    ]
    validate_contiguous_window(complete, triggered_at=trigger, pre_seconds=4, post_seconds=4)

    with pytest.raises(ValueError, match="full pre-trigger"):
        validate_contiguous_window(complete[2:], triggered_at=trigger, pre_seconds=4, post_seconds=4)


def test_assembles_selected_segments_without_reencoding(tmp_path):
    first = make_record(tmp_path / "a.ts", 0, 4, 1000)
    second = make_record(tmp_path / "b.ts", 4, 8, 1004)
    output = tmp_path / "highlights" / "candidate.mp4"
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        output.write_bytes(b"assembled")
        return SimpleNamespace(returncode=0)

    result = assemble_segments([first, second], output, runner=runner)
    args, kwargs = calls[0]
    assert result == output
    assert output.read_bytes() == b"assembled"
    assert args[args.index("-c") + 1] == "copy"
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 120


def test_assembly_rejects_mixed_capture_directories_and_non_mp4_output(tmp_path):
    first = make_record(tmp_path / "a.ts", 0, 4, 1000)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    second = make_record(other_dir / "b.ts", 4, 8, 1004)
    with pytest.raises(RollingCaptureError, match="one capture directory"):
        assemble_segments([first, second], tmp_path / "candidate.mp4")
    with pytest.raises(RollingCaptureError, match=r"requires an \.mp4"):
        assemble_segments([first], tmp_path / "candidate.ts")
