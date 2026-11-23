"""Windows-only smoke test for managed Whisper model file locking and promotion.

This uses only the standard library. It exercises the actual msvcrt lock and
Windows directory rename behavior without downloading model weights or loading
CTranslate2.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))


def make_model(path: Path, marker: bytes) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "model.bin").write_bytes(marker)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / "vocabulary.txt").write_text("test vocabulary", encoding="utf-8")
    return path


def check_cross_process_lock(model_path: Path, root: Path) -> None:
    attempted = root / "child-attempted-lock"
    blocked = root / "child-blocked-on-lock"
    acquired = root / "child-acquired-lock"
    child = r"""
import sys
from pathlib import Path
import clippy_local_models as models

attempted, blocked, acquired = map(Path, sys.argv[2:5])
original = models.acquire_file_lock

def signal_and_lock(handle):
    attempted.write_text("attempted", encoding="utf-8")
    try:
        return original(handle)
    except OSError:
        blocked.write_text("blocked", encoding="utf-8")
        raise

models.acquire_file_lock = signal_and_lock
with models.whisper_model_path_lock(sys.argv[1]):
    acquired.write_text("acquired", encoding="utf-8")
"""
    environment = os.environ.copy()
    environment["CLIPPY_MODELS_DIR"] = str(root / "models")
    process = None
    try:
        with __import__("clippy_local_models").whisper_model_path_lock(model_path):
            process = subprocess.Popen(
                [sys.executable, "-c", child, str(model_path), str(attempted), str(blocked), str(acquired)],
                cwd=REPOSITORY_ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            deadline = time.monotonic() + 8
            while not blocked.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(0.02)
            assert attempted.exists(), "Child process did not reach the Windows file lock."
            assert blocked.exists(), "The Windows file lock did not block the competing process."
            assert process.poll() is None, "Child process exited despite the parent holding the model lock."
            assert not acquired.exists(), "Child acquired the lock while the parent held it."

        stdout, stderr = process.communicate(timeout=8)
        assert process.returncode == 0, f"Child lock process failed: {stderr}\\n{stdout}"
        assert acquired.exists(), "Child did not acquire the lock after the parent released it."
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)

def check_directory_promotion(root: Path) -> None:
    import clippy_local_models as models

    destination = root / "models" / "whisper" / "base"
    staging = destination.parent / ".base.staging-smoke"
    make_model(destination, b"old-model")
    make_model(staging, b"new-model")

    promoted = models._promote_staged_whisper_model(staging, destination)
    assert promoted == destination.resolve()
    assert (destination / "model.bin").read_bytes() == b"new-model"
    assert not list(destination.parent.glob(".base.previous-*"))

    # Fail the second rename, after the old directory has been moved aside.
    # The original must be restored and staging must remain available for the
    # caller's normal failure cleanup.
    staging = destination.parent / ".base.staging-failure"
    make_model(staging, b"failed-candidate")
    real_replace = os.replace
    calls = 0

    def fail_staging_activation(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated Windows activation failure")
        return real_replace(source, target)

    models.os.replace = fail_staging_activation
    try:
        try:
            models._promote_staged_whisper_model(staging, destination)
        except OSError as exc:
            assert "simulated Windows activation failure" in str(exc)
        else:
            raise AssertionError("Promotion unexpectedly succeeded.")
    finally:
        models.os.replace = real_replace

    assert calls == 3, "Expected old-model backup, failed activation, and restore."
    assert (destination / "model.bin").read_bytes() == b"new-model"
    assert staging.is_dir()
    assert not list(destination.parent.glob(".base.previous-*"))


def main() -> None:
    if os.name != "nt":
        raise SystemExit("This smoke test must run on Windows.")
    with tempfile.TemporaryDirectory(prefix="clippy-whisper-lock-") as temporary:
        root = Path(temporary)
        os.environ["CLIPPY_MODELS_DIR"] = str(root / "models")
        model_path = root / "models" / "whisper" / "base"
        check_cross_process_lock(model_path, root)
        check_directory_promotion(root)
    print("Windows Whisper activation lock and directory promotion smoke test passed.")


if __name__ == "__main__":
    main()
