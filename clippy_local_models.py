"""Local AI model selection and download helpers for desktop/self-hosted Clippy.

Runtime dependencies are managed by the desktop first-run bootstrapper. This
module deliberately manages model weights only; it must not install Python or
Node packages as a side effect of selecting a model.
"""
from __future__ import annotations

import gc
import json
import os
import shutil
import threading
import tempfile
import time
import uuid
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

_settings_lock = threading.RLock()
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
    with _settings_lock:
        path = settings_path()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}


def _write_settings(value: dict[str, Any]) -> None:
    """Persist settings atomically without sharing a temporary filename."""
    with _settings_lock:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise


def _selection_revision(whisper_settings: Any) -> int:
    if not isinstance(whisper_settings, dict):
        return 0
    try:
        return max(0, int(whisper_settings.get("selection_revision", 0) or 0))
    except (TypeError, ValueError):
        return 0


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
    required = ("model.bin", "config.json", "tokenizer.json")
    missing = [name for name in required if not (candidate / name).is_file()]
    # faster-whisper model repositories use either vocabulary.txt (Systran's
    # standard conversions) or vocabulary.json (some newer conversions).
    # CTranslate2 supports both; requiring only .json rejects valid downloads.
    vocabulary_files = ("vocabulary.txt", "vocabulary.json")
    if not any((candidate / name).is_file() for name in vocabulary_files):
        missing.append("vocabulary.txt or vocabulary.json")
    if missing:
        raise ValueError(
            "This folder is not a complete faster-whisper model. Missing: "
            + ", ".join(missing)
        )
    empty = [name for name in (*required, *vocabulary_files)
             if (candidate / name).is_file() and (candidate / name).stat().st_size == 0]
    if empty:
        raise ValueError(
            "This faster-whisper model contains empty required files: "
            + ", ".join(empty)
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
    if not isinstance(size, str) or size not in WHISPER_MODELS:
        size = "small"
    custom_path = saved.get("model_path")
    source = "catalog"
    if custom_path:
        supplied_path = Path(str(custom_path)).expanduser()
        try:
            # Downloads from Clippy's catalog are also stored with an absolute
            # model_path for compatibility with older settings. Recognize that
            # managed directory as a catalog model, not a user-supplied folder.
            if supplied_path.resolve() != _catalog_model_dir(size).resolve():
                source = "local"
            else:
                custom_path = None
        except (OSError, RuntimeError):
            source = "local"

    configured = bool(saved.get("model_path") or saved.get("model_size") in WHISPER_MODELS)
    candidate = Path(str(custom_path)).expanduser() if source == "local" else _catalog_model_dir(size)

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
        "selection_revision": _selection_revision(saved),
    }


def get_whisper_selection() -> dict[str, Any]:
    return inspect_whisper_model()


def update_whisper_preferences(**changes: Any) -> dict[str, Any]:
    """Update non-picker Whisper preferences through the same atomic settings store."""
    with _settings_lock:
        settings = _read_settings()
        previous = settings.get("whisper", {})
        if not isinstance(previous, dict):
            previous = {}

        updated = dict(previous)
        model_size_changed = (
            "model_size" in changes
            and changes["model_size"] != previous.get("model_size")
        )
        if model_size_changed and "model_path" not in changes:
            # A legacy first-run model-size change must not keep an unrelated
            # custom local path active.
            updated["model_path"] = None
        updated.update(changes)
        if model_size_changed:
            updated["selection_revision"] = _selection_revision(previous) + 1
        else:
            updated["selection_revision"] = _selection_revision(previous)

        settings["whisper"] = updated
        _write_settings(settings)

    return inspect_whisper_model()


def save_whisper_selection(*, model_size: str | None = None,
                           model_path: str | None = None) -> dict[str, Any]:
    with _settings_lock:
        settings = _read_settings()
        previous = settings.get("whisper", {})
        if not isinstance(previous, dict):
            previous = {}

        if model_path:
            resolved = validate_whisper_model_path(model_path)
            selection = {
                "model_size": model_size or previous.get("model_size") or "small",
                "model_path": str(resolved),
            }
        else:
            if model_size not in WHISPER_MODELS:
                raise ValueError("Choose one of the supported Whisper model sizes.")
            # A catalog choice is a preference, not proof that its weights exist.
            selection = {"model_size": model_size, "model_path": None}

        # Preserve unrelated/legacy Whisper preferences (for example gpu_mode)
        # while making each explicit selection change observable to downloads.
        updated = dict(previous)
        updated.update(selection)
        updated["selection_revision"] = _selection_revision(previous) + 1
        settings["whisper"] = updated
        _write_settings(settings)

    return get_whisper_selection()


def _verify_whisper_model_directory(model_path: str, model_size: str) -> dict[str, Any]:
    """Load a candidate model directory and execute a real short CPU transcription."""
    import math
    import wave
    from array import array

    from faster_whisper import WhisperModel

    # CPU int8 makes integrity verification independent of CUDA availability
    # and does not alter the user's selected production device/preferences.
    audio_path = None
    model = None
    load_started = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(prefix="clippy-whisper-test-", suffix=".wav", delete=False) as audio_file:
            audio_path = Path(audio_file.name)

        # A deterministic tone exercises both the packaged PyAV decoder and
        # the actual CTranslate2 encoder/decoder without requiring user media.
        sample_rate = 16_000
        duration_seconds = 2
        samples = array(
            "h",
            (
                int(2500 * math.sin(2.0 * math.pi * 440.0 * index / sample_rate))
                for index in range(sample_rate * duration_seconds)
            ),
        )
        with wave.open(str(audio_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(samples.tobytes())

        model = WhisperModel(
            model_path,
            device="cpu",
            compute_type="int8",
            cpu_threads=2,
            num_workers=1,
            local_files_only=True,
        )
        load_seconds = time.perf_counter() - load_started

        inference_started = time.perf_counter()
        segments, info = model.transcribe(
            str(audio_path),
            language="en",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            vad_filter=False,
        )
        # faster-whisper is lazy: iterating is required to execute inference.
        list(segments)
        inference_seconds = time.perf_counter() - inference_started
        if not getattr(info, "duration", None):
            raise RuntimeError("The test audio was not decoded by faster-whisper.")

        return {
            "ok": True,
            "model_size": model_size,
            "model_path": model_path,
            "load_seconds": round(load_seconds, 2),
            "inference_seconds": round(inference_seconds, 2),
            "test_audio_seconds": duration_seconds,
            "message": (
                "The model loaded and completed a real faster-whisper transcription "
                "pass on 2 seconds of test audio (CPU int8)."
            ),
        }
    finally:
        if model is not None:
            del model
            # CTranslate2 owns native file handles; collect before the caller
            # attempts a same-volume directory rename on Windows.
            gc.collect()
        if audio_path is not None:
            try:
                audio_path.unlink(missing_ok=True)
            except OSError:
                pass


def verify_whisper_model_load() -> dict[str, Any]:
    """Load the selected model and execute a real, short CPU transcription pass."""
    selection = get_whisper_selection()
    if not selection.get("installed"):
        raise FileNotFoundError(
            f"Whisper {selection.get('model_size', 'small')} is selected but its model files "
            "are not installed. Download the model first."
        )
    # Verification and production transcription must load the same resolved source.
    model_path = whisper_model_argument(selection)
    return _verify_whisper_model_directory(model_path, selection["model_size"])


def _promote_staged_whisper_model(staging: Path, destination: Path) -> Path:
    """Promote a fully verified model on the same volume, restoring old files on failure."""
    backup = None
    if destination.exists():
        backup = destination.with_name(
            f".{destination.name}.previous-{uuid.uuid4().hex}"
        )
        # Keep the previous model intact until the new directory is ready.
        os.replace(destination, backup)

    try:
        # staging and destination are siblings, so this is a same-volume rename.
        os.replace(staging, destination)
    except Exception as promotion_error:
        if backup is not None and backup.exists() and not destination.exists():
            try:
                os.replace(backup, destination)
            except OSError as restore_error:
                raise RuntimeError(
                    "The new Whisper model could not be activated and the previous "
                    f"model could not be restored automatically. Previous files remain at "
                    f"{backup}. Activation error: {promotion_error}; restore error: {restore_error}"
                ) from promotion_error
        raise

    if backup is not None and backup.exists():
        # Cleanup failure must not turn a successful activation into a failed
        # download or remove the newly activated model.
        shutil.rmtree(backup, ignore_errors=True)
    return validate_whisper_model_path(str(destination))


def whisper_model_argument(selection: dict[str, Any] | None = None) -> str:
    selection = selection or get_whisper_selection()

    # A downloaded catalog model must resolve to Clippy's managed directory,
    # not back to a Hub identifier (which can trigger a duplicate download).
    if selection.get("installed") and selection.get("model_path"):
        return selection["model_path"]

    if selection.get("source") == "local":
        raise FileNotFoundError(
            "The selected local Whisper model is unavailable. Open Settings "
            "and choose another model or update its folder path."
        )

    # An undownloaded catalog choice keeps faster-whisper's normal first-use
    # Hub/cache behavior.
    return selection.get("model_size") or "small"


def list_download_tasks() -> dict[str, dict[str, Any]]:
    with _download_lock:
        return {key: dict(value) for key, value in _download_tasks.items()}


def queue_whisper_download(task_id: str, model_size: str) -> int:
    """Queue a download and capture the user's selection revision at request time."""
    if model_size not in WHISPER_MODELS:
        raise ValueError("Unsupported Whisper model size.")

    # Serialize the revision snapshot with explicit selection changes. The
    # background worker may activate its result only while this revision holds.
    with _settings_lock:
        settings = _read_settings()
        revision = _selection_revision(settings.get("whisper"))
        with _download_lock:
            if any(task.get("status") in {"queued", "downloading", "validating"}
                   for task in _download_tasks.values()):
                raise RuntimeError("A Whisper model download is already running.")
            now = time.time()
            _download_tasks[task_id] = {
                "status": "queued",
                "model_size": model_size,
                "message": "Preparing model download…",
                "created_at": now,
                "updated_at": now,
            }
    return revision


def _activate_download_if_selection_is_unchanged(
    model_size: str, model_dir: Path, expected_revision: int | None
) -> bool:
    """Activate a completed download only if no newer user selection was saved."""
    with _settings_lock:
        settings = _read_settings()
        previous = settings.get("whisper", {})
        if not isinstance(previous, dict):
            previous = {}
        current_revision = _selection_revision(previous)
        if expected_revision is not None and current_revision != expected_revision:
            return False

        updated = dict(previous)
        updated.update({
            "model_size": model_size,
            # The catalog path is deterministic from the model size. Keeping
            # model_path empty preserves the catalog identity in the UI and
            # lets the shared resolver discover the managed folder.
            "model_path": None,
            "selection_revision": current_revision + 1,
        })
        settings["whisper"] = updated
        _write_settings(settings)
        return True


def _update_download_task(task_id: str, **changes: Any) -> None:
    with _download_lock:
        task = _download_tasks.get(task_id)
        if task is not None:
            task.update(changes)
            task["updated_at"] = time.time()


def start_whisper_download(
    task_id: str, model_size: str, expected_selection_revision: int | None = None
) -> None:
    _update_download_task(
        task_id,
        status="downloading",
        model_size=model_size,
        message="Downloading model files…",
    )
    staging = None
    try:
        from huggingface_hub import snapshot_download

        destination = models_root() / "whisper" / model_size
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Never download into the path used by transcription workers. A job
        # must see either the previous complete model or the new verified one,
        # never a directory whose model.bin is still being written.
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{model_size}.staging-",
                dir=str(destination.parent),
            )
        )
        snapshot_download(
            repo_id=WHISPER_MODELS[model_size]["repo_id"],
            local_dir=str(staging),
        )

        _update_download_task(
            task_id,
            status="validating",
            message="Download complete. Checking files and testing the model…",
        )
        validate_whisper_model_path(str(staging))
        # Checking filenames and sizes is not enough: prove that the native
        # CTranslate2 loader can open these exact staged weights and transcribe
        # a short deterministic audio sample before they become selectable.
        _verify_whisper_model_directory(str(staging), model_size)

        model_dir = _promote_staged_whisper_model(staging, destination)
        staging = None  # The staging directory was renamed into its final path.
        activated = _activate_download_if_selection_is_unchanged(
            model_size, model_dir, expected_selection_revision
        )
        message = (
            "Model downloaded, load-tested, and selected."
            if activated
            else "Model downloaded and load-tested. Your newer selection was preserved."
        )
        _update_download_task(
            task_id,
            status="complete",
            model_size=model_size,
            model_path=str(model_dir),
            activated=activated,
            message=message,
        )
    except Exception as exc:
        _update_download_task(
            task_id,
            status="failed",
            model_size=model_size,
            message=str(exc)[:500],
        )
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
