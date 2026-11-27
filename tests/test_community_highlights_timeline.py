from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from community_highlights.extraction import assemble_segments
from community_highlights.rolling_capture import SegmentRecord, RollingCaptureError
from community_highlights.timeline import (
    segment_wall_interval,
    select_segments_for_interval,
    validate_contiguous_interval,
)


def make_record(path: Path, start: float, end: float, wall_end: float) -> SegmentRecord:
    path.write_bytes(b"ts")
    import os
    os.utime(path, (wall_end, wall_end))
    return SegmentRecord(path.resolve(), start, end)


def test_selects_segments_overlapping_exact_utc_interval(tmp_path):
    records = [
        make_record(tmp_path / "s0.ts", 0, 4, 984),
        make_record(tmp_path / "s1.ts", 4, 8, 988),
        make_record(tmp_path / "s2.ts", 8, 12, 992),
        make_record(tmp_path / "s3.ts", 12, 16, 996),
        make_record(tmp_path / "s4.ts", 16, 20, 1_000),
        make_record(tmp_path / "s5.ts", 20, 24, 1_004),
    ]

    selected = select_segments_for_interval(
        records,
        window_start=datetime.fromtimestamp(990, timezone.utc),
        window_end=datetime.fromtimestamp(1_003, timezone.utc),
    )

    assert [item.path.name for item in selected] == ["s2.ts", "s3.ts", "s4.ts", "s5.ts"]


def test_interval_selection_rejects_naive_boundaries(tmp_path):
    record = make_record(tmp_path / "segment.ts", 0, 4, 1000)
    with pytest.raises(ValueError, match="window_start must be timezone-aware"):
        select_segments_for_interval(
            [record],
            window_start=datetime.now(),
            window_end=datetime.now(timezone.utc),
        )


def test_segment_wall_interval_uses_file_mtime_and_media_duration(tmp_path):
    record = make_record(tmp_path / "segment.ts", 4, 8, 1000)
    start, end = segment_wall_interval(record)
    assert start.timestamp() == pytest.approx(996)
    assert end.timestamp() == pytest.approx(1000)


def test_validates_exact_interval_coverage(tmp_path):
    complete = [
        make_record(tmp_path / "a.ts", 0, 4, 996),
        make_record(tmp_path / "b.ts", 4, 8, 1000),
        make_record(tmp_path / "c.ts", 8, 12, 1004),
    ]
    window_start = datetime.fromtimestamp(996, timezone.utc)
    window_end = datetime.fromtimestamp(1004, timezone.utc)
    validate_contiguous_interval(
        complete, window_start=window_start, window_end=window_end
    )

    with pytest.raises(ValueError, match="full pre-trigger"):
        validate_contiguous_interval(
            complete[2:], window_start=window_start, window_end=window_end
        )


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



def test_selects_and_validates_exact_merged_interval(tmp_path):
    start = datetime.fromtimestamp(1000, timezone.utc)
    end = datetime.fromtimestamp(1012, timezone.utc)
    records = [
        make_record(tmp_path / "before.ts", 0, 4, 999),
        make_record(tmp_path / "inside-a.ts", 4, 8, 1004),
        make_record(tmp_path / "inside-b.ts", 8, 12, 1008),
        make_record(tmp_path / "inside-c.ts", 12, 16, 1012),
        make_record(tmp_path / "after.ts", 16, 20, 1017),
    ]

    selected = select_segments_for_interval(
        records, window_start=start, window_end=end
    )
    assert [item.path.name for item in selected] == [
        "inside-a.ts", "inside-b.ts", "inside-c.ts"
    ]
    validate_contiguous_interval(
        selected, window_start=start, window_end=end
    )

    with pytest.raises(ValueError, match="window_end must not precede"):
        select_segments_for_interval(
            records, window_start=end, window_end=start
        )



def test_contiguous_pts_segments_do_not_appear_gapped_when_one_file_mtime_jitters(tmp_path):
    records = [
        make_record(tmp_path / "a.ts", 0, 4, 1004),
        make_record(tmp_path / "b.ts", 4, 8, 1012),
        make_record(tmp_path / "c.ts", 8, 12, 1012),
    ]

    selected = select_segments_for_interval(
        records,
        window_start=datetime.fromtimestamp(1000, timezone.utc),
        window_end=datetime.fromtimestamp(1012, timezone.utc),
    )

    assert [item.path.name for item in selected] == ["a.ts", "b.ts", "c.ts"]
    validate_contiguous_interval(
        selected,
        window_start=datetime.fromtimestamp(1000, timezone.utc),
        window_end=datetime.fromtimestamp(1012, timezone.utc),
    )


def test_real_pts_discontinuity_is_still_rejected_despite_smooth_file_mtimes(tmp_path):
    records = [
        make_record(tmp_path / "a.ts", 0, 4, 1004),
        make_record(tmp_path / "b.ts", 8, 12, 1012),
    ]

    with pytest.raises(ValueError, match="recording gap"):
        validate_contiguous_interval(
            records,
            window_start=datetime.fromtimestamp(1000, timezone.utc),
            window_end=datetime.fromtimestamp(1012, timezone.utc),
        )



def test_interval_selection_excludes_segments_that_only_touch_window_edges(tmp_path):
    records = [
        make_record(tmp_path / "before.ts", 0, 4, 1004),
        make_record(tmp_path / "inside.ts", 4, 8, 1008),
        make_record(tmp_path / "after.ts", 8, 12, 1012),
    ]

    selected = select_segments_for_interval(
        records,
        window_start=datetime.fromtimestamp(1004, timezone.utc),
        window_end=datetime.fromtimestamp(1008, timezone.utc),
    )

    assert [item.path.name for item in selected] == ["inside.ts"]


def test_zero_length_window_still_selects_the_segment_covering_its_timestamp(tmp_path):
    record = make_record(tmp_path / "point.ts", 0, 4, 1004)

    selected = select_segments_for_interval(
        [record],
        window_start=datetime.fromtimestamp(1002, timezone.utc),
        window_end=datetime.fromtimestamp(1002, timezone.utc),
    )

    assert selected == [record]
