from __future__ import annotations

import hashlib

import pytest

from template_system.analysis import ReferenceAnalysisCancelled, ReferenceAnalysisError
from template_system.ingest import (
    StagedReference,
    cleanup_staged_reference,
    stage_reference_video,
)


def test_stage_reference_copies_source_and_fingerprints_bytes(tmp_path):
    source = tmp_path / "original.mp4"
    source.write_bytes(b"reference-video")
    staging = tmp_path / "staging"

    staged = stage_reference_video(source, staging)

    assert staged.id.startswith("ref_")
    assert staged.original_name == "original.mp4"
    assert staged.path.name == "source.mp4"
    assert staged.path.read_bytes() == b"reference-video"
    assert staged.size_bytes == len(b"reference-video")
    assert staged.sha256 == hashlib.sha256(b"reference-video").hexdigest()
    assert source.read_bytes() == b"reference-video"


def test_stage_reference_rejects_oversized_source(tmp_path):
    source = tmp_path / "large.mp4"
    source.write_bytes(b"12345")

    with pytest.raises(ReferenceAnalysisError, match="size limit"):
        stage_reference_video(source, tmp_path / "staging", max_file_size_bytes=4)

    assert not (tmp_path / "staging").exists()


def test_stage_reference_rejects_source_symlink(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    link = tmp_path / "link.mp4"
    try:
        link.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable in this environment")

    with pytest.raises(ReferenceAnalysisError, match="symbolic link"):
        stage_reference_video(link, tmp_path / "staging")


def test_stage_reference_rejects_symlink_staging_root(tmp_path):
    root = tmp_path / "real-staging"
    root.mkdir()
    link = tmp_path / "staging-link"
    try:
        link.symlink_to(root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable in this environment")
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    with pytest.raises(ReferenceAnalysisError, match="staging root"):
        stage_reference_video(source, link)


def test_cleanup_removes_only_owned_staging_directory(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    staging_root = tmp_path / "staging"
    staged = stage_reference_video(source, staging_root)
    unrelated = staging_root / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    cleanup_staged_reference(staged, staging_root)

    assert not staged.path.parent.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_cleanup_rejects_path_outside_owned_stage(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    staging_root = tmp_path / "staging"
    staged = stage_reference_video(source, staging_root)
    forged = StagedReference(
        id=staged.id,
        path=tmp_path / "outside.mp4",
        original_name=staged.original_name,
        size_bytes=staged.size_bytes,
        sha256=staged.sha256,
    )

    with pytest.raises(ReferenceAnalysisError, match="does not belong"):
        cleanup_staged_reference(forged, staging_root)

    assert staged.path.exists()



def test_stage_reference_reports_progress_and_can_be_cancelled(tmp_path):
    source = tmp_path / "large.mp4"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    staging = tmp_path / "staging"
    progress = []
    checks = []

    def cancel_after_first_chunk():
        checks.append(True)
        return len(checks) > 1

    with pytest.raises(ReferenceAnalysisCancelled, match="cancelled"):
        stage_reference_video(
            source,
            staging,
            progress_callback=lambda copied, total: progress.append((copied, total)),
            cancel_check=cancel_after_first_chunk,
        )

    assert progress[0] == (0, 2 * 1024 * 1024)
    assert progress[-1][0] == 1024 * 1024
    assert list(staging.iterdir()) == []
