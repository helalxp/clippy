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
