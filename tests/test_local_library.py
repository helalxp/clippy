import json
import os
import time
import uuid
import zipfile

import pytest

from local_library import LocalLibrary


JOB_ID = "12345678-1234-5678-9abc-1234567890ab"


def make_job(tmp_path, job_id=JOB_ID):
    output = tmp_path / "output" / job_id
    output.mkdir(parents=True)
    (output / "source.mp4").write_bytes(b"original-source")
    (output / "video_clip_1.mp4").write_bytes(b"rendered-clip")
    metadata = {
        "source_video": "source.mp4",
        "shorts": [{
            "start": 1.0,
            "end": 8.0,
            "video_title_for_youtube_short": "A short title",
            "video_description_for_instagram": "Instagram copy",
            "video_description_for_tiktok": "TikTok copy",
        }],
        "transcript": {"segments": []},
    }
    (output / "video_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    result = {"clips": [{
        **metadata["shorts"][0],
        "video_url": f"/videos/{job_id}/video_clip_1.mp4",
    }]}
    return output, result


def test_archive_creates_project_and_keeps_source_off_by_default(tmp_path):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")

    project = library.archive_job(JOB_ID, output, {}, result, keep_source=False)

    assert project["project_id"] == JOB_ID
    assert project["title"] == "video"
    assert project["clip_count"] == 1
    assert project["source_video"]["retained"] is False
    project_dir = library._project_dir(JOB_ID)
    assert (project_dir / "clips" / f"{JOB_ID}-001" / "video.mp4").read_bytes() == b"rendered-clip"
    assert not (project_dir / "source" / "source.mp4").exists()
    assert not (project_dir / "workspace" / "source.mp4").exists()
    assert (project_dir / "workspace" / "video_metadata.json").is_file()


def test_archive_can_retain_source_when_explicitly_enabled(tmp_path):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")

    project = library.archive_job(JOB_ID, output, {}, result, keep_source=True)

    assert project["source_video"]["retained"] is True
    assert (library._project_dir(JOB_ID) / "source" / "source.mp4").read_bytes() == b"original-source"


def test_rename_caption_update_and_delete(tmp_path):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    library.archive_job(JOB_ID, output, {}, result)

    renamed = library.rename_project(JOB_ID, "My renamed project")
    assert renamed["title"] == "My renamed project"

    clip_id = renamed["clips"][0]["clip_id"]
    updated = library.update_captions(JOB_ID, clip_id, {
        "youtube": {"title": "New title", "caption": "YT copy", "hashtags": ["#shorts"]},
        "instagram": {"caption": "IG copy", "hashtags": ["#reels"]},
        "tiktok": {"caption": "TT copy", "hashtags": ["#fyp"]},
    })
    assert updated["platforms"]["youtube"]["title"] == "New title"
    assert updated["platforms"]["instagram"]["caption"] == "IG copy"

    assert library.clip_path(JOB_ID, clip_id).read_bytes() == b"rendered-clip"
    assert library.project_size(JOB_ID) > 0
    after_clip_delete = library.delete_clip(JOB_ID, clip_id)
    assert after_clip_delete["clip_count"] == 0
    # Syncing the active generation job must not resurrect a user-deleted clip.
    synced = library.archive_job(JOB_ID, output, {}, result)
    assert synced["clip_count"] == 0
    with pytest.raises(FileNotFoundError):
        library.clip_path(JOB_ID, clip_id)
    library.delete_project(JOB_ID)
    assert library.list_projects() == []
    with pytest.raises(FileNotFoundError):
        library.archive_job(JOB_ID, output, {}, result)


def test_rejects_invalid_project_and_clip_paths(tmp_path):
    library = LocalLibrary(tmp_path / "library")
    with pytest.raises(ValueError):
        library.get_project("../../outside")
    with pytest.raises(FileNotFoundError):
        library.clip_path(str(uuid.uuid4()), "anything")



def test_rearchive_preserves_user_title_and_caption_edits(tmp_path):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    first = library.archive_job(JOB_ID, output, {}, result)
    clip_id = first["clips"][0]["clip_id"]
    assert library.needs_sync(JOB_ID, output, {}, result) is False
    library.rename_project(JOB_ID, "User project name")
    library.update_captions(JOB_ID, clip_id, {
        "youtube": {"title": "Edited title", "caption": "Saved copy", "hashtags": []},
    })

    (output / "video_clip_1.mp4").write_bytes(b"newly-edited-render")
    assert library.needs_sync(JOB_ID, output, {}, result) is True
    library.archive_job(JOB_ID, output, {}, result)
    assert library.needs_sync(JOB_ID, output, {}, result) is False

    project = library.get_project(JOB_ID)
    saved_captions = json.loads((library._project_dir(JOB_ID) / project["clips"][0]["captions_path"]).read_text())
    assert project["title"] == "User project name"
    assert project["clips"][0]["clip_id"] == clip_id
    assert saved_captions["platforms"]["youtube"]["title"] == "Edited title"
    assert library.clip_path(JOB_ID, clip_id).read_bytes() == b"newly-edited-render"


def test_recovers_backup_after_interrupted_archive_swap(tmp_path):
    library_root = tmp_path / "library"
    backup = library_root / "projects" / f".{JOB_ID}.abc.backup"
    backup.mkdir(parents=True)
    (backup / "project.json").write_text(json.dumps({
        "schema_version": 1,
        "project_id": JOB_ID,
        "title": "Recovered project",
        "created_at": "2026-01-01T00:00:00+00:00",
        "clips": [],
        "clip_count": 0,
    }), encoding="utf-8")

    recovered = LocalLibrary(library_root)
    assert recovered.get_project(JOB_ID)["title"] == "Recovered project"
    assert not backup.exists()


def test_failed_archive_does_not_publish_partial_project(tmp_path):
    output, result = make_job(tmp_path)
    (output / "video_clip_1.mp4").unlink()
    library = LocalLibrary(tmp_path / "library")

    with pytest.raises(FileNotFoundError):
        library.archive_job(JOB_ID, output, {}, result)

    assert library.list_projects() == []
    assert not any(item.name.startswith(f".{JOB_ID}.") for item in library.projects_dir.iterdir())



def test_source_retention_setting_defaults_off_and_persists(tmp_path):
    library = LocalLibrary(tmp_path / "library")
    assert library.get_settings()["keep_source_default"] is False
    assert library.update_settings(True)["keep_source_default"] is True
    assert LocalLibrary(tmp_path / "library").get_settings()["keep_source_default"] is True


def test_source_can_be_copied_from_upload_storage(tmp_path):
    output, result = make_job(tmp_path)
    (output / "source.mp4").unlink()
    uploaded_source = tmp_path / "uploads" / "source.mp4"
    uploaded_source.parent.mkdir()
    uploaded_source.write_bytes(b"user-original")
    library = LocalLibrary(tmp_path / "library")

    project = library.archive_job(
        JOB_ID, output, {"source_path": str(uploaded_source)}, result, keep_source=True,
    )

    assert project["source_video"]["retained"] is True
    archived = library._project_dir(JOB_ID) / "source" / "source.mp4"
    assert archived.read_bytes() == b"user-original"
    assert uploaded_source.read_bytes() == b"user-original"



def test_project_is_reserved_before_generation_and_auto_named_on_completion(tmp_path):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")

    reserved = library.reserve_project(JOB_ID, "Processing YouTube video")
    assert reserved["status"] == "queued"
    assert reserved["clip_count"] == 0

    library.update_project_status(JOB_ID, "processing")
    completed = library.archive_job(JOB_ID, output, {}, result)
    assert completed["status"] == "completed"
    assert completed["title"] == "video"
    assert completed["source_title"] == "video"


def test_user_rename_during_generation_survives_auto_title_resolution(tmp_path):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    library.reserve_project(JOB_ID, "Processing YouTube video")
    library.rename_project(JOB_ID, "My chosen project")

    completed = library.archive_job(JOB_ID, output, {}, result)
    assert completed["title"] == "My chosen project"
    assert completed["source_title"] == "video"
    assert completed["title_source"] == "user"


def test_queued_project_becomes_interrupted_when_not_resumed(tmp_path):
    library = LocalLibrary(tmp_path / "library")
    library.reserve_project(JOB_ID, "Queued project")
    changed = library.mark_interrupted_projects(set())

    assert changed == 1
    assert library.get_project(JOB_ID)["status"] == "interrupted"



def test_startup_cleans_clip_media_left_after_metadata_delete(tmp_path):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    project = library.archive_job(JOB_ID, output, {}, result)
    clip_id = project["clips"][0]["clip_id"]
    clip_dir = library._project_dir(JOB_ID) / "clips" / clip_id
    metadata_path = library._project_dir(JOB_ID) / "project.json"
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    data["clips"] = []
    data["clip_count"] = 0
    data["deleted_clip_ids"] = [clip_id]
    metadata_path.write_text(json.dumps(data), encoding="utf-8")

    LocalLibrary(tmp_path / "library")
    assert not clip_dir.exists()


def test_startup_cleans_abandoned_project_exports(tmp_path):
    exports = tmp_path / "library" / "exports"
    exports.mkdir(parents=True)
    stale_zip = exports / "abandoned.zip"
    stale_zip.write_bytes(b"partial")
    old_time = time.time() - 25 * 60 * 60
    os.utime(stale_zip, (old_time, old_time))

    LocalLibrary(tmp_path / "library")
    assert not stale_zip.exists()



def test_source_retention_is_snapshotted_per_project(tmp_path):
    library = LocalLibrary(tmp_path / "library")
    first_source = tmp_path / "first-source.mp4"
    first_source.write_bytes(b"source-video-one")
    library.update_settings(True)
    first_output, first_result = make_job(tmp_path)
    library.reserve_project(JOB_ID, "First project", source_path=str(first_source))
    library.update_settings(False)
    first = library.archive_job(JOB_ID, first_output, {"source_path": str(first_source)}, first_result)
    assert first["source_video"]["retention_requested"] is True
    assert first["source_video"]["retained"] is True
    assert (library._project_dir(JOB_ID) / "source" / first_source.name).read_bytes() == b"source-video-one"

    second_id = "22345678-1234-5678-9abc-1234567890ab"
    second_source = tmp_path / "second-source.mp4"
    second_source.write_bytes(b"source-video-two")
    second_output, second_result = make_job(tmp_path, second_id)
    library.reserve_project(second_id, "Second project", source_path=str(second_source))
    library.update_settings(True)
    second = library.archive_job(second_id, second_output, {"source_path": str(second_source)}, second_result)
    assert second["source_video"]["retention_requested"] is False
    assert second["source_video"]["retained"] is False
    assert not (library._project_dir(second_id) / "source").exists()
    assert library.needs_sync(second_id, second_output, {}, second_result) is False


def test_legacy_project_without_retention_snapshot_defaults_to_existing_state(tmp_path):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    library.archive_job(JOB_ID, output, {}, result)
    project_file = library._project_dir(JOB_ID) / "project.json"
    metadata = json.loads(project_file.read_text(encoding="utf-8"))
    metadata["source_video"].pop("retention_requested", None)
    project_file.write_text(json.dumps(metadata), encoding="utf-8")
    library.update_settings(True)
    synced = library.archive_job(JOB_ID, output, {}, result, keep_source=True)
    assert synced["source_video"]["retention_requested"] is False
    assert synced["source_video"]["retained"] is False



def test_caption_changes_sync_until_user_edits_library_caption(tmp_path):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    first = library.archive_job(JOB_ID, output, {}, result)
    clip_id = first["clips"][0]["clip_id"]

    changed_result = {"clips": [{**result["clips"][0], "video_description_for_instagram": "Updated source caption"}]}
    assert library.needs_sync(JOB_ID, output, {}, changed_result) is True
    library.archive_job(JOB_ID, output, {}, changed_result)
    project = library.get_project(JOB_ID)
    caption_path = library._project_dir(JOB_ID) / project["clips"][0]["captions_path"]
    captions = json.loads(caption_path.read_text(encoding="utf-8"))
    assert captions["platforms"]["instagram"]["caption"] == "Updated source caption"

    library.update_captions(JOB_ID, clip_id, {
        "youtube": {"title": "", "caption": "", "hashtags": []},
        "instagram": {"caption": "My Library edit", "hashtags": []},
        "tiktok": {"caption": "", "hashtags": []},
    })
    newer_result = {"clips": [{**changed_result["clips"][0], "video_description_for_instagram": "New generator caption"}]}
    assert library.needs_sync(JOB_ID, output, {}, newer_result) is True
    library.archive_job(JOB_ID, output, {}, newer_result)
    project = library.get_project(JOB_ID)
    caption_path = library._project_dir(JOB_ID) / project["clips"][0]["captions_path"]
    captions = json.loads(caption_path.read_text(encoding="utf-8"))
    assert captions["platforms"]["instagram"]["caption"] == "My Library edit"



def test_missing_optional_source_does_not_block_clip_archival(tmp_path):
    output, result = make_job(tmp_path)
    (output / "source.mp4").unlink()
    library = LocalLibrary(tmp_path / "library")

    project = library.archive_job(JOB_ID, output, {}, result, keep_source=True)

    assert project["clip_count"] == 1
    assert project["source_video"]["retained"] is False
    assert project["source_video"]["retention_warning"]



def test_project_deleted_during_archive_cannot_be_published(tmp_path, monkeypatch):
    import local_library as library_module

    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    original_copy = library_module._copy_verified
    deleted_during_copy = False

    def delete_then_copy(source, destination):
        nonlocal deleted_during_copy
        if not deleted_during_copy:
            deleted_during_copy = True
            library.delete_project(JOB_ID)
        return original_copy(source, destination)

    monkeypatch.setattr(library_module, "_copy_verified", delete_then_copy)

    with pytest.raises(FileNotFoundError, match="deleted from the Library"):
        library.archive_job(JOB_ID, output, {}, result)

    assert deleted_during_copy is True
    assert library.is_deleted(JOB_ID) is True
    assert not library._project_dir(JOB_ID).exists()
    assert not any(item.name.startswith(f".{JOB_ID}.") for item in library.projects_dir.iterdir())



def test_project_and_clip_thumbnails_are_generated_and_exposed(tmp_path, monkeypatch):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    def fake_thumbnail(source, destination):
        destination.write_bytes(b"jpeg-preview")
        return True
    monkeypatch.setattr(library, "_create_thumbnail", fake_thumbnail)
    project = library.archive_job(JOB_ID, output, {}, result)
    clip = project["clips"][0]
    assert project["thumbnail_url"] == f"/api/library/projects/{JOB_ID}/thumbnail"
    assert clip["thumbnail_url"] == f"/api/library/projects/{JOB_ID}/clips/{clip['clip_id']}/thumbnail"
    assert library.project_thumbnail_path(JOB_ID).read_bytes() == b"jpeg-preview"
    assert library.clip_thumbnail_path(JOB_ID, clip["clip_id"]).read_bytes() == b"jpeg-preview"


def test_thumbnail_failure_does_not_fail_archive(tmp_path, monkeypatch):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    monkeypatch.setattr(library, "_create_thumbnail", lambda source, destination: False)
    project = library.archive_job(JOB_ID, output, {}, result)
    assert project["clip_count"] == 1
    assert "thumbnail_url" not in project
    assert "thumbnail_url" not in project["clips"][0]


def test_project_zip_contains_only_light_portable_deliverables(tmp_path, monkeypatch):
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    monkeypatch.setattr(library, "_create_thumbnail", lambda source, destination: False)
    library.archive_job(JOB_ID, output, {}, result, keep_source=True)
    destination = tmp_path / "exports" / "project.zip"
    library.export_project_zip(JOB_ID, destination)
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert len(names) == 3
        manifest_name = next(name for name in names if name.endswith("/project.json"))
        manifest = json.loads(archive.read(manifest_name))
        captions_name = next(name for name in names if name.endswith("/captions/clip-001.json"))
        captions = json.loads(archive.read(captions_name))
    assert any(name.endswith("/clips/clip-001.mp4") for name in names)
    assert not any("/source/" in name or "/workspace/" in name for name in names)
    assert str(library.root) not in json.dumps(manifest)
    assert "storage_path" not in manifest and "source_fields" not in captions
    assert captions["platforms"]["instagram"]["caption"] == "Instagram copy"


def test_archive_preserves_user_rename_and_caption_edits_during_copy(tmp_path, monkeypatch):
    import local_library as module
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    first = library.archive_job(JOB_ID, output, {}, result)
    clip_id = first["clips"][0]["clip_id"]
    (output / "video_clip_1.mp4").write_bytes(b"new-rendered-clip")
    original_copy = module._copy_verified
    edited = False
    def mutate_during_copy(source, destination):
        nonlocal edited
        if destination.name == "video.mp4" and not edited:
            edited = True
            library.rename_project(JOB_ID, "Renamed during archive")
            library.update_captions(JOB_ID, clip_id, {"instagram": {"caption": "Concurrent edit", "hashtags": ["#saved"]}})
        return original_copy(source, destination)
    monkeypatch.setattr(module, "_copy_verified", mutate_during_copy)
    updated = library.archive_job(JOB_ID, output, {}, result)
    caption_file = library._project_dir(JOB_ID) / updated["clips"][0]["captions_path"]
    caption_data = json.loads(caption_file.read_text(encoding="utf-8"))
    assert edited and updated["title"] == "Renamed during archive"
    assert caption_data["platforms"]["instagram"]["caption"] == "Concurrent edit"
    assert library.clip_path(JOB_ID, clip_id).read_bytes() == b"new-rendered-clip"


def test_clip_deleted_during_archive_is_not_restored(tmp_path, monkeypatch):
    import local_library as module
    output, result = make_job(tmp_path)
    library = LocalLibrary(tmp_path / "library")
    clip_id = library.archive_job(JOB_ID, output, {}, result)["clips"][0]["clip_id"]
    (output / "video_clip_1.mp4").write_bytes(b"new-rendered-clip")
    original_copy = module._copy_verified
    deleted = False
    def delete_during_copy(source, destination):
        nonlocal deleted
        if destination.name == "video.mp4" and not deleted:
            deleted = True
            library.delete_clip(JOB_ID, clip_id)
        return original_copy(source, destination)
    monkeypatch.setattr(module, "_copy_verified", delete_during_copy)
    updated = library.archive_job(JOB_ID, output, {}, result)
    assert deleted and updated["clip_count"] == 0
    assert clip_id in updated["deleted_clip_ids"]
    with pytest.raises(FileNotFoundError):
        library.clip_path(JOB_ID, clip_id)
