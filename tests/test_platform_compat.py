"""Tests for native Windows/POSIX process compatibility helpers."""

import os
import subprocess
import sys
import types

import platform_compat


def test_windows_jobs_use_below_normal_priority_without_preexec():
    options = platform_compat.job_subprocess_options(10, platform="win32")
    assert options == {"creationflags": 0x00004000}
    assert "preexec_fn" not in options


def test_zero_priority_does_not_change_process_class():
    assert platform_compat.job_subprocess_options(0, platform="win32") == {}
    assert platform_compat.job_subprocess_options(0, platform="linux") == {}


def test_posix_jobs_keep_niceness_behavior():
    options = platform_compat.job_subprocess_options(7, platform="linux")
    assert callable(options["preexec_fn"])
    assert "creationflags" not in options


def test_windows_lock_uses_msvcrt_byte_range(tmp_path, monkeypatch):
    calls = []
    fake_msvcrt = types.SimpleNamespace(
        LK_NBLCK=1,
        LK_UNLCK=2,
        locking=lambda fd, mode, count: calls.append((fd, mode, count)),
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    path = tmp_path / "slot.lock"
    with path.open("a+", encoding="utf-8") as handle:
        platform_compat.acquire_file_lock(handle, platform="nt")
        assert path.read_text(encoding="utf-8") == "\\0"
        platform_compat.release_file_lock(handle, platform="nt")

    assert [call[1:] for call in calls] == [(1, 1), (2, 1)]


def test_posix_lock_acquires_and_releases(tmp_path, monkeypatch):
    calls = []
    fake_fcntl = types.SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda handle, mode: calls.append((handle, mode)),
    )
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)

    path = tmp_path / "slot.lock"
    with path.open("a+", encoding="utf-8") as handle:
        platform_compat.acquire_file_lock(handle, platform="posix")
        platform_compat.release_file_lock(handle, platform="posix")

    assert [mode for _, mode in calls] == [3, 4]
