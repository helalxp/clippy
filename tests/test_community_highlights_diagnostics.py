import io
import logging

from community_highlights.diagnostics import (
    BoundedStderrTail,
    log_event,
    summarize_ffmpeg_stderr,
)


def test_ffmpeg_summary_classifies_timestamps_and_redacts_private_values():
    stderr = (
        b"Non-monotonous DTS in output stream 0:0; previous: 4, current: 3\n"
        b"Opening https://viewer:password@example.test/live?access_token=secret\n"
        b"Error reading C:\\Users\\private\\candidate.ts\n"
        b"Error reading C:/Users/private/candidate-forward-slash.ts\n"
        b"candidate id 12345678-1234-1234-1234-123456789abc\n"
    )

    fields = summarize_ffmpeg_stderr(stderr)

    assert fields["failure_code"] == "timestamp_error"
    assert "Non-monotonous DTS" in fields["ffmpeg_detail"]
    for private_value in ("viewer:password", "access_token", "secret", "C:\\Users", "C:/Users", "12345678-1234"):
        assert private_value not in fields["ffmpeg_detail"]


def test_stderr_capture_retains_only_a_bounded_tail():
    stream = io.BytesIO(b"x" * 200 + b"Invalid data found when processing input")
    capture = BoundedStderrTail(stream, max_bytes=64)

    fields = capture.diagnostic_fields()

    assert fields["failure_code"] == "invalid_data"
    assert len(fields["ffmpeg_detail"]) <= 64


def test_log_event_rejects_arbitrary_failure_codes_and_sanitizes_ffmpeg_detail(caplog):
    with caplog.at_level(logging.INFO, logger="clippy.community_highlights"):
        log_event(
            "capture.test",
            failure_code="private user-provided failure",
            ffmpeg_detail="Error opening https://example.test/path?token=private",
        )

    assert "private user-provided failure" not in caplog.text
    assert "token=private" not in caplog.text
    assert "https://example.test" not in caplog.text
    assert '"failure_code"' not in caplog.text
    assert "[url]" in caplog.text
