"""Wall-clock selection of completed rolling segments for highlight windows.

FFmpeg's segment CSV contains media PTS, not UTC. Completed segment file mtimes
provide a host-clock anchor, but their individual close times can jitter. The
capture's PTS intervals are therefore mapped with one median mtime/PTS offset.
This reduces artificial inter-segment gaps without claiming frame-accurate
wall-clock alignment; extraction still selects whole completed TS segments.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable

from .rolling_capture import SegmentRecord


def segment_wall_intervals(
    records: Iterable[SegmentRecord],
) -> list[tuple[SegmentRecord, datetime, datetime]]:
    """Map one capture's PTS intervals to wall time using a shared mtime anchor.

    Each completed TS file's mtime can vary slightly from its actual segment end.
    Estimating every segment independently turns that variation into artificial
    gaps. A median offset from the segment PTS end times gives the capture one
    stable wall-clock mapping while preserving real discontinuities in PTS.
    """
    valid: list[tuple[SegmentRecord, float]] = []
    offsets: list[float] = []
    for record in records:
        if record.end_seconds <= record.start_seconds:
            continue
        try:
            modified_at = record.path.stat().st_mtime
        except OSError:
            continue
        valid.append((record, modified_at))
        offsets.append(modified_at - record.end_seconds)

    if not valid:
        return []

    wall_offset = median(offsets)
    return [
        (
            record,
            datetime.fromtimestamp(wall_offset + record.start_seconds, tz=timezone.utc),
            datetime.fromtimestamp(wall_offset + record.end_seconds, tz=timezone.utc),
        )
        for record, _modified_at in valid
    ]


def segment_wall_interval(record: SegmentRecord) -> tuple[datetime, datetime]:
    """Estimate one segment interval using its mtime as a single-record anchor."""
    intervals = segment_wall_intervals([record])
    if not intervals:
        record.path.stat()
        raise ValueError("Segment duration must be positive.")
    _record, start, end = intervals[0]
    return start, end


def select_segments_for_interval(
    records: Iterable[SegmentRecord],
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[SegmentRecord]:
    """Select completed segments overlapping one exact UTC wall-clock interval."""
    if window_start.tzinfo is None or window_start.utcoffset() is None:
        raise ValueError("window_start must be timezone-aware.")
    if window_end.tzinfo is None or window_end.utcoffset() is None:
        raise ValueError("window_end must be timezone-aware.")
    start_utc = window_start.astimezone(timezone.utc)
    end_utc = window_end.astimezone(timezone.utc)
    if end_utc < start_utc:
        raise ValueError("window_end must not precede window_start.")

    selected: list[tuple[datetime, SegmentRecord]] = []
    for record, segment_start, segment_end in segment_wall_intervals(records):
        if segment_start <= end_utc and segment_end >= start_utc:
            selected.append((segment_start, record))
    selected.sort(key=lambda item: (item[0], item[1].start_seconds))
    return [record for _, record in selected]


def validate_contiguous_interval(
    records: list[SegmentRecord],
    *,
    window_start: datetime,
    window_end: datetime,
    max_gap_seconds: float = 2.0,
) -> None:
    """Reject missing coverage or discontinuities for an exact requested interval."""
    if window_start.tzinfo is None or window_start.utcoffset() is None:
        raise ValueError("window_start must be timezone-aware.")
    if window_end.tzinfo is None or window_end.utcoffset() is None:
        raise ValueError("window_end must be timezone-aware.")
    start_utc = window_start.astimezone(timezone.utc)
    end_utc = window_end.astimezone(timezone.utc)
    if end_utc < start_utc:
        raise ValueError("window_end must not precede window_start.")
    if not records:
        raise ValueError("No completed segments overlap the requested highlight window.")
    if max_gap_seconds < 0:
        raise ValueError("max_gap_seconds cannot be negative.")

    intervals = [
        (start, end)
        for _record, start, end in segment_wall_intervals(records)
    ]
    intervals.sort(key=lambda item: item[0])
    tolerance = timedelta(seconds=max_gap_seconds)
    if intervals[0][0] - start_utc > tolerance:
        raise ValueError("The rolling buffer does not contain the full pre-trigger window yet.")
    if end_utc - intervals[-1][1] > tolerance:
        raise ValueError("The requested post-trigger footage has not finished recording yet.")
    for previous, current in zip(intervals, intervals[1:]):
        if current[0] - previous[1] > tolerance:
            raise ValueError("The selected rolling segments contain a recording gap.")
