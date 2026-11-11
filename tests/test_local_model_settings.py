import json

import pytest

import clippy_local_models as models


def make_model(path):
    path.mkdir(parents=True)
    (path / "model.bin").write_bytes(b"model")
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / "vocabulary.json").write_text("{}", encoding="utf-8")
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


def test_catalog_selection_reports_installed_weights(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPY_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CLIPPY_MODELS_DIR", str(tmp_path / "models"))
    model_dir = make_model(tmp_path / "models" / "whisper" / "base")

    selected = models.save_whisper_selection(model_size="base")

    assert selected["installed"] is True
    assert selected["available"] is True
    assert selected["status"] == "ready"
    assert selected["model_path"] == str(model_dir.resolve())


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

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))

    result = models.verify_whisper_model_load()

    assert result["ok"] is True
    assert calls["model_path"] == str(model_dir.resolve())
    assert calls["device"] == "cpu"
    assert calls["compute_type"] == "int8"
    assert calls["local_files_only"] is True


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
