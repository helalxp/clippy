"""Wall-clock selection of completed rolling segments for highlight windows.

FFmpeg's segment CSV contains media PTS, not UTC. For the first extraction
iteration, completed segment file mtimes provide a host-clock end-time estimate;
the media duration in the CSV estimates each segment's start. Selection is
therefore bounded to completed segments and may trim at segment/keyframe edges.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .rolling_capture import SegmentRecord


def segment_wall_interval(record: SegmentRecord) -> tuple[datetime, datetime]:
    """Estimate a completed segment's wall interval from its file mtime and PTS duration."""
    duration = record.end_seconds - record.start_seconds
    if duration <= 0:
        raise ValueError("Segment duration must be positive.")
    end = datetime.fromtimestamp(record.path.stat().st_mtime, tz=timezone.utc)
    return end - timedelta(seconds=duration), end


def select_segments_for_window(
    records: Iterable[SegmentRecord],
    *,
    triggered_at: datetime,
    pre_seconds: float,
    post_seconds: float,
) -> list[SegmentRecord]:
    """Select completed segments overlapping [trigger-pre, trigger+post]."""
    if triggered_at.tzinfo is None or triggered_at.utcoffset() is None:
        raise ValueError("triggered_at must be timezone-aware.")
    if pre_seconds < 0 or post_seconds < 0:
        raise ValueError("Pre-trigger and post-trigger durations cannot be negative.")
    trigger_utc = triggered_at.astimezone(timezone.utc)
    window_start = trigger_utc - timedelta(seconds=pre_seconds)
    window_end = trigger_utc + timedelta(seconds=post_seconds)
    selected: list[tuple[datetime, SegmentRecord]] = []
    for record in records:
        try:
            segment_start, segment_end = segment_wall_interval(record)
        except (OSError, ValueError):
            continue
        if segment_start <= window_end and segment_end >= window_start:
            selected.append((segment_start, record))
    selected.sort(key=lambda item: (item[0], item[1].start_seconds))
    return [record for _, record in selected]


def validate_contiguous_window(
    records: list[SegmentRecord],
    *,
    triggered_at: datetime,
    pre_seconds: float,
    post_seconds: float,
    max_gap_seconds: float = 2.0,
) -> None:
    """Reject obviously incomplete windows instead of silently creating a broken clip."""
    if triggered_at.tzinfo is None or triggered_at.utcoffset() is None:
        raise ValueError("triggered_at must be timezone-aware.")
    if not records:
        raise ValueError("No completed segments overlap the requested highlight window.")
    if max_gap_seconds < 0:
        raise ValueError("max_gap_seconds cannot be negative.")
    intervals = [segment_wall_interval(record) for record in records]
    intervals.sort(key=lambda item: item[0])
    trigger = triggered_at.astimezone(timezone.utc)
    requested_start = trigger - timedelta(seconds=pre_seconds)
    requested_end = trigger + timedelta(seconds=post_seconds)
    if intervals[0][0] - requested_start > timedelta(seconds=max_gap_seconds):
        raise ValueError("The rolling buffer does not contain the full pre-trigger window yet.")
    if requested_end - intervals[-1][1] > timedelta(seconds=max_gap_seconds):
        raise ValueError("The requested post-trigger footage has not finished recording yet.")
    for previous, current in zip(intervals, intervals[1:]):
        if current[0] - previous[1] > timedelta(seconds=max_gap_seconds):
            raise ValueError("The selected rolling segments contain a recording gap.")
