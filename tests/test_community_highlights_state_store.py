import json
import community_highlights.state_store as state_store_module

import pytest

from community_highlights.state_store import (
    CommunityHighlightsStateStore,
    StateStoreError,
)


def test_state_sections_survive_store_recreation(tmp_path):
    store = CommunityHighlightsStateStore(tmp_path)
    trigger_settings = {
        "phrases": ["clip it"],
        "min_messages": 1,
        "min_unique_users": 1,
        "window_seconds": 5,
        "cooldown_seconds": 10,
        "pre_seconds": 12,
        "post_seconds": 18,
    }
    sessions = [{"session_id": "session_12345678901234567890", "status": "recording"}]
    candidates = [{"candidate_id": "candidate_12345678901234567890", "review_status": "approved"}]

    store.update_sections(
        trigger_settings=trigger_settings,
        capture_sessions=sessions,
        candidates=candidates,
    )

    restored = CommunityHighlightsStateStore(tmp_path).read()
    assert restored["schema_version"] == 1
    assert restored["trigger_settings"] == trigger_settings
    assert restored["capture_sessions"] == sessions
    assert restored["candidates"] == candidates
    assert restored["updated_at"]


def test_corrupt_state_is_preserved_before_store_recovers_empty_state(tmp_path):
    store = CommunityHighlightsStateStore(tmp_path)
    store.directory.mkdir(parents=True)
    store.path.write_text('{"schema_version": 1, "candidates": [', encoding="utf-8")

    recovered = store.read()

    assert recovered["candidates"] == []
    assert not store.path.exists()
    backups = list(store.directory.glob("state.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"schema_version": 1, "candidates": ['


def test_newer_state_schema_is_not_quarantined_or_overwritten(tmp_path):
    store = CommunityHighlightsStateStore(tmp_path)
    store.directory.mkdir(parents=True)
    payload = {"schema_version": 999, "candidates": [{"future": True}]}
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(StateStoreError, match="newer Clippy version"):
        store.read()

    assert json.loads(store.path.read_text(encoding="utf-8")) == payload


def test_state_store_rejects_symlinked_state_file(tmp_path):
    store = CommunityHighlightsStateStore(tmp_path)
    store.directory.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        store.path.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("This Windows environment does not grant symlink creation.")

    with pytest.raises(StateStoreError, match="not a regular file"):
        store.read()

    assert outside.read_text(encoding="utf-8") == "{}"

def test_default_state_store_rejects_symlinked_data_directory(tmp_path, monkeypatch):
    real_root = tmp_path / "real-data"
    real_root.mkdir()
    linked_root = tmp_path / "linked-data"
    try:
        linked_root.symlink_to(real_root, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("This Windows environment does not grant symlink creation.")

    monkeypatch.setenv("CLIPPY_DATA_DIR", str(linked_root))
    monkeypatch.setattr(state_store_module, "_DEFAULT_STORE", None)

    with pytest.raises(StateStoreError, match="symbolic link"):
        state_store_module.get_state_store()
