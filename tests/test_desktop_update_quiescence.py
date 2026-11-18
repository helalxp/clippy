"""Backend quiescence contract used before installing a desktop update."""

import asyncio

import httpx
import pytest

app_module = pytest.importorskip("app")


def _post(path):
    async def _request():
        transport = httpx.ASGITransport(app=app_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(path)
    return asyncio.run(_request())


@pytest.fixture(autouse=True)
def reset_maintenance_state(monkeypatch):
    monkeypatch.setattr(app_module, "_DATA_MOVE_PENDING", False)
    monkeypatch.setattr(app_module, "_DATA_MOVE_ACTIVE_REQUESTS", 0)
    monkeypatch.setattr(app_module, "_DATA_MOVE_ACTIVE_BACKGROUND_TASKS", 0)
    monkeypatch.setattr(app_module, "jobs", {})
    monkeypatch.setattr(app_module, "pending_uploads", {})
    monkeypatch.setattr(app_module, "publish_jobs", {})


def test_update_prepare_and_cancel_reopen_request_admission():
    prepared = _post("/api/desktop/update/prepare")
    assert prepared.status_code == 200
    assert prepared.json()["ready"] is True
    assert app_module._DATA_MOVE_PENDING is True

    cancelled = _post("/api/desktop/update/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] is True
    assert app_module._DATA_MOVE_PENDING is False


@pytest.mark.parametrize(
    ("state_name", "state"),
    [
        ("jobs", {"job-1": {"status": "processing"}}),
        ("jobs", {"job-1": {"status": "queued"}}),
        ("pending_uploads", {"upload-1": {"complete": False}}),
        ("publish_jobs", {"publish-1": {"status": "uploading"}}),
    ],
)
def test_update_prepare_refuses_active_work_and_releases_gate(monkeypatch, state_name, state):
    monkeypatch.setattr(app_module, state_name, state)

    response = _post("/api/desktop/update/prepare")

    assert response.status_code == 409
    assert "active" in response.json()["detail"].lower()
    assert app_module._DATA_MOVE_PENDING is False


def test_update_and_data_move_cannot_prepare_at_the_same_time():
    prepared = _post("/api/desktop/update/prepare")
    assert prepared.status_code == 200

    conflicting = _post("/api/library/storage/prepare-move")
    assert conflicting.status_code == 409
    assert app_module._DATA_MOVE_PENDING is True
