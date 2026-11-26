"""Wall-clock selection of completed rolling segments for highlight windows.

FFmpeg's segment CSV contains media PTS, not UTC. For the first extraction
iteration, completed segment file mtimes provide a host-clock end-time estimate;
the media duration in the CSV estimates each segment's start. Selection is
therefore bounded to completed segments and may trim at segment/keyframe edges.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from .rolling_capture import SegmentRecord


def segment_wall_interval(record: SegmentRecord) -> tuple[datetime, datetime]:
    """Estimate a completed segment's wall interval from its file mtime and PTS duration."""
    duration = record.end_seconds - record.start_seconds
    if duration <= 0:
        raise ValueError("Segment duration must be positive.")
    end = datetime.fromtimestamp(record.path.stat().st_mtime, tz=timezone.utc)
    return end - timedelta(seconds=duration), end


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
    for record in records:
        try:
            segment_start, segment_end = segment_wall_interval(record)
        except (OSError, ValueError):
            continue
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

    intervals = [segment_wall_interval(record) for record in records]
    intervals.sort(key=lambda item: item[0])
    tolerance = timedelta(seconds=max_gap_seconds)
    if intervals[0][0] - start_utc > tolerance:
        raise ValueError("The rolling buffer does not contain the full pre-trigger window yet.")
    if end_utc - intervals[-1][1] > tolerance:
        raise ValueError("The requested post-trigger footage has not finished recording yet.")
    for previous, current in zip(intervals, intervals[1:]):
        if current[0] - previous[1] > tolerance:
            raise ValueError("The selected rolling segments contain a recording gap.")
