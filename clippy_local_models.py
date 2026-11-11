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


def _catalog_model_dir(model_size: str) -> Path:
    return models_root() / "whisper" / model_size


def inspect_whisper_model() -> dict[str, Any]:
    """Describe the persisted selection and on-disk readiness without loading weights."""
    saved = _read_settings().get("whisper", {})
    if not isinstance(saved, dict):
        saved = {}

    size = saved.get("model_size", "small")
    if size not in WHISPER_MODELS:
        size = "small"
    custom_path = saved.get("model_path")
    source = "local" if custom_path else "catalog"
    configured = bool(custom_path or saved.get("model_size") in WHISPER_MODELS)
    candidate = Path(str(custom_path)).expanduser() if custom_path else _catalog_model_dir(size)

    try:
        resolved = validate_whisper_model_path(str(candidate))
        installed = True
        validation_error = None
        resolved_path = str(resolved)
    except (OSError, ValueError) as exc:
        installed = False
        validation_error = str(exc)
        resolved_path = str(candidate)

    return {
        "model_size": size,
        "model_path": resolved_path if source == "local" or installed else None,
        "source": source,
        "selected": configured,
        "configured": configured,
        "installed": installed,
        "available": installed,
        "status": ("ready" if installed else "selected_not_downloaded") if configured else "not_selected",
        "validation_error": validation_error,
    }


def get_whisper_selection() -> dict[str, Any]:
    return inspect_whisper_model()


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
        # A catalog choice is a saved preference, not proof that its weights
        # exist locally. Keep the selection visible while reporting that it
        # still needs an explicit download or first-use fetch.
        selection = {"model_size": model_size, "model_path": None}
    settings["whisper"] = selection
    _write_settings(settings)
    return get_whisper_selection()


def verify_whisper_model_load() -> dict[str, Any]:
    """Explicitly load the selected local weights on CPU to verify CTranslate2 compatibility."""
    selection = get_whisper_selection()
    if not selection.get("installed"):
        raise FileNotFoundError(
            f"Whisper {selection.get('model_size', 'small')} is selected but its model files "
            "are not installed. Download the model first."
        )

    from faster_whisper import WhisperModel

    model_path = selection.get("model_path") or str(_catalog_model_dir(selection["model_size"]))
    # CPU int8 is a conservative compatibility probe. It avoids depending on
    # the user's CUDA driver and does not run inference or alter GPU settings.
    model = WhisperModel(
        model_path,
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1,
        local_files_only=True,
    )
    del model
    return {
        "ok": True,
        "model_size": selection["model_size"],
        "model_path": model_path,
        "message": "The selected Whisper model loaded successfully with faster-whisper (CPU int8).",
    }


def whisper_model_argument() -> str:
    selection = get_whisper_selection()
    if selection.get("source") == "local":
        if not selection.get("installed", False):
            raise FileNotFoundError(
                "The selected local Whisper model is unavailable. Open Settings "
                "and choose another model or update its folder path."
            )
        return selection["model_path"]
    # Keep faster-whisper's normal cache/download behavior for catalog models.
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
