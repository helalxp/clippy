"""Durable local project Library for the Clippy desktop application.

The Library is deliberately separate from OUTPUT_DIR: generation jobs remain
scratch workspaces and can be cleaned independently after their deliverables
have been archived.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote
from typing import Any

SCHEMA_VERSION = 1
_PROJECT_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_title(value: str, fallback: str = "Untitled project") -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", " ", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value[:120] or fallback)


def _copy_verified(source: Path, destination: Path) -> None:
    shutil.copy2(source, destination)
    if source.stat().st_size != destination.stat().st_size:
        raise OSError(f"Copied file size verification failed: {source.name}")


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class LocalLibrary:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.projects_dir = self.root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._recover_interrupted_archives()
        self._purge_deleted_projects()
        self._purge_orphan_clip_dirs()
        self._cleanup_interrupted_exports()

    def _recover_interrupted_archives(self) -> None:
        """Recover a previous project if the process stopped during directory swap."""
        for candidate in self.projects_dir.iterdir():
            if not candidate.is_dir() or not candidate.name.startswith("."):
                continue
            match = re.match(r"^\.([0-9a-f-]{36})\.[0-9a-f]+\.(staging|backup)$", candidate.name)
            if not match:
                continue
            project_id, kind = match.groups()
            try:
                age_seconds = time.time() - candidate.stat().st_mtime
            except OSError:
                continue
            # Avoid touching another still-running backend during installer
            # handover. A staging directory is considered abandoned after an
            # hour; a missing project with a backup is restored immediately.
            if kind == "staging" and age_seconds < 3600:
                continue
            try:
                target = self._project_dir(project_id)
            except ValueError:
                shutil.rmtree(candidate, ignore_errors=True)
                continue
            if kind == "backup" and not target.exists() and (candidate / "project.json").is_file():
                try:
                    os.replace(candidate, target)
                    continue
                except OSError:
                    pass
            if age_seconds >= 3600:
                shutil.rmtree(candidate, ignore_errors=True)

    def _project_dir(self, project_id: str) -> Path:
        if not _PROJECT_ID_RE.fullmatch(str(project_id or "")):
            raise ValueError("Invalid project identifier.")
        path = (self.projects_dir / project_id).resolve()
        if path.parent != self.projects_dir.resolve():
            raise ValueError("Project path is outside the Library.")
        return path

    def _purge_deleted_projects(self) -> None:
        for project_id in self._deleted_project_ids():
            try:
                folder = self._project_dir(project_id)
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
            except ValueError:
                continue

    def _cleanup_interrupted_exports(self) -> None:
        """Remove ZIPs left behind if the app stopped before response cleanup."""
        export_dir = self.root / "exports"
        if not export_dir.is_dir():
            return
        cutoff = time.time() - 24 * 60 * 60
        for item in export_dir.iterdir():
            try:
                if item.stat().st_mtime >= cutoff:
                    continue
                if item.is_symlink() or item.is_file():
                    item.unlink(missing_ok=True)
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
            except OSError:
                pass

    def _purge_orphan_clip_dirs(self) -> None:
        """Finish clip deletions that were interrupted after metadata commit."""
        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir() or project_dir.name.startswith(".") or self.is_deleted(project_dir.name):
                continue
            try:
                project = self.get_project(project_dir.name)
            except (ValueError, FileNotFoundError, OSError):
                continue
            clips_root = project_dir / "clips"
            if not clips_root.is_dir() or clips_root.is_symlink():
                continue
            referenced = {item.get("clip_id") for item in project.get("clips", []) if isinstance(item, dict)}
            for child in clips_root.iterdir():
                if child.name in referenced:
                    continue
                try:
                    if child.is_symlink() or child.is_file():
                        child.unlink(missing_ok=True)
                    elif child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                except OSError:
                    pass

    def _deleted_project_ids(self) -> set[str]:
        path = self.root / "deleted_projects.json"
        if not path.is_file():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = payload.get("project_ids", []) if isinstance(payload, dict) else []
            return {value for value in values if isinstance(value, str) and _PROJECT_ID_RE.fullmatch(value)}
        except (OSError, ValueError, TypeError):
            return set()

    def is_deleted(self, project_id: str) -> bool:
        return project_id in self._deleted_project_ids()

    def _mark_project_deleted(self, project_id: str) -> None:
        deleted = self._deleted_project_ids()
        deleted.add(project_id)
        _atomic_json(self.root / "deleted_projects.json", {
            "schema_version": SCHEMA_VERSION,
            "project_ids": sorted(deleted),
            "updated_at": _now(),
        })

    def reserve_project(
        self, job_id: str, fallback_title: str = "Processing project",
        source_path: str | None = None, source_url: str | None = None,
    ) -> dict[str, Any]:
        """Create a durable project record as soon as a generation job is queued."""
        project_id = str(uuid.UUID(job_id))
        if self.is_deleted(project_id):
            raise FileNotFoundError("This project was deleted from the Library.")
        folder = self._project_dir(project_id)
        if (folder / "project.json").is_file():
            return self.get_project(project_id)
        now = _now()
        source_file = Path(source_path).name if source_path else None
        project = {
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
            "title": _safe_title(fallback_title),
            "source_title": _safe_title(fallback_title),
            "title_source": "automatic",
            "source_video": {"filename": source_file, "retained": False, "url": source_url},
            "created_at": now,
            "updated_at": now,
            "status": "queued",
            "clip_count": 0,
            "clips": [],
            "deleted_clip_ids": [],
            "workspace_available": False,
            "storage_size_bytes": 0,
        }
        folder.mkdir(parents=True, exist_ok=True)
        _atomic_json(folder / "project.json", project)
        return self.get_project(project_id)

    def update_project_status(self, project_id: str, status: str) -> dict[str, Any] | None:
        if status not in {"queued", "processing", "failed", "interrupted", "archive_failed"}:
            raise ValueError("Invalid non-terminal project status.")
        try:
            project = self.get_project(project_id)
        except FileNotFoundError:
            return None
        folder = self._project_dir(project_id)
        project["status"] = status
        project["updated_at"] = _now()
        project.pop("storage_path", None)
        _atomic_json(folder / "project.json", project)
        return self.get_project(project_id)

    def mark_interrupted_projects(self, active_job_ids: set[str]) -> int:
        changed = 0
        for folder in self.projects_dir.iterdir():
            if not folder.is_dir() or folder.name.startswith(".") or self.is_deleted(folder.name):
                continue
            try:
                project = self.get_project(folder.name)
            except (ValueError, FileNotFoundError, OSError):
                continue
            if project.get("status") in {"queued", "processing"} and folder.name not in active_job_ids:
                self.update_project_status(folder.name, "interrupted")
                changed += 1
        return changed

    @staticmethod
    def _caption_digest(clip: dict[str, Any]) -> str:
        fields = {
            key: value for key, value in clip.items()
            if any(token in key.lower() for token in ("caption", "description", "hashtag", "title_for_"))
        }
        payload = json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _resolve_original_index(clip: dict[str, Any], index: int, original_shorts: list[Any], used: set[int]) -> int:
        for source_index, source_clip in enumerate(original_shorts):
            if source_index in used or not isinstance(source_clip, dict):
                continue
            if source_clip.get("start") == clip.get("start") and source_clip.get("end") == clip.get("end"):
                return source_index
        return index

    @staticmethod
    def _resolve_clip_file(source_dir: Path, metadata_path: Path, clip: dict[str, Any], original_index: int) -> tuple[Path, str]:
        raw_url = str(clip.get("video_url") or "")
        filename = Path(unquote(raw_url.split("?", 1)[0].rstrip("/").split("/")[-1])).name
        if not filename:
            filename = f"{metadata_path.name[:-len('_metadata.json')]}_clip_{original_index + 1}.mp4"
        candidate = source_dir / filename
        if not candidate.is_file():
            candidate = source_dir / f"{metadata_path.name[:-len('_metadata.json')]}_clip_{original_index + 1}.mp4"
            filename = candidate.name
        return candidate, filename

    def needs_sync(
        self, job_id: str, output_dir: str | Path, job_data: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None, keep_source: bool = False,
    ) -> bool:
        """Return true only when the permanent archive is absent or rendered files changed."""
        try:
            project = self.get_project(job_id)
        except (ValueError, FileNotFoundError):
            return True
        if project.get("status") != "completed":
            return True
        source_dir = Path(output_dir).resolve()
        if not source_dir.is_dir():
            return False
        metadata_files = sorted(source_dir.glob("*_metadata.json"))
        if not metadata_files:
            return False
        metadata_path = metadata_files[0]
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return True
        clips_data = list((result or {}).get("clips") or [])
        if not clips_data:
            clips_data = [dict(item) for item in (metadata.get("shorts") or []) if isinstance(item, dict)]
        original_shorts = metadata.get("shorts") or []
        deleted = set(project.get("deleted_clip_ids", []))
        used: set[int] = set()
        fingerprint = []
        caption_fingerprint = []
        for index, clip in enumerate(clips_data):
            if not isinstance(clip, dict):
                continue
            original_index = self._resolve_original_index(clip, index, original_shorts, used)
            used.add(original_index)
            clip_id = f"{project['project_id']}-{original_index + 1:03d}"
            if clip_id in deleted:
                continue
            candidate, filename = self._resolve_clip_file(source_dir, metadata_path, clip, original_index)
            if not candidate.is_file() or candidate.stat().st_size <= 0:
                return True
            stat = candidate.stat()
            fingerprint.append({
                "index": original_index,
                "filename": filename,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            })
            caption_fingerprint.append({
                "index": original_index,
                "sha256": self._caption_digest(clip),
            })
        if fingerprint != project.get("render_fingerprint", []):
            return True
        if caption_fingerprint != project.get("caption_fingerprint", []):
            return True
        if keep_source and not (project.get("source_video") or {}).get("retained"):
            source_name = Path(str(metadata.get("source_video") or "")).name
            candidates = [source_dir / source_name] if source_name else []
            source_path = (job_data or {}).get("source_path")
            if source_path:
                candidates.append(Path(source_path).expanduser())
            if any(candidate.is_file() for candidate in candidates):
                return True
        return False

    def archive_job(
        self, job_id: str, output_dir: str | Path, job_data: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None, keep_source: bool = False,
    ) -> dict[str, Any]:
        """Archive a completed local job using staging + directory replacement."""
        project_id = str(uuid.UUID(job_id))
        if self.is_deleted(project_id):
            raise FileNotFoundError("This project was deleted from the Library.")
        source_dir = Path(output_dir).resolve()
        if not source_dir.is_dir():
            raise FileNotFoundError("Completed job output directory is missing.")
        metadata_files = sorted(source_dir.glob("*_metadata.json"))
        if not metadata_files:
            raise FileNotFoundError("Completed job metadata is missing.")
        metadata_path = metadata_files[0]
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("Job metadata has an invalid format.")

        project_dir = self._project_dir(project_id)
        existing_project = None
        if (project_dir / "project.json").is_file():
            try:
                existing_project = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                existing_project = None
        metadata_title = _safe_title(metadata_path.name[:-len("_metadata.json")])
        if existing_project and existing_project.get("status") == "completed":
            source_title = _safe_title(existing_project.get("source_title") or metadata_title)
        else:
            source_title = metadata_title
        title_source = (existing_project or {}).get("title_source", "automatic")
        title = _safe_title((existing_project or {}).get("title") if title_source == "user" else source_title)
        source_name = Path(str(metadata.get("source_video") or "")).name
        keep_source = bool(keep_source or (existing_project or {}).get("source_video", {}).get("retained"))
        source_retention_warning = None
        staging = self.projects_dir / f".{project_id}.{uuid.uuid4().hex}.staging"
        backup = self.projects_dir / f".{project_id}.{uuid.uuid4().hex}.backup"
        created = (existing_project or {}).get("created_at") or _now()
        updated = _now()
        clips_data = list((result or {}).get("clips") or [])
        if not clips_data:
            shorts = metadata.get("shorts") or []
            clips_data = [dict(item) for item in shorts if isinstance(item, dict)]

        try:
            (staging / "workspace").mkdir(parents=True)
            (staging / "clips").mkdir()
            # Preserve the job's edit/render workspace but never silently retain
            # the original source when the user's retention preference is OFF.
            for item in source_dir.iterdir():
                if source_name and item.name == source_name:
                    continue
                if item.name.lower().endswith((".zip", ".mp4", ".mov", ".mkv", ".webm")) or item.name.startswith("temp_"):
                    continue
                if item.name.startswith("custom_watermark_upload"):
                    continue
                target = staging / "workspace" / item.name
                if item.is_file():
                    _copy_verified(item, target)
                elif item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)

            if keep_source:
                retained_source = (source_dir / source_name) if source_name else None
                if not retained_source or not retained_source.is_file():
                    candidate = (job_data or {}).get("source_path")
                    retained_source = Path(candidate).expanduser() if candidate else None
                if (not retained_source or not retained_source.is_file()) and existing_project:
                    old_source = (project_dir / "source").resolve()
                    if old_source.is_dir() and old_source.parent == project_dir:
                        candidates = [item for item in old_source.iterdir() if item.is_file()]
                        retained_source = candidates[0] if candidates else None
                if retained_source and retained_source.is_file():
                    (staging / "source").mkdir()
                    archive_source_name = source_name or retained_source.name
                    source_name = archive_source_name
                    try:
                        _copy_verified(retained_source, staging / "source" / archive_source_name)
                    except OSError as source_error:
                        if (existing_project or {}).get("source_video", {}).get("retained"):
                            raise
                        shutil.rmtree(staging / "source", ignore_errors=True)
                        source_retention_warning = f"Original source could not be retained: {source_error}"
                elif keep_source:
                    source_retention_warning = "Original source file was unavailable when this project was archived."

            archived_clips = []
            render_fingerprint = []
            caption_fingerprint = []
            eligible_clip_count = 0
            deleted_clip_ids = set((existing_project or {}).get("deleted_clip_ids", []))
            used_source_indexes: set[int] = set()
            original_shorts = metadata.get("shorts") or []
            for index, clip in enumerate(clips_data):
                if not isinstance(clip, dict):
                    continue
                original_index = self._resolve_original_index(clip, index, original_shorts, used_source_indexes)
                used_source_indexes.add(original_index)
                clip_id = f"{project_id}-{original_index + 1:03d}"
                if clip_id in deleted_clip_ids:
                    continue
                eligible_clip_count += 1
                candidate, filename = self._resolve_clip_file(source_dir, metadata_path, clip, original_index)
                if not candidate.is_file() or candidate.stat().st_size <= 0:
                    raise FileNotFoundError(f"Completed clip file is missing or empty: {candidate.name}")
                stat = candidate.stat()
                render_fingerprint.append({
                    "index": original_index,
                    "filename": filename,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                })
                caption_fingerprint.append({
                    "index": original_index,
                    "sha256": self._caption_digest(clip),
                })
                clip_dir = staging / "clips" / clip_id
                clip_dir.mkdir(parents=True)
                _copy_verified(candidate, clip_dir / "video.mp4")
                caption_fields = {
                    key: value for key, value in clip.items()
                    if any(token in key.lower() for token in ("caption", "description", "hashtag", "title_for_"))
                }
                caption_file = clip_dir / "captions.json"
                _atomic_json(caption_file, {
                    "schema_version": SCHEMA_VERSION,
                    "clip_id": clip_id,
                    "platforms": {
                        "youtube": {
                            "title": clip.get("video_title_for_youtube_short", ""),
                            "caption": clip.get("video_description_for_youtube", ""),
                            "hashtags": clip.get("youtube_hashtags", []),
                        },
                        "instagram": {
                            "caption": clip.get("video_description_for_instagram", ""),
                            "hashtags": clip.get("instagram_hashtags", []),
                        },
                        "tiktok": {
                            "caption": clip.get("video_description_for_tiktok", ""),
                            "hashtags": clip.get("tiktok_hashtags", []),
                        },
                    },
                    "source_fields": caption_fields,
                })
                archived_clips.append({
                    "clip_id": clip_id,
                    "index": original_index,
                    "title": clip.get("video_title_for_youtube_short") or f"Clip {original_index + 1}",
                    "filename": filename,
                    "video_path": f"clips/{clip_id}/video.mp4",
                    "captions_path": f"clips/{clip_id}/captions.json",
                    "start": clip.get("start"),
                    "end": clip.get("end"),
                    "why": clip.get("why", ""),
                })
                # A Library caption edit is user-authored data. Re-archiving
                # newer rendered media must not overwrite those saved variants.
                if existing_project:
                    old_clip = next((item for item in existing_project.get("clips", [])
                                     if item.get("clip_id") == clip_id), None)
                    if old_clip:
                        old_caption = (project_dir / old_clip.get("captions_path", "")).resolve()
                        if old_caption.is_relative_to(project_dir) and old_caption.is_file():
                            try:
                                old_caption_data = json.loads(old_caption.read_text(encoding="utf-8"))
                            except (OSError, ValueError):
                                old_caption_data = {}
                            if old_caption_data.get("user_edited"):
                                _copy_verified(old_caption, caption_file)

            if not archived_clips and (eligible_clip_count or not existing_project):
                raise ValueError("No completed clip files could be archived.")

            project = {
                "schema_version": SCHEMA_VERSION,
                "project_id": project_id,
                "title": title,
                "source_title": source_title,
                "title_source": title_source,
                "source_video": {
                    "filename": source_name or None,
                    "retained": bool(keep_source and source_name and (staging / "source" / source_name).is_file()),
                    "retention_warning": source_retention_warning if keep_source else None,
                    "url": (job_data or {}).get("source_url"),
                },
                "created_at": created,
                "updated_at": updated,
                "status": "completed",
                "clip_count": len(archived_clips),
                "clips": archived_clips,
                "deleted_clip_ids": sorted(deleted_clip_ids),
                "render_fingerprint": render_fingerprint,
                "caption_fingerprint": caption_fingerprint,
                "workspace_available": (staging / "workspace").is_dir(),
            }
            _atomic_json(staging / "project.json", project)

            with _LOCK:
                # Deletion may race with a long archive copy. Re-check the
                # tombstone while holding the same lock used by delete_project
                # so an in-flight archive cannot publish a deleted project.
                if self.is_deleted(project_id):
                    raise FileNotFoundError("This project was deleted from the Library.")
                if project_dir.exists():
                    os.replace(project_dir, backup)
                try:
                    os.replace(staging, project_dir)
                except Exception:
                    if backup.exists() and not project_dir.exists():
                        os.replace(backup, project_dir)
                    raise
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
            project["storage_size_bytes"] = self.project_size(project_id)
            _atomic_json(project_dir / "project.json", project)
            return self.get_project(project_id)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def get_settings(self) -> dict[str, Any]:
        path = self.root / "library_settings.json"
        if not path.is_file():
            return {"keep_source_default": False}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {"keep_source_default": bool(data.get("keep_source_default", False))}
        except (OSError, ValueError, TypeError):
            return {"keep_source_default": False}

    def update_settings(self, keep_source_default: bool) -> dict[str, Any]:
        if not isinstance(keep_source_default, bool):
            raise ValueError("keep_source_default must be a boolean.")
        data = {"schema_version": SCHEMA_VERSION, "keep_source_default": keep_source_default, "updated_at": _now()}
        _atomic_json(self.root / "library_settings.json", data)
        return self.get_settings()

    def list_projects(self) -> list[dict[str, Any]]:
        projects = []
        for folder in self.projects_dir.iterdir():
            if not folder.is_dir() or folder.name.startswith("."):
                continue
            try:
                if self.is_deleted(folder.name):
                    continue
                project = json.loads((folder / "project.json").read_text(encoding="utf-8"))
                project["storage_path"] = str(folder)
                project["storage_size_bytes"] = int(project.get("storage_size_bytes") or 0)
                projects.append(project)
            except (OSError, ValueError, TypeError):
                continue
        return sorted(projects, key=lambda item: item.get("updated_at", ""), reverse=True)

    def get_project(self, project_id: str) -> dict[str, Any]:
        folder = self._project_dir(project_id)
        if self.is_deleted(project_id):
            raise FileNotFoundError("Project was deleted.")
        project_file = folder / "project.json"
        if not project_file.is_file():
            raise FileNotFoundError("Project not found.")
        project = json.loads(project_file.read_text(encoding="utf-8"))
        project["storage_path"] = str(folder)
        return project

    def rename_project(self, project_id: str, title: str) -> dict[str, Any]:
        folder = self._project_dir(project_id)
        project = self.get_project(project_id)
        project["title"] = _safe_title(title)
        project["title_source"] = "user"
        project["updated_at"] = _now()
        project.pop("storage_path", None)
        project["storage_size_bytes"] = self.project_size(project_id)
        _atomic_json(folder / "project.json", project)
        return self.get_project(project_id)

    def update_captions(self, project_id: str, clip_id: str, platforms: dict[str, Any]) -> dict[str, Any]:
        project = self.get_project(project_id)
        clip = next((c for c in project.get("clips", []) if c.get("clip_id") == clip_id), None)
        if not clip:
            raise FileNotFoundError("Clip not found.")
        allowed = {"youtube", "instagram", "tiktok"}
        if not isinstance(platforms, dict) or set(platforms) - allowed:
            raise ValueError("Invalid platform caption data.")
        folder = self._project_dir(project_id)
        caption_path = (folder / clip["captions_path"]).resolve()
        if not caption_path.is_relative_to(folder):
            raise ValueError("Caption path is outside the project.")
        existing = json.loads(caption_path.read_text(encoding="utf-8"))
        normalized = {}
        for platform in allowed:
            value = platforms.get(platform, existing.get("platforms", {}).get(platform, {}))
            if not isinstance(value, dict):
                raise ValueError("Each platform caption must be an object.")
            clean = {}
            for field in ("title", "caption"):
                text_value = value.get(field, "")
                if not isinstance(text_value, str) or len(text_value) > 5000:
                    raise ValueError(f"{field} must be text up to 5000 characters.")
                clean[field] = text_value
            tags = value.get("hashtags", [])
            if isinstance(tags, str):
                tags = tags.split()
            if not isinstance(tags, list) or len(tags) > 50 or any(not isinstance(tag, str) or len(tag) > 100 for tag in tags):
                raise ValueError("Hashtags must be a list of up to 50 short text values.")
            clean["hashtags"] = tags
            normalized[platform] = clean
        existing["platforms"] = normalized
        existing["user_edited"] = True
        existing["updated_at"] = _now()
        _atomic_json(caption_path, existing)
        project["updated_at"] = _now()
        project.pop("storage_path", None)
        project["storage_size_bytes"] = self.project_size(project_id)
        _atomic_json(folder / "project.json", project)
        return existing

    def delete_project(self, project_id: str) -> None:
        folder = self._project_dir(project_id)
        # Serialize tombstone creation and physical removal with archive publish.
        # The tombstone is written first so a crash cannot make the project reappear.
        with _LOCK:
            self._mark_project_deleted(project_id)
            if folder.exists():
                shutil.rmtree(folder)

    def delete_clip(self, project_id: str, clip_id: str) -> dict[str, Any]:
        folder = self._project_dir(project_id)
        project = self.get_project(project_id)
        clip = next((item for item in project.get("clips", []) if item.get("clip_id") == clip_id), None)
        if not clip:
            raise FileNotFoundError("Clip not found.")
        clip_dir = (folder / "clips" / clip_id).resolve()
        if not clip_dir.is_relative_to(folder / "clips"):
            raise ValueError("Clip path is outside the project.")
        # Commit the logical deletion first. If the process stops before media
        # cleanup, startup removes the now-unreferenced clip directory.
        project["clips"] = [item for item in project.get("clips", []) if item.get("clip_id") != clip_id]
        deleted_clip_ids = set(project.get("deleted_clip_ids", []))
        deleted_clip_ids.add(clip_id)
        project["deleted_clip_ids"] = sorted(deleted_clip_ids)
        project["render_fingerprint"] = [
            item for item in project.get("render_fingerprint", [])
            if item.get("index") != clip.get("index")
        ]
        project["caption_fingerprint"] = [
            item for item in project.get("caption_fingerprint", [])
            if item.get("index") != clip.get("index")
        ]
        project["clip_count"] = len(project["clips"])
        project["updated_at"] = _now()
        project.pop("storage_path", None)
        _atomic_json(folder / "project.json", project)
        if clip_dir.exists():
            try:
                shutil.rmtree(clip_dir)
            except OSError:
                pass
        project["storage_size_bytes"] = self.project_size(project_id)
        _atomic_json(folder / "project.json", project)
        return self.get_project(project_id)

    def clip_path(self, project_id: str, clip_id: str) -> Path:
        project = self.get_project(project_id)
        clip = next((c for c in project.get("clips", []) if c.get("clip_id") == clip_id), None)
        if not clip:
            raise FileNotFoundError("Clip not found.")
        path = (self._project_dir(project_id) / clip["video_path"]).resolve()
        if not path.is_relative_to(self._project_dir(project_id)):
            raise ValueError("Clip path is outside the project.")
        if not path.is_file():
            raise FileNotFoundError("Archived clip file is missing.")
        return path

    def project_size(self, project_id: str) -> int:
        folder = self._project_dir(project_id)
        total = 0
        for path in folder.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        return total
