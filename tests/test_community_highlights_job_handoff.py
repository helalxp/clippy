import asyncio
import itertools
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from community_highlights.capture_sessions import CaptureSessionManager, HighlightCandidate
from community_highlights.diagnostics import log_event

app_module = pytest.importorskip("app")


class MemoryStateStore:
    def __init__(self):
        self.state = {
            "trigger_settings": None,
            "capture_sessions": [],
            "candidates": [],
        }

    def read(self):
        return {
            **self.state,
            "capture_sessions": list(self.state["capture_sessions"]),
            "candidates": [dict(row) for row in self.state["candidates"]],
        }

    def update_sections(self, **sections):
        self.state.update(sections)


class FakeCandidateManager:
    def __init__(self, source_path):
        self.source_path = Path(source_path)
        self.snapshot = {
            "candidate_id": "candidate_12345678901234567890",
            "capture_session_id": "session_12345678901234567890",
            "status": "ready",
            "review_status": "pending",
            "generation_status": "not_started",
            "generation_job_id": None,
            "generation_error": None,
        }

    def get_candidate_generation(self, candidate_id):
        return dict(self.snapshot) if candidate_id == self.snapshot["candidate_id"] else None

    def claim_candidate_generation(self, candidate_id, job_id):
        if candidate_id != self.snapshot["candidate_id"]:
            raise KeyError("Highlight candidate not found.")
        if self.snapshot["status"] != "ready" or self.snapshot["review_status"] == "rejected":
            raise ValueError("Only a completed, non-rejected highlight can be generated.")
        if self.snapshot["generation_status"] in {"staging", "queued", "processing", "completed"}:
            return dict(self.snapshot), None, False
        self.snapshot.update({
            "review_status": "approved",
            "generation_status": "staging",
            "generation_job_id": job_id,
            "generation_error": None,
        })
        return dict(self.snapshot), self.source_path, True

    def update_candidate_generation(self, candidate_id, job_id, *, status, error=None):
        if candidate_id != self.snapshot["candidate_id"] or job_id != self.snapshot["generation_job_id"]:
            return None
        self.snapshot.update(generation_status=status, generation_error=error)
        return dict(self.snapshot)

    def list_candidates(self):
        return [dict(self.snapshot)]


def _post_process(body):
    async def _do():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/api/process",
                json=body,
                headers={"X-Gemini-Key": "test-key"},
            )
    return asyncio.run(_do())


@pytest.fixture()
def handoff(tmp_path, monkeypatch):
    output_root = tmp_path / "output"
    upload_root = tmp_path / "uploads"
    source = (
        tmp_path
        / "community-highlights"
        / "session_12345678901234567890"
        / "highlights"
        / "candidate_12345678901234567890.mp4"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original-highlight-mp4")

    manager = FakeCandidateManager(source)
    queued = []
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(output_root))
    monkeypatch.setattr(app_module, "UPLOAD_DIR", str(upload_root))
    monkeypatch.setattr(app_module, "capture_sessions", manager)
    monkeypatch.setattr(app_module, "BILLING_ENABLED", False)
    monkeypatch.setattr(app_module, "jobs", {})
    monkeypatch.setattr(app_module, "_job_seq", itertools.count())
    monkeypatch.setattr(app_module, "_assert_data_storage_available", lambda: None)
    monkeypatch.setattr(app_module, "resolve_gemini", lambda _request: _async_value("test-key"))
    monkeypatch.setattr(app_module, "child_env", lambda: {})
    monkeypatch.setattr(app_module, "layout_env", lambda _layouts: {})
    monkeypatch.setattr(app_module, "_media_duration_seconds", lambda _path: 120.0)
    monkeypatch.setattr(app_module, "MIN_SOURCE_SECONDS", 0)

    async def reserve(*_args, **_kwargs):
        return None, 2, None, "self_host", None

    monkeypatch.setattr(app_module, "reserve_process_minutes", reserve)
    monkeypatch.setattr(
        app_module.local_library,
        "reserve_project",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        app_module,
        "_enqueue_job",
        lambda job_id, priority: queued.append((job_id, priority)),
    )
    return output_root, upload_root, source, manager, queued


async def _async_value(value):
    return value


def test_approved_candidate_enters_normal_one_clip_vertical_job(handoff):
    output_root, upload_root, original, manager, queued = handoff

    response = _post_process({
        "community_candidate_id": manager.snapshot["candidate_id"],
        "acknowledged": True,
    })

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["community_highlight"] is True
    job_id = payload["job_id"]
    job = app_module.jobs[job_id]

    input_path = Path(job["cmd"][job["cmd"].index("-i") + 1])
    assert input_path.parent == upload_root
    assert input_path.is_file()
    assert input_path.read_bytes() == original.read_bytes()
    assert original.read_bytes() == b"original-highlight-mp4"

    assert job["cmd"][job["cmd"].index("--format") + 1] == "vertical"
    assert job["env"]["CLIP_TARGET_MIN"] == "1"
    assert job["env"]["CLIP_TARGET_MAX"] == "1"
    assert job["attestation"]["source"] == "community_highlights"
    assert job["community_candidate_id"] == manager.snapshot["candidate_id"]

    manifest = json.loads((output_root / job_id / ".resume.json").read_text(encoding="utf-8"))
    assert manifest["community_candidate_id"] == manager.snapshot["candidate_id"]
    assert manager.snapshot["review_status"] == "approved"
    assert manager.snapshot["generation_status"] == "queued"
    assert manager.snapshot["generation_job_id"] == job_id
    assert queued == [(job_id, 2)]


def test_repeated_candidate_generation_request_returns_same_job_without_enqueue(handoff):
    _output_root, _upload_root, _original, manager, queued = handoff
    body = {
        "community_candidate_id": manager.snapshot["candidate_id"],
        "acknowledged": True,
    }

    first = _post_process(body)
    assert first.status_code == 200, first.text
    second = _post_process(body)

    assert second.status_code == 200, second.text
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["idempotent"] is True
    assert len(queued) == 1


def test_candidate_source_staging_failure_keeps_original_and_marks_attempt_retryable(handoff, monkeypatch):
    _output_root, upload_root, original, manager, queued = handoff
    monkeypatch.setattr(app_module, "_media_duration_seconds", lambda _path: 0.0)

    response = _post_process({
        "community_candidate_id": manager.snapshot["candidate_id"],
        "acknowledged": True,
    })

    assert response.status_code == 400
    assert original.is_file()
    assert original.read_bytes() == b"original-highlight-mp4"
    assert list(upload_root.iterdir()) == []
    assert manager.snapshot["review_status"] == "approved"
    assert manager.snapshot["generation_status"] == "failed"
    assert manager.snapshot["generation_job_id"]
    assert queued == []


def test_candidate_source_requires_rights_attestation_and_does_not_claim(handoff):
    _output_root, _upload_root, _original, manager, queued = handoff

    response = _post_process({"community_candidate_id": manager.snapshot["candidate_id"]})

    assert response.status_code == 400
    assert manager.snapshot["generation_status"] == "not_started"
    assert manager.snapshot["generation_job_id"] is None
    assert queued == []


def test_candidate_claim_is_atomic_idempotent_and_retryable_after_failure(tmp_path):
    root = tmp_path / "captures"
    store = MemoryStateStore()
    manager = CaptureSessionManager(output_root=root, state_store=store)
    manager.restore()

    session_id = "session_12345678901234567890"
    candidate_id = "candidate_12345678901234567890"
    source = root / session_id / "highlights" / f"{candidate_id}.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"highlight")
    candidate = HighlightCandidate(
        candidate_id=candidate_id,
        capture_session_id=session_id,
        triggered_at=datetime.now(timezone.utc),
        pre_seconds=45,
        post_seconds=45,
        reason="phrase",
        status="ready",
        output_path=source,
    )
    manager._candidates[candidate_id] = candidate
    manager._persist_locked(strict=True)

    first_job = str(uuid.uuid4())
    snapshot, path, created = manager.claim_candidate_generation(candidate_id, first_job)
    assert created is True
    assert path == source
    assert snapshot["review_status"] == "approved"
    assert snapshot["generation_status"] == "staging"
    with pytest.raises(ValueError, match="cannot be rejected"):
        manager.decide_candidate(candidate_id, approved=False)
    with pytest.raises(ValueError, match="still being created"):
        manager.delete_candidate(candidate_id)

    duplicate, no_path, created = manager.claim_candidate_generation(candidate_id, str(uuid.uuid4()))
    assert created is False
    assert no_path is None
    assert duplicate["generation_job_id"] == first_job

    manager.update_candidate_generation(
        candidate_id,
        first_job,
        status="failed",
        error="The test render failed.",
    )
    retry_job = str(uuid.uuid4())
    retried, retry_path, created = manager.claim_candidate_generation(candidate_id, retry_job)
    assert created is True
    assert retry_path == source
    assert retried["generation_job_id"] == retry_job
    assert retried["generation_status"] == "staging"
    assert source.read_bytes() == b"highlight"

    restored = CaptureSessionManager(output_root=root, state_store=store)
    restored_candidate = next(item for item in restored.list_candidates() if item["candidate_id"] == candidate_id)
    assert restored_candidate["generation_job_id"] == retry_job
    assert restored_candidate["generation_status"] == "staging"


def test_timestamped_diagnostics_hash_ids_and_drop_secret_fields(caplog):
    opaque_id = "candidate-super-secret-identifier"
    with caplog.at_level("INFO", logger="clippy.community_highlights"):
        log_event(
            "generation.test",
            candidate_id=opaque_id,
            outcome="failed",
            oauth_token="never-log-this-token",
            chat_text="private chat contents",
        )

    assert "timestamp" in caplog.text
    assert "generation.test" in caplog.text
    assert "candidate_id_ref" in caplog.text
    assert opaque_id not in caplog.text
    assert "never-log-this-token" not in caplog.text
    assert "private chat contents" not in caplog.text



def test_startup_reconciles_recovered_completed_job_to_candidate(handoff, monkeypatch):
    _output_root, _upload_root, _original, manager, _queued = handoff
    job_id = str(uuid.uuid4())
    manager.snapshot.update(
        review_status="approved",
        generation_status="queued",
        generation_job_id=job_id,
    )
    monkeypatch.setattr(
        app_module,
        "jobs",
        {job_id: {"status": "completed", "result": {"clips": []}}},
    )

    app_module._reconcile_community_candidate_generations()

    assert manager.snapshot["generation_status"] == "completed"
    assert manager.snapshot["generation_error"] is None


def test_startup_marks_missing_generation_job_retryable(handoff, monkeypatch):
    _output_root, _upload_root, _original, manager, _queued = handoff
    job_id = str(uuid.uuid4())
    manager.snapshot.update(
        review_status="approved",
        generation_status="processing",
        generation_job_id=job_id,
    )
    monkeypatch.setattr(app_module, "jobs", {})
    monkeypatch.setattr(app_module, "_read_manifest", lambda _job_id: None)

    app_module._reconcile_community_candidate_generations()

    assert manager.snapshot["generation_status"] == "failed"
    assert manager.snapshot["generation_error"]
