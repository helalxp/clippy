"""NVDEC decoding (gpu_decode) and the sparse trajectory pass (reframe_v2).

The card itself is not available in CI: these tests pin the command rewrites,
the CPU fallback, and that the sparse trajectory hands the detectors exactly
the frames the full pass did and ends with the same crop trajectory.
"""
import re
import subprocess
import sys
import types

import numpy as np
import pytest

import gpu_decode
import reframe_v2


# --- command rewrites -------------------------------------------------------

def test_graph_feeds_the_first_input_from_the_card():
    g = gpu_decode.graph("[0:v]split=2[a][b];[a][b]vstack[v]", True)
    assert g == ("[0:v]hwdownload,format=nv12,format=yuv420p[gpudec];"
                 "[gpudec]split=2[a][b];[a][b]vstack[v]")
    assert gpu_decode.graph("[0:v]scale=2:2[v]", False) == "[0:v]scale=2:2[v]"


def test_vf_chain_starts_with_the_download():
    assert gpu_decode.vf("scale=48:27", True) == f"{gpu_decode.DOWNLOAD},scale=48:27"
    assert gpu_decode.vf("scale=48:27", False) == "scale=48:27"


def test_on_card_rewrites_filter_complex_and_input():
    cmd = ["ffmpeg", "-y", "-i", "clip.mp4", "-i", "logo.png",
           "-filter_complex", "[0:v][1:v]overlay=1:2[v]", "-map", "[v]", "out.mp4"]
    out = gpu_decode.on_card(cmd, "clip.mp4")
    assert out[:6] == ["ffmpeg", "-y", *gpu_decode.HW_ARGS]
    assert out[6:8] == ["-i", "clip.mp4"]
    k = out.index("-filter_complex") + 1
    assert out[k].startswith("[0:v]" + gpu_decode.DOWNLOAD + "[gpudec];[gpudec][1:v]overlay")
    # The logo input is left alone.
    assert out[out.index("logo.png") - 1] == "-i"
    assert cmd[2] == "-i"  # the original list is not modified


def test_on_card_rewrites_a_vf_chain():
    cmd = ["ffmpeg", "-y", "-i", "clip.mp4", "-vf", "subtitles=a.ass", "out.mp4"]
    out = gpu_decode.on_card(cmd, "clip.mp4")
    assert out[out.index("-vf") + 1] == f"{gpu_decode.DOWNLOAD},subtitles=a.ass"
    assert out[2:6] == gpu_decode.HW_ARGS


@pytest.mark.parametrize("cmd", [
    ["ffmpeg", "-i", "clip.mp4", "-c", "copy", "out.mp4"],                   # no filter
    ["ffmpeg", "-i", "logo.png", "-i", "clip.mp4", "-vf", "x", "out.mp4"],   # not first
    ["ffmpeg", "-i", "clip.mp4", "-filter_complex",
     "[0:v]split[a];[0:v]null[b]", "out.mp4"],                               # [0:v] twice
])
def test_on_card_leaves_unsafe_commands_alone(cmd):
    assert gpu_decode.on_card(cmd, "clip.mp4") is cmd


def test_run_falls_back_to_the_cpu_when_the_card_fails(monkeypatch):
    monkeypatch.setattr(gpu_decode, "usable", lambda path, render=True: True)
    calls = []

    def runner(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd == "gpu" else 0)

    before = dict(gpu_decode.STATS)
    result = gpu_decode.run(lambda g: "gpu" if g else "cpu", runner, path="x.mp4")
    assert calls == ["gpu", "cpu"]
    assert result.returncode == 0
    assert gpu_decode.STATS["fallback"] == before["fallback"] + 1


def test_run_stays_on_the_cpu_when_the_card_is_not_usable(monkeypatch):
    monkeypatch.setattr(gpu_decode, "usable", lambda path, render=True: False)
    calls = []
    gpu_decode.run(lambda g: "gpu" if g else "cpu",
                   lambda c: calls.append(c) or subprocess.CompletedProcess(c, 0),
                   path="x.mp4")
    assert calls == ["cpu"]


def test_only_plain_8bit_420_h264_hevc_goes_to_the_card():
    ok = {"codec_name": "h264", "pix_fmt": "yuv420p"}
    assert gpu_decode._supported(ok)
    assert gpu_decode._supported({"codec_name": "hevc", "pix_fmt": "yuv420p"})
    assert not gpu_decode._supported({"codec_name": "h264", "pix_fmt": "yuv420p10le"})
    assert not gpu_decode._supported({"codec_name": "h264", "pix_fmt": "yuvj420p"})
    assert not gpu_decode._supported({"codec_name": "vp9", "pix_fmt": "yuv420p"})
    assert not gpu_decode._supported(
        {**ok, "side_data_list": [{"rotation": -90}]})
    assert gpu_decode._supported({**ok, "side_data_list": [{"rotation": 0}]})
    assert not gpu_decode._supported(None)


# --- select expression -------------------------------------------------------

def _selected(expr, n_max):
    """Evaluate the select= expression the way ffmpeg does, for n < n_max."""
    py = re.sub(r"between\(n,(\d+),(\d+)\)", r"(\1<=n<=\2)", expr)
    py = re.sub(r"not\(mod\(n,(\d+)\)\)", r"(n%\1==0)", py)
    py = re.sub(r"eq\(n,(\d+)\)", r"(n==\1)", py)
    py = re.sub(r"gte\(n,(\d+)\)", r"(n>=\1)", py)
    return [n for n in range(n_max) if eval(py, {"n": n})]


@pytest.mark.parametrize("seed", range(6))
def test_select_expr_is_true_exactly_on_the_frames(seed):
    rng = np.random.default_rng(seed)
    stride_run = list(range(0, 400, 4)) if seed % 2 else []
    frames = sorted(set(stride_run + rng.integers(0, 600, 40).tolist()))
    assert _selected(reframe_v2.select_expr(frames, 4), 700) == frames


def test_select_expr_collapses_stride_runs():
    expr = reframe_v2.select_expr(list(range(0, 4000, 4)), 4)
    assert expr == "between(n,0,3996)*not(mod(n,4))"
    assert reframe_v2.select_expr([1, 5, 6], 4) == "((eq(n,1)+eq(n,5))+eq(n,6))"
    assert reframe_v2.select_expr([], 4) == "0"


# --- sparse trajectory == full trajectory ------------------------------------

class _Cameraman:
    def __init__(self):
        self.current_center_x = 50.0
        self.target_center_x = 50.0
        self.scene_starts = 0

    def begin_scene(self):
        self.scene_starts += 1

    def update_target(self, box):
        self.target_center_x = box[0] + box[2] / 2

    def get_crop_box(self, force_snap=False):
        if force_snap:
            self.current_center_x = self.target_center_x
        else:
            self.current_center_x += (self.target_center_x - self.current_center_x) * 0.25
        x = int(self.current_center_x)
        return x, 0, x + 10, 10


class _Tracker:
    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1

    def get_target(self, candidates, frame_number, width):
        return candidates[0]["box"] if candidates else None


@pytest.fixture
def fake_main(monkeypatch):
    seen = []

    def detect_face_candidates(frame):
        n = int(frame[0, 0, 0]) + 256 * int(frame[0, 0, 1])
        seen.append(("face", n))
        if n % 3 == 0:  # no face on some frames: exercises the YOLO fallback
            return []
        return [{"box": [n % 90, 0, 8, 8]}]

    def detect_person_yolo(frame):
        n = int(frame[0, 0, 0]) + 256 * int(frame[0, 0, 1])
        seen.append(("yolo", n))
        return [n % 70, 0, 6, 6]

    m = types.SimpleNamespace(
        DETECT_STRIDE=4, YOLO_FALLBACK_STRIDE=8, SCENE_CUT_RESET=True,
        detect_face_candidates=detect_face_candidates,
        detect_person_yolo=detect_person_yolo)
    monkeypatch.setitem(sys.modules, "main", m)
    return seen


def _frame(n):
    f = np.zeros((4, 4, 3), dtype=np.uint8)
    f[0, 0, 0], f[0, 0, 1] = n % 256, n // 256
    return f


SCENES = [(0, 37), (37, 90), (90, 91), (91, 150), (150, 233)]
STRATS = ["TRACK", "GENERAL", "TRACK", "SPLIT", "TRACK"]
N = 233


def _dense(seen, orig_w=100):
    frames = iter([_frame(n) for n in range(N)])
    cam, tr = _Cameraman(), _Tracker()
    xs = reframe_v2._trajectory_loop(lambda: next(frames, None), False, None,
                                     SCENES, STRATS, orig_w, 1.0, cam, tr)
    return xs, list(seen), cam.__dict__, tr.__dict__


def test_detection_frames_are_the_frames_the_full_pass_detects_on(fake_main):
    _xs, seen, _c, _t = _dense(fake_main)
    detected = sorted({n for kind, n in seen})
    assert reframe_v2._detection_frames(SCENES, STRATS, N, 4, True) == detected


def test_sparse_pass_gives_the_same_trajectory(fake_main):
    xs, seen, cam_state, tracker_state = _dense(fake_main)
    fake_main.clear()
    wanted = iter(reframe_v2._detection_frames(SCENES, STRATS, N, 4, True))

    def next_frame(frame_number):
        assert next(wanted) == frame_number
        return _frame(frame_number)

    cam, tr = _Cameraman(), _Tracker()
    sparse = reframe_v2._trajectory_loop(next_frame, True, N, SCENES, STRATS,
                                         100, 1.0, cam, tr)
    assert sparse == xs
    assert fake_main == seen  # same detector calls, same order
    assert cam.__dict__ == cam_state and tr.__dict__ == tracker_state
    assert next(wanted, None) is None


def test_sparse_trajectory_restores_state_and_falls_back(monkeypatch, fake_main):
    """A sparse pass that does not see the frames it expects must leave the
    camera as it found it and let the full pass run."""
    xs, _seen, _c, _t = _dense(fake_main, orig_w=4)
    monkeypatch.setattr(gpu_decode, "decoded_frames", lambda path: N)
    monkeypatch.setattr(gpu_decode, "usable", lambda path, render=False: False)

    def broken_sparse(*args, **kw):
        cam, tr = args[-2], args[-1]
        cam.target_center_x = 999.0
        tr.resets = 77
        raise reframe_v2._SparseMismatch("stream ended")

    monkeypatch.setattr(reframe_v2, "_sparse_trajectory", broken_sparse)

    class _Proc:
        def __init__(self, *a, **k):
            self.stdout = _Stream()

        def wait(self):
            return 0

    class _Stream:
        def __init__(self):
            self.frames = [_frame(n).tobytes() for n in range(N)]

        def read(self, size):
            return self.frames.pop(0) if self.frames else b""

        def close(self):
            pass

    monkeypatch.setattr(reframe_v2.subprocess, "Popen", _Proc)
    monkeypatch.setattr(reframe_v2, "_analysis_size", lambda w, h: (4, 4))
    cam, tr = _Cameraman(), _Tracker()
    out = reframe_v2._analyze_trajectory("clip.mp4", SCENES, STRATS, 30.0, 4, 4, cam, tr)
    assert out == xs
    assert tr.resets != 77


# --- frame count bookkeeping and the sampler fallback -----------------------

def test_decoded_count_is_tied_to_the_exact_file(tmp_path):
    import os

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x" * 10)
    gpu_decode.remember_count(str(clip), 321)
    assert gpu_decode.decoded_frames(str(clip)) == 321
    clip.write_bytes(b"y" * 11)
    os.utime(clip, ns=(1, 1))
    assert gpu_decode.decoded_frames(str(clip)) is None
    assert gpu_decode.decoded_frames(str(tmp_path / "missing.mp4")) is None


def test_sampler_uses_read_at_when_the_card_is_not_usable(monkeypatch):
    import frame_sampler

    monkeypatch.setattr(gpu_decode, "usable", lambda path, render=False: False)
    monkeypatch.setattr(frame_sampler, "read_at",
                        lambda cap, idx, max_forward=0: iter([("cpu", i) for i in idx]))
    assert list(frame_sampler.read_at_path("clip.mp4", None, [3, 1])) == [("cpu", 3), ("cpu", 1)]
    assert list(frame_sampler.read_at_path("clip.mp4", None, [1, 3])) == [("cpu", 1), ("cpu", 3)]


def test_frame_count_is_kept_only_when_the_cfr_sync_changed_nothing():
    plain = b"frame=  810 fps=0.0 q=-0.0 Lsize= 3149kB time=00:00:27.00 speed=6x\n"
    dup = b"frame=  810 fps=0.0 q=-0.0 Lsize= 3149kB time=00:00:27.00 dup=1 drop=0 speed=6x\n"
    assert gpu_decode.one_frame_per_decoded_frame(plain)
    assert not gpu_decode.one_frame_per_decoded_frame(dup)
    assert not gpu_decode.one_frame_per_decoded_frame(b"")
    assert not gpu_decode.one_frame_per_decoded_frame(None)


def test_dense_card_decode_that_fails_is_redone_on_the_cpu(monkeypatch, fake_main):
    """No frame count (irregular timestamps): every frame is decoded, on the
    card first; a card ffmpeg that exits with an error is thrown away."""
    xs, _seen, _c, _t = _dense(fake_main, orig_w=4)
    monkeypatch.setattr(gpu_decode, "decoded_frames", lambda path: None)
    monkeypatch.setattr(gpu_decode, "usable", lambda path, render=False: True)
    runs = []

    class _Proc:
        def __init__(self, cmd, **k):
            self.gpu = "-hwaccel" in cmd
            runs.append(self.gpu)
            # The card run dies after 50 frames.
            frames = [_frame(n).tobytes() for n in range(50 if self.gpu else N)]
            self.stdout = types.SimpleNamespace(
                read=lambda size: frames.pop(0) if frames else b"", close=lambda: None)

        def wait(self):
            return 1 if self.gpu else 0

    monkeypatch.setattr(reframe_v2.subprocess, "Popen", _Proc)
    monkeypatch.setattr(reframe_v2, "_analysis_size", lambda w, h: (4, 4))
    cam, tr = _Cameraman(), _Tracker()
    out = reframe_v2._analyze_trajectory("clip.mp4", SCENES, STRATS, 30.0, 4, 4, cam, tr)
    assert runs == [True, False]
    assert out == xs


def test_any_of_stays_shallow_for_many_terms():
    """A flat sum of more than ~100 terms is refused by ffmpeg."""
    terms = [f"eq(n,{i})" for i in range(0, 1500, 3)]
    expr = gpu_decode.any_of(terms)
    depth = deepest = 0
    for ch in expr:
        depth += ch == "("
        depth -= ch == ")"
        deepest = max(deepest, depth)
    assert deepest <= 10
    assert _selected(expr, 1520) == list(range(0, 1500, 3))
    assert gpu_decode.any_of([]) == "0"
    assert gpu_decode.any_of(["eq(n,4)"]) == "eq(n,4)"
