"""The free plan's watermark is a served COPY, never the file itself.

Until 30-sep-2026 the mark was burned into the canonical reframe, so every
derivative (hook, captions, recut) inherited it and nothing short of running
the whole job again could remove it. The upgrade modal said "upgrade to remove
the watermark" all the same, and the first cancellation for "clip quality" was
a user who paid fifteen minutes after their first job and found the mark still
there on every download and every restyle.

Now every file the pipeline and the editor write is clean, the served file on
the free plan is a ``wm_`` twin of the final one (``main.mark_delivery``), both
go to R2, and an upgrade re-points the library at the clean twins with no
render (``cloud.videos.unmark_user_library``).
"""
import asyncio
import json
import os

import pytest

import watermarked


class TestNames:
    def test_marked_and_clean_are_inverses(self):
        assert watermarked.marked_name("a_clip_1.mp4") == "wm_a_clip_1.mp4"
        assert watermarked.marked_name("wm_a_clip_1.mp4") == "wm_a_clip_1.mp4"
        assert watermarked.clean_name("wm_subtitled_1_hooked_2_a_clip_1.mp4") == \
            "subtitled_1_hooked_2_a_clip_1.mp4"
        assert watermarked.clean_name("a_clip_1.mp4") == "a_clip_1.mp4"
        assert watermarked.is_marked("wm_x.mp4") and not watermarked.is_marked("x.mp4")

    def test_clean_deliverables_are_clips_and_their_derivatives(self):
        for name in ("t_clip_1.mp4", "subtitled_1_t_clip_1.mp4", "hooked_1_t_clip_2.mp4",
                     "recut_1_ab_t_clip_1.mp4", "edited_t_clip_1.mp4",
                     "translated_es_t_clip_1.mp4"):
            assert watermarked.is_clean_deliverable(name), name
        # The marked copy itself, the editor's scratch files, and sidecars are
        # not clean deliverables: they stay servable on a marked job.
        for name in ("wm_t_clip_1.mp4", "temp_preview_0.mp4", "temp_scene_ab_001.jpg",
                     "subs_0_1.ass", "t_clip_1.layout.json"):
            assert not watermarked.is_clean_deliverable(name), name

    def test_marker_round_trip(self, tmp_path):
        d = str(tmp_path)
        assert not watermarked.job_is_marked(d)
        watermarked.mark_job(d)
        assert watermarked.job_is_marked(d)
        watermarked.unmark_job(d)
        assert not watermarked.job_is_marked(d)
        watermarked.unmark_job(d)  # idempotent


class TestMarkDelivery:
    """The pipeline's last step on a free job: a wm_ copy next to the clean final."""

    def test_writes_the_copy_and_leaves_the_final_alone(self, tmp_path):
        main = pytest.importorskip("main")
        final = tmp_path / "subtitled_1_t_clip_1.mp4"
        final.write_bytes(b"clean")
        calls = []

        def marker(src, out):
            calls.append((os.path.basename(src), os.path.basename(out)))
            with open(out, "wb") as f:
                f.write(b"marked")
            return True

        served = main.mark_delivery(str(final), marker=marker)
        assert os.path.basename(served) == "wm_subtitled_1_t_clip_1.mp4"
        assert calls == [("subtitled_1_t_clip_1.mp4", "wm_subtitled_1_t_clip_1.mp4")]
        assert final.read_bytes() == b"clean"

    def test_reuses_an_existing_copy(self, tmp_path):
        main = pytest.importorskip("main")
        (tmp_path / "t_clip_1.mp4").write_bytes(b"clean")
        (tmp_path / "wm_t_clip_1.mp4").write_bytes(b"marked")
        served = main.mark_delivery(str(tmp_path / "t_clip_1.mp4"),
                                    marker=lambda *_: pytest.fail("re-encoded"))
        assert os.path.basename(served) == "wm_t_clip_1.mp4"

    def test_fails_open_under_the_marked_name(self, tmp_path):
        """A failed mark still serves the clip, and still under the wm_ name:
        the /videos guard refuses the clean deliverables of a free job, so a
        clean name here would be a clip the user cannot play."""
        main = pytest.importorskip("main")
        (tmp_path / "t_clip_1.mp4").write_bytes(b"clean")
        served = main.mark_delivery(str(tmp_path / "t_clip_1.mp4"),
                                    marker=lambda *_: False)
        assert os.path.basename(served) == "wm_t_clip_1.mp4"
        assert (tmp_path / "wm_t_clip_1.mp4").read_bytes() == b"clean"


class TestWalkBacks:
    """The mark is the outermost layer: every editor derivation strips it first."""

    def test_strip_captions_walks_through_the_mark(self, tmp_path):
        app = pytest.importorskip("app")
        d = str(tmp_path)
        for name in ("t_clip_1.mp4", "hooked_2_t_clip_1.mp4",
                     "subtitled_3_hooked_2_t_clip_1.mp4",
                     "wm_subtitled_3_hooked_2_t_clip_1.mp4"):
            (tmp_path / name).write_bytes(b"x")
        assert app._strip_burned_captions(d, "wm_subtitled_3_hooked_2_t_clip_1.mp4") == \
            "hooked_2_t_clip_1.mp4"
        assert app._strip_burned_hook(d, "hooked_2_t_clip_1.mp4") == "t_clip_1.mp4"
        # The mark is a copy of a file that is on disk: it walks back the same.
        assert app._strip_burned_hook(d, "wm_hooked_2_t_clip_1.mp4") == "t_clip_1.mp4"

    def test_strip_keeps_the_mark_when_the_twin_is_gone(self, tmp_path):
        app = pytest.importorskip("app")
        (tmp_path / "wm_t_clip_1.mp4").write_bytes(b"x")
        assert app._strip_burned_captions(str(tmp_path), "wm_t_clip_1.mp4") == "wm_t_clip_1.mp4"

    def test_canonical_clip_file_prefers_the_marked_copy(self, tmp_path):
        app = pytest.importorskip("app")
        import time
        (tmp_path / "t_clip_1.mp4").write_bytes(b"x")
        (tmp_path / "subtitled_5_t_clip_1.mp4").write_bytes(b"x")
        time.sleep(0.02)
        (tmp_path / "wm_subtitled_5_t_clip_1.mp4").write_bytes(b"x")
        os.utime(tmp_path / "wm_subtitled_5_t_clip_1.mp4", None)
        assert app._canonical_clip_file(str(tmp_path), "t", 0) == "wm_subtitled_5_t_clip_1.mp4"


class TestMediaGuard:
    """A free job's clean twins are not fetchable by stripping wm_ off the URL."""

    def test_deliver_marks_only_jobs_the_pipeline_marked(self, tmp_path, monkeypatch):
        """An old-scheme free job (mark burned into the canonical, no marker)
        must not get a second mark on its next edit."""
        app = pytest.importorskip("app")
        monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(app, "BILLING_ENABLED", True)

        class _U:
            plan = "free"

        async def _user(_request):
            return _U()

        monkeypatch.setattr(app, "_user_from_request", _user)
        (tmp_path / "old").mkdir()
        (tmp_path / "old" / "t_clip_1.mp4").write_bytes(b"burned")
        assert asyncio.run(app._deliver(None, "old", "t_clip_1.mp4")) == "t_clip_1.mp4"

        (tmp_path / "new").mkdir()
        (tmp_path / "new" / "t_clip_1.mp4").write_bytes(b"clean")
        watermarked.mark_job(str(tmp_path / "new"))
        # main.py needs the ML stack; _deliver imports it lazily, so a stub
        # module stands in for it here (CI installs none of it).
        import sys
        import types
        monkeypatch.setitem(sys.modules, "main", types.SimpleNamespace(
            mark_delivery=lambda path, marker=None: os.path.join(
                os.path.dirname(path), "wm_" + os.path.basename(path))))
        assert asyncio.run(app._deliver(None, "new", "t_clip_1.mp4")) == "wm_t_clip_1.mp4"

    def test_marked_job_refuses_clean_clips_only(self, tmp_path, monkeypatch):
        app = pytest.importorskip("app")
        monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
        (tmp_path / "job1").mkdir()
        watermarked.mark_job(str(tmp_path / "job1"))
        assert app._media_guard("job1/wm_subtitled_1_t_clip_1.mp4")
        assert not app._media_guard("job1/subtitled_1_t_clip_1.mp4")
        assert not app._media_guard("job1/t_clip_1.mp4")
        # Editor scratch files and sidecars stay servable.
        assert app._media_guard("job1/temp_preview_0.mp4")
        assert app._media_guard("job1/subs_0_1.ass")
        # And a dotfile never is, marker included.
        assert not app._media_guard("job1/.marked")

    def test_unmarked_job_serves_everything_deliverable(self, tmp_path, monkeypatch):
        app = pytest.importorskip("app")
        monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
        (tmp_path / "job2").mkdir()
        assert app._media_guard("job2/t_clip_1.mp4")
        assert not app._media_guard("job2/t_metadata.json")


class TestLocalUnmark:
    def test_repoints_memory_metadata_and_drops_the_copy(self, tmp_path, monkeypatch):
        app = pytest.importorskip("app")
        monkeypatch.setattr(app, "OUTPUT_DIR", str(tmp_path))
        job_dir = tmp_path / "j1"
        job_dir.mkdir()
        (job_dir / "t_clip_1.mp4").write_bytes(b"clean")
        (job_dir / "wm_t_clip_1.mp4").write_bytes(b"marked")
        watermarked.mark_job(str(job_dir))
        (job_dir / "t_metadata.json").write_text(json.dumps({
            "shorts": [{"video_url": "/videos/j1/wm_t_clip_1.mp4"}]}))
        app.jobs["j1"] = {"status": "completed",
                          "result": {"clips": [{"video_url": "/videos/j1/wm_t_clip_1.mp4"}]},
                          "ready_files": {0: "wm_t_clip_1.mp4"}}
        try:
            app._unmark_local_job("j1", 0, "t_clip_1.mp4")
            assert app.jobs["j1"]["result"]["clips"][0]["video_url"] == "/videos/j1/t_clip_1.mp4"
            assert app.jobs["j1"]["ready_files"][0] == "t_clip_1.mp4"
            meta = json.loads((job_dir / "t_metadata.json").read_text())
            assert meta["shorts"][0]["video_url"] == "/videos/j1/t_clip_1.mp4"
            assert not (job_dir / "wm_t_clip_1.mp4").exists()
            assert (job_dir / "t_clip_1.mp4").exists()
            assert not watermarked.job_is_marked(str(job_dir))
        finally:
            app.jobs.pop("j1", None)


class TestArchiveTwins:
    def test_twins_of_a_marked_captioned_hook(self):
        videos = pytest.importorskip("cloud.videos")
        assert videos._twins_to_archive("wm_subtitled_3_hooked_2_t_clip_1.mp4", "t", 0) == [
            "subtitled_3_hooked_2_t_clip_1.mp4", "hooked_2_t_clip_1.mp4"]

    def test_the_canonical_is_the_callers_job(self):
        videos = pytest.importorskip("cloud.videos")
        # wm_ copy of the canonical itself: the twin IS the canonical, which
        # archive_job uploads on its own branch.
        assert videos._twins_to_archive("wm_t_clip_1.mp4", "t", 0) == []
        # A clean captioned hook (paid plan): only the intermediate.
        assert videos._twins_to_archive("subtitled_3_hooked_2_t_clip_1.mp4", "t", 0) == [
            "hooked_2_t_clip_1.mp4"]
        assert videos._twins_to_archive("t_clip_1.mp4", "t", 0) == []

    def test_superseded_never_touches_master_or_original(self):
        videos = pytest.importorskip("cloud.videos")
        # An edit on a free job: the previous marked file and its clean twin go.
        assert videos._superseded_names(
            "wm_subtitled_1_t_clip_1.mp4", "wm_subtitled_0_t_clip_1.mp4",
            "wm_subtitled_2_t_clip_1.mp4", "t", 0) == [
            "wm_subtitled_1_t_clip_1.mp4", "subtitled_1_t_clip_1.mp4"]
        # Back to the canonical (captions removed): the canonical survives.
        assert videos._superseded_names(
            "wm_t_clip_1.mp4", "wm_subtitled_0_t_clip_1.mp4",
            "wm_subtitled_2_t_clip_1.mp4", "t", 0) == ["wm_t_clip_1.mp4"]
        # The pristine original (and its twin) survive too.
        assert videos._superseded_names(
            "wm_subtitled_0_t_clip_1.mp4", "wm_subtitled_0_t_clip_1.mp4",
            "wm_subtitled_2_t_clip_1.mp4", "t", 0) == []
        assert videos._superseded_names(None, None, "x.mp4", "t", 0) == []


class TestUnmarkedState:
    def test_replaces_marked_names_and_reports_changes(self):
        videos = pytest.importorskip("cloud.videos")
        state = {"v": 1, "rights_attestation": {"acknowledged": True}, "clips": [
            {"index": 0, "original_file": "wm_subtitled_1_t_clip_1.mp4",
             "server_file": "wm_subtitled_9_t_clip_1.mp4", "active_layers": None},
            {"index": 1, "original_file": "t_clip_2.mp4", "server_file": "t_clip_2.mp4"},
        ]}
        new_state, changes = videos.unmarked_clip_state(state)
        assert changes == [(0, "wm_subtitled_9_t_clip_1.mp4", "subtitled_9_t_clip_1.mp4")]
        assert new_state["clips"][0]["server_file"] == "subtitled_9_t_clip_1.mp4"
        assert new_state["clips"][0]["original_file"] == "subtitled_1_t_clip_1.mp4"
        assert new_state["clips"][1] == state["clips"][1]
        assert new_state["rights_attestation"] == {"acknowledged": True}
        # The input is not mutated.
        assert state["clips"][0]["server_file"] == "wm_subtitled_9_t_clip_1.mp4"

    def test_nothing_marked_nothing_changes(self):
        videos = pytest.importorskip("cloud.videos")
        assert videos.unmarked_clip_state(None) == ({"v": 1, "clips": []}, [])


class TestBecameLive:
    def test_only_the_free_to_paid_transition(self):
        billing = pytest.importorskip("cloud.billing")
        assert billing.became_live(None, "active")
        assert billing.became_live(None, "trialing")
        assert billing.became_live("canceled", "active")
        assert billing.became_live("incomplete", "active")
        assert not billing.became_live("active", "active")
        assert not billing.became_live("trialing", "active")
        assert not billing.became_live(None, "incomplete")
        assert not billing.became_live("active", "canceled")
