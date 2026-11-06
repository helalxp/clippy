"""Small process/locking compatibility helpers for native Windows and POSIX.

The application runs pipeline jobs as child processes and coordinates GPU-heavy
transcription across those processes. Keep the OS-specific details here so the
pipeline itself stays platform-neutral.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import IO, Any


def job_subprocess_options(nice: int = 10, *, platform: str | None = None) -> dict[str, Any]:
    """Return Popen options that lower a batch job's priority.

    Windows uses a process priority class, inherited by child processes. POSIX
    keeps the existing pre-exec niceness behavior. No unsupported kwargs are
    passed to subprocess on either platform.
    """
    target = sys.platform if platform is None else platform
    try:
        priority = max(0, min(19, int(nice)))
    except (TypeError, ValueError):
        priority = 10

    if priority <= 0:
        return {}
    if target == "win32":
        # BELOW_NORMAL_PRIORITY_CLASS. The numeric fallback keeps this helper
        # importable/testable on non-Windows hosts.
        return {"creationflags": getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)}
    if target.startswith(("linux", "darwin", "freebsd")):
        return {"preexec_fn": lambda: os.nice(priority)}
    return {}


def acquire_file_lock(handle: IO[str], *, platform: str | None = None) -> None:
    """Acquire an exclusive, non-blocking lock on the first byte of a file."""
    target = os.name if platform is None else platform
    if target == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write("\\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def release_file_lock(handle: IO[str], *, platform: str | None = None) -> None:
    """Release a lock previously acquired with acquire_file_lock()."""
    target = os.name if platform is None else platform
    if target == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle, fcntl.LOCK_UN)


def resolve_cookies_write_path(script_dir: str) -> str:
    """Return a cross-platform path for writing temporary cookies.

    On Windows, uses the script directory. On POSIX/Docker, prefers /app/cookies.txt
    if /app exists (container environment), otherwise falls back to script directory.
    """
    if sys.platform == "win32":
        return os.path.join(script_dir, "cookies.txt")

    # POSIX: prefer /app/cookies.txt in containers, script dir otherwise
    if os.path.isdir("/app"):
        return "/app/cookies.txt"
    return os.path.join(script_dir, "cookies.txt")
