"""Local AI model selection and download helpers for desktop/self-hosted Clippy.

Runtime dependencies are managed by the desktop first-run bootstrapper. This
module deliberately manages model weights only; it must not install Python or
Node packages as a side effect of selecting a model.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

WHISPER_MODELS = {
    "tiny": {"repo_id": "Systran/faster-whisper-tiny", "label": "Tiny", "description": "Fastest, lowest memory use; lower accuracy."},
    "base": {"repo_id": "Systran/faster-whisper-base", "label": "Base", "description": "Lightweight balance for quick transcription."},
    "small": {"repo_id": "Systran/faster-whisper-small", "label": "Small", "description": "Balanced quality and resource use. Default."},
    "medium": {"repo_id": "Systran/faster-whisper-medium", "label": "Medium", "description": "Higher accuracy, heavier memory and compute use."},
    "large-v3": {"repo_id": "Systran/faster-whisper-large-v3", "label": "Large v3", "description": "High accuracy; requires substantially more resources."},
    "large-v3-turbo": {"repo_id": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "label": "Large v3 Turbo", "description": "High quality with faster inference; still resource intensive."},
}

_download_lock = threading.Lock()
_download_tasks: dict[str, dict[str, Any]] = {}


def settings_path() -> Path:
    explicit = os.environ.get("CLIPPY_SETTINGS_PATH")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "Clippy" / "settings.json"


def models_root() -> Path:
    explicit = os.environ.get("CLIPPY_MODELS_DIR")
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return root / "Clippy" / "models"


def _read_settings() -> dict[str, Any]:
    path = settings_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_settings(value: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def validate_whisper_model_path(value: str) -> Path:
    """Accept a model directory or its model.bin file and validate its layout."""
    raw = str(value or "").strip().strip('"')
    if not raw:
        raise ValueError("Choose a model folder or model.bin file.")
    candidate = Path(raw).expanduser()
    if candidate.is_file() and candidate.name.lower() == "model.bin":
        candidate = candidate.parent
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise ValueError("The selected Whisper model folder does not exist.")
    required = ("model.bin", "config.json", "tokenizer.json", "vocabulary.json")
    missing = [name for name in required if not (candidate / name).is_file()]
    if missing:
        raise ValueError(
            "This folder is not a complete faster-whisper model. Missing: "
            + ", ".join(missing)
        )
    return candidate


def get_whisper_selection() -> dict[str, Any]:
    saved = _read_settings().get("whisper", {})
    if not isinstance(saved, dict):
        saved = {}
    model_path = saved.get("model_path")
    if model_path:
        try:
            resolved = validate_whisper_model_path(model_path)
            return {"model_size": saved.get("model_size", "small"),
                    "model_path": str(resolved), "source": "local",
                    "available": True}
        except (OSError, ValueError):
            # Keep the user's selection visible as unavailable instead of
            # silently switching models behind their back.
            return {"model_size": saved.get("model_size", "small"),
                    "model_path": str(model_path), "source": "local",
                    "available": False}
    size = saved.get("model_size", "small")
    if size not in WHISPER_MODELS:
        size = "small"
    return {"model_size": size, "model_path": None, "source": "catalog",
            "available": True}


def save_whisper_selection(*, model_size: str | None = None,
                           model_path: str | None = None) -> dict[str, Any]:
    settings = _read_settings()
    if model_path:
        resolved = validate_whisper_model_path(model_path)
        selection = {"model_size": model_size or "small",
                     "model_path": str(resolved)}
    else:
        if model_size not in WHISPER_MODELS:
            raise ValueError("Choose one of the supported Whisper model sizes.")
        selection = {"model_size": model_size, "model_path": None}
    settings["whisper"] = selection
    _write_settings(settings)
    return get_whisper_selection()


def whisper_model_argument() -> str:
    selection = get_whisper_selection()
    if selection.get("source") == "local":
        if not selection.get("available", False):
            raise FileNotFoundError(
                "The selected local Whisper model is unavailable. Open Settings "
                "and choose another model or update its folder path."
            )
        return selection["model_path"]
    return selection.get("model_size") or "small"


def list_download_tasks() -> dict[str, dict[str, Any]]:
    with _download_lock:
        return {key: dict(value) for key, value in _download_tasks.items()}


def queue_whisper_download(task_id: str, model_size: str) -> None:
    if model_size not in WHISPER_MODELS:
        raise ValueError("Unsupported Whisper model size.")
    with _download_lock:
        if any(task.get("status") in {"queued", "downloading"} for task in _download_tasks.values()):
            raise RuntimeError("A Whisper model download is already running.")
        _download_tasks[task_id] = {"status": "queued", "model_size": model_size,
                                    "message": "Preparing model download…"}


def start_whisper_download(task_id: str, model_size: str) -> None:
    with _download_lock:
        _download_tasks[task_id] = {"status": "downloading", "model_size": model_size,
                                    "message": "Downloading model files…"}
    try:
        from huggingface_hub import snapshot_download
        destination = models_root() / "whisper" / model_size
        destination.parent.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=WHISPER_MODELS[model_size]["repo_id"],
            local_dir=str(destination),
        )
        model_dir = validate_whisper_model_path(str(destination))
        save_whisper_selection(model_size=model_size, model_path=str(model_dir))
        with _download_lock:
            _download_tasks[task_id] = {"status": "complete", "model_size": model_size,
                                        "model_path": str(model_dir), "message": "Model ready."}
    except Exception as exc:
        with _download_lock:
            _download_tasks[task_id] = {"status": "failed", "model_size": model_size,
                                        "message": str(exc)[:500]}
