import json

import pytest

import clippy_local_models as models


def make_model(path, vocabulary_name="vocabulary.txt"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "model.bin").write_bytes(b"model")
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / vocabulary_name).write_text("test vocabulary", encoding="utf-8")
    return path


def test_catalog_has_expected_whisper_choices():
    assert {"tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"} <= set(models.WHISPER_MODELS)


def test_settings_are_persisted_outside_application_directory(tmp_path, monkeypatch):
    settings = tmp_path / "user-data" / "settings.json"
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(settings))

    saved = models.save_whisper_selection(model_size="medium")

    assert saved["model_size"] == "medium"
    assert saved["source"] == "catalog"
    assert json.loads(settings.read_text(encoding="utf-8"))["whisper"]["model_size"] == "medium"


def test_existing_model_directory_can_be_selected(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    model_dir = make_model(tmp_path / "whisper-small")

    saved = models.save_whisper_selection(model_path=str(model_dir))

    assert saved["source"] == "local"
    assert saved["available"] is True
    assert models.whisper_model_argument() == str(model_dir.resolve())


def test_model_bin_file_path_resolves_to_parent_folder(tmp_path):
    model_dir = make_model(tmp_path / "model")
    assert models.validate_whisper_model_path(str(model_dir / "model.bin")) == model_dir.resolve()


def test_model_accepts_vocabulary_json_for_compatible_conversions(tmp_path):
    model_dir = make_model(tmp_path / "model-json", vocabulary_name="vocabulary.json")
    assert models.validate_whisper_model_path(str(model_dir)) == model_dir.resolve()


def test_model_rejects_folder_missing_both_supported_vocabulary_formats(tmp_path):
    model_dir = make_model(tmp_path / "model")
    (model_dir / "vocabulary.txt").unlink()
    with pytest.raises(ValueError, match="vocabulary.txt or vocabulary.json"):
        models.validate_whisper_model_path(str(model_dir))


def test_incomplete_model_folder_is_rejected(tmp_path):
    folder = tmp_path / "not-a-model"
    folder.mkdir()
    (folder / "model.bin").write_bytes(b"model")
    with pytest.raises(ValueError, match="config.json"):
        models.validate_whisper_model_path(str(folder))


def test_unavailable_selected_local_model_does_not_silently_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    model_dir = make_model(tmp_path / "model")
    models.save_whisper_selection(model_path=str(model_dir))
    model_dir.rename(tmp_path / "model-moved")

    with pytest.raises(FileNotFoundError, match="selected local Whisper model"):
        models.whisper_model_argument()



def test_catalog_selection_is_saved_but_not_reported_as_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))

    selected = models.save_whisper_selection(model_size="medium")

    assert selected["selected"] is True
    assert selected["model_size"] == "medium"
    assert selected["source"] == "catalog"
    assert selected["installed"] is False
    assert selected["available"] is False
    assert selected["status"] == "selected_not_downloaded"
    assert models.whisper_model_argument() == "medium"


def test_desktop_catalog_selection_keeps_first_use_hub_behavior(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("CLIPPY_DESKTOP_MODE", "1")

    selected = models.save_whisper_selection(model_size="base")

    assert selected["status"] == "selected_not_downloaded"
    assert models.whisper_model_argument() == "base"


def test_whisper_model_path_lock_serializes_threads(tmp_path, monkeypatch):
    import threading

    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    model_path = tmp_path / "models" / "whisper" / "base"
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    errors = []

    def hold_lock():
        try:
            with models.whisper_model_path_lock(model_path):
                first_entered.set()
                if not release_first.wait(5):
                    raise TimeoutError("test did not release first model lock")
        except Exception as exc:
            errors.append(exc)

    def wait_for_lock():
        try:
            with models.whisper_model_path_lock(model_path):
                second_entered.set()
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=hold_lock)
    second = threading.Thread(target=wait_for_lock)
    first.start()
    assert first_entered.wait(2)
    second.start()
    assert not second_entered.wait(0.15)
    release_first.set()
    assert second_entered.wait(2)
    first.join(2)
    second.join(2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []


def test_catalog_selection_recovers_previous_model_after_interrupted_promotion(
    tmp_path, monkeypatch
):
    settings = tmp_path / "settings.json"
    models_root = tmp_path / "models"
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(settings))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(models_root))
    backup = make_model(
        models_root / "whisper" / ".small.previous-interrupted"
    )
    settings.write_text(
        json.dumps({"whisper": {"model_size": "small", "model_path": None}}),
        encoding="utf-8",
    )

    selection = models.get_whisper_selection()

    destination = models_root / "whisper" / "small"
    assert selection["installed"] is True
    assert selection["model_path"] == str(destination.resolve())
    assert (destination / "model.bin").read_bytes() == b"model"
    assert not backup.exists()


def test_catalog_selection_reports_installed_weights(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    model_dir = make_model(tmp_path / "models" / "whisper" / "base")

    selected = models.save_whisper_selection(model_size="base")

    assert selected["installed"] is True
    assert selected["available"] is True
    assert selected["status"] == "ready"
    assert selected["model_path"] == str(model_dir.resolve())


def test_catalog_selection_uses_managed_directory_for_transcription(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    model_dir = make_model(tmp_path / "models" / "whisper" / "medium")

    selected = models.save_whisper_selection(model_size="medium")

    assert selected["source"] == "catalog"
    assert selected["installed"] is True
    assert selected["model_path"] == str(model_dir.resolve())
    assert models.whisper_model_argument() == str(model_dir.resolve())


def test_legacy_managed_catalog_path_is_not_misclassified_as_custom(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    model_dir = make_model(tmp_path / "models" / "whisper" / "small")
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({
            "whisper": {
                "model_size": "small",
                "model_path": str(model_dir.resolve()),
            }
        }),
        encoding="utf-8",
    )

    selection = models.get_whisper_selection()

    assert selection["source"] == "catalog"
    assert selection["installed"] is True
    assert selection["model_path"] == str(model_dir.resolve())


def test_catalog_verification_uses_the_same_resolved_path_as_transcription(
    tmp_path, monkeypatch
):
    import sys
    import types

    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    model_dir = make_model(tmp_path / "models" / "whisper" / "small")
    models.save_whisper_selection(model_size="small")
    calls = {}

    class FakeWhisperModel:
        def __init__(self, model_path, **kwargs):
            calls["model_path"] = model_path
            calls.update(kwargs)

        def transcribe(self, audio_path, **kwargs):
            calls["transcribe_kwargs"] = kwargs
            def generated_segments():
                calls["inference_iterated"] = True
                yield object()
            return generated_segments(), type("Info", (), {"duration": 2.0})()

    monkeypatch.setitem(
        sys.modules, "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )

    result = models.verify_whisper_model_load()

    assert result["ok"] is True
    assert result["model_path"] == str(model_dir.resolve())
    assert calls["model_path"] == models.whisper_model_argument()
    assert calls["model_path"] == str(model_dir.resolve())
    assert calls["inference_iterated"] is True


def test_saving_catalog_selection_preserves_other_whisper_preferences(
    tmp_path, monkeypatch
):
    settings = tmp_path / "settings.json"
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(settings))
    settings.write_text(
        json.dumps({"whisper": {"gpu_mode": True, "other_setting": "preserve"}}),
        encoding="utf-8",
    )

    selected = models.save_whisper_selection(model_size="medium")
    saved = json.loads(settings.read_text(encoding="utf-8"))["whisper"]

    assert saved["gpu_mode"] is True
    assert saved["other_setting"] == "preserve"
    assert saved["selection_revision"] == 1
    assert selected["selection_revision"] == 1


def _install_fake_snapshot_download(
    monkeypatch, *, model_load_error=None, events=None
):
    import sys
    import types

    from pathlib import Path

    def snapshot_download(repo_id, local_dir):
        if events is not None:
            events["download_path"] = Path(local_dir)
        make_model(Path(local_dir))

    class FakeWhisperModel:
        def __init__(self, model_path, **kwargs):
            if events is not None:
                events["load_path"] = Path(model_path)
                events["load_kwargs"] = kwargs
            if model_load_error:
                raise RuntimeError(model_load_error)

        def transcribe(self, audio_path, **kwargs):
            if events is not None:
                events["inference"] = True
            def generated_segments():
                yield object()
            return generated_segments(), types.SimpleNamespace(duration=2.0)

    monkeypatch.setitem(
        sys.modules, "huggingface_hub",
        types.SimpleNamespace(snapshot_download=snapshot_download),
    )
    monkeypatch.setitem(
        sys.modules, "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeWhisperModel),
    )


def test_download_completion_does_not_overwrite_a_newer_user_selection(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))

    download_revision = models.queue_whisper_download("download-medium", "medium")
    models.save_whisper_selection(model_size="small")
    _install_fake_snapshot_download(monkeypatch)

    models.start_whisper_download("download-medium", "medium", download_revision)

    selection = models.get_whisper_selection()
    task = models.list_download_tasks()["download-medium"]

    assert selection["model_size"] == "small"
    assert selection["source"] == "catalog"
    assert task["status"] == "complete"
    assert task["activated"] is False
    assert "newer selection was preserved" in task["message"]
    assert (tmp_path / "models" / "whisper" / "medium" / "model.bin").is_file()


def test_download_keeps_candidate_staged_until_native_model_load_passes(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    destination = tmp_path / "models" / "whisper" / "small"
    events = {}

    download_revision = models.queue_whisper_download("download-staged", "small")
    _install_fake_snapshot_download(monkeypatch, events=events)

    models.start_whisper_download("download-staged", "small", download_revision)

    task = models.list_download_tasks()["download-staged"]
    assert task["status"] == "complete"
    assert events["download_path"] == events["load_path"]
    assert events["download_path"].parent == destination.parent
    assert events["download_path"].name.startswith(".small.staging-")
    assert events["load_kwargs"]["local_files_only"] is True
    assert events["inference"] is True
    assert destination.is_dir()
    assert (destination / "model.bin").is_file()
    assert not list(destination.parent.glob(".small.staging-*"))


def test_failed_native_model_load_preserves_previous_model_and_selection(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    destination = make_model(tmp_path / "models" / "whisper" / "small")
    models.save_whisper_selection(model_size="small")
    original_model = (destination / "model.bin").read_bytes()
    events = {}

    download_revision = models.queue_whisper_download("download-load-fail", "small")
    _install_fake_snapshot_download(
        monkeypatch,
        model_load_error="native CTranslate2 load failed",
        events=events,
    )

    models.start_whisper_download("download-load-fail", "small", download_revision)

    task = models.list_download_tasks()["download-load-fail"]
    assert task["status"] == "failed"
    assert "native CTranslate2 load failed" in task["message"]
    assert (destination / "model.bin").read_bytes() == original_model
    assert not list(destination.parent.glob(".small.staging-*"))
    assert models.get_whisper_selection()["model_path"] == str(destination.resolve())


def test_existing_model_is_replaced_only_after_verified_staged_download(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    destination = make_model(tmp_path / "models" / "whisper" / "small")
    (destination / "model.bin").write_bytes(b"previous-complete-model")
    download_revision = models.queue_whisper_download("download-replace", "small")
    _install_fake_snapshot_download(monkeypatch)

    models.start_whisper_download("download-replace", "small", download_revision)

    task = models.list_download_tasks()["download-replace"]
    assert task["status"] == "complete"
    assert (destination / "model.bin").read_bytes() == b"model"
    assert not list(destination.parent.glob(".small.previous-*"))
    assert not list(destination.parent.glob(".small.staging-*"))


def test_whisper_model_path_lock_serializes_processes(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    models_root = tmp_path / "models"
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(models_root))
    model_path = models_root / "whisper" / "base"
    child_code = """
import sys
from clippy_local_models import whisper_model_path_lock
print('WAITING', flush=True)
with whisper_model_path_lock(sys.argv[1]):
    print('LOCK_ACQUIRED', flush=True)
"""

    with models.whisper_model_path_lock(model_path):
        process = subprocess.Popen(
            [sys.executable, "-c", child_code, str(model_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "CLIPPY_MODELS_DIR": str(models_root)},
        )
        # Wait until the child has reached the lock attempt. It must remain
        # blocked until the parent releases the model-size-specific lock.
        assert process.stdout.readline().strip() == "WAITING"
        import time
        time.sleep(0.2)
        assert process.poll() is None

    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr
    assert "LOCK_ACQUIRED" in stdout


def test_directory_validation_failure_restores_previous_model(
    tmp_path, monkeypatch
):
    from pathlib import Path

    destination = make_model(tmp_path / "models" / "whisper" / "small")
    (destination / "model.bin").write_bytes(b"previous-complete-model")
    staging = make_model(destination.parent / ".small.staging-invalid")
    (staging / "model.bin").write_bytes(b"new-model")
    real_validate = models.validate_whisper_model_path

    def reject_activated_directory(value):
        if Path(value).resolve() == destination.resolve():
            raise ValueError("simulated final directory validation failure")
        return real_validate(value)

    monkeypatch.setattr(models, "validate_whisper_model_path", reject_activated_directory)

    with pytest.raises(ValueError, match="simulated final directory validation failure"):
        models._promote_staged_whisper_model(staging, destination)

    assert (destination / "model.bin").read_bytes() == b"previous-complete-model"
    assert not list(destination.parent.glob(".small.failed-*"))
    assert not list(destination.parent.glob(".small.previous-*"))


def test_failed_directory_promotion_restores_previous_model(
    tmp_path, monkeypatch
):
    import os

    destination = make_model(tmp_path / "models" / "whisper" / "small")
    (destination / "model.bin").write_bytes(b"previous-complete-model")
    staging = make_model(destination.parent / ".small.staging-test")
    (staging / "model.bin").write_bytes(b"new-model")
    real_replace = os.replace
    replace_calls = {"count": 0}

    def fail_second_rename(source, target):
        replace_calls["count"] += 1
        if replace_calls["count"] == 2:
            raise OSError("simulated activation rename failure")
        return real_replace(source, target)

    monkeypatch.setattr(models.os, "replace", fail_second_rename)

    with pytest.raises(OSError, match="simulated activation rename failure"):
        models._promote_staged_whisper_model(staging, destination)

    assert replace_calls["count"] == 3  # move old aside, fail new, restore old
    assert (destination / "model.bin").read_bytes() == b"previous-complete-model"
    assert staging.is_dir()
    assert not list(destination.parent.glob(".small.previous-*"))


def test_interrupted_download_never_leaves_a_partial_final_model(
    tmp_path, monkeypatch
):
    import sys
    import types
    from pathlib import Path

    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))

    def interrupted_download(repo_id, local_dir):
        staging = Path(local_dir)
        (staging / "model.bin").write_bytes(b"partial")
        raise RuntimeError("simulated interrupted download")

    monkeypatch.setitem(
        sys.modules, "huggingface_hub",
        types.SimpleNamespace(snapshot_download=interrupted_download),
    )
    download_revision = models.queue_whisper_download("download-interrupted", "base")

    models.start_whisper_download("download-interrupted", "base", download_revision)

    destination = tmp_path / "models" / "whisper" / "base"
    task = models.list_download_tasks()["download-interrupted"]
    assert task["status"] == "failed"
    assert "simulated interrupted download" in task["message"]
    assert not destination.exists()
    assert not list(destination.parent.glob(".base.staging-*"))


def test_download_activates_model_when_selection_has_not_changed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))

    download_revision = models.queue_whisper_download("download-small", "small")
    _install_fake_snapshot_download(monkeypatch)

    models.start_whisper_download("download-small", "small", download_revision)

    selection = models.get_whisper_selection()
    task = models.list_download_tasks()["download-small"]

    assert selection["model_size"] == "small"
    assert selection["source"] == "catalog"
    assert selection["installed"] is True
    expected_path = (tmp_path / "models" / "whisper" / "small").resolve()
    assert selection["model_path"] == str(expected_path)
    assert models.whisper_model_argument() == str(expected_path)
    assert task["status"] == "complete"
    assert task["activated"] is True


def test_verify_whisper_model_load_calls_real_loader_with_safe_cpu_settings(tmp_path, monkeypatch):
    import sys
    import types

    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    model_dir = make_model(tmp_path / "whisper")
    models.save_whisper_selection(model_path=str(model_dir))
    calls = {}

    class FakeWhisperModel:
        def __init__(self, model_path, **kwargs):
            calls["model_path"] = model_path
            calls.update(kwargs)

        def transcribe(self, audio_path, **kwargs):
            from pathlib import Path
            import wave
            calls["audio_path"] = audio_path
            calls["transcribe_kwargs"] = kwargs
            with wave.open(audio_path, "rb") as wav_file:
                calls["audio_frames"] = wav_file.getnframes()
                calls["audio_rate"] = wav_file.getframerate()
            # Return a lazy iterator so the test asserts the implementation
            # consumes it, just as the real faster-whisper API requires.
            def generated_segments():
                calls["inference_iterated"] = True
                yield object()
            return generated_segments(), type("Info", (), {"duration": 2.0})()

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))

    result = models.verify_whisper_model_load()

    assert result["ok"] is True
    assert calls["model_path"] == str(model_dir.resolve())
    assert calls["device"] == "cpu"
    assert calls["compute_type"] == "int8"
    assert calls["local_files_only"] is True
    assert calls["audio_frames"] == 32000
    assert calls["audio_rate"] == 16000
    assert calls["transcribe_kwargs"]["beam_size"] == 1
    assert calls["inference_iterated"] is True
    assert result["inference_seconds"] >= 0
    assert result["test_audio_seconds"] == 2


def test_verify_whisper_model_load_refuses_uninstalled_catalog_model(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    models.save_whisper_selection(model_size="large-v3")

    with pytest.raises(FileNotFoundError, match="selected but its model files"):
        models.verify_whisper_model_load()


def test_default_whisper_fallback_is_not_misreported_as_a_saved_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))

    selection = models.get_whisper_selection()

    assert selection["model_size"] == "small"
    assert selection["selected"] is False
    assert selection["configured"] is False
    assert selection["status"] == "not_selected"
    # The pipeline retains a safe default, but the UI must not call it a saved choice.
    assert models.whisper_model_argument() == "small"
