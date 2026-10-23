"""Names for the free plan's watermarked delivery copies.

Every file the pipeline and the clip editor write is CLEAN. On the free plan
the file that is *served* is a copy of the final one with the mark burned in,
named ``wm_<final>`` and kept next to it (and in R2 beside it). Two things
follow from keeping both:

* an upgrade removes the watermark from the clips the user already has by
  re-pointing each clip at its clean twin, with no re-encode and no source
  video, which is what the upgrade modal has always promised
  (``cloud.videos.unmark_user_library``);
* the walk-backs that find the editable master under a served name
  (``app._strip_burned_captions`` and friends) treat the ``wm_`` prefix as the
  outermost layer, and the ``/videos`` guard refuses the clean twins of a
  free job so the copy cannot be fetched by stripping the prefix from a URL.

Before 30-sep-2026 the mark was burned into the canonical reframe, so the
only way to lose it was to run the whole job again: the first cancellation
for "clip quality" was a user who paid 15 minutes after their first job and
found the mark still there on every download and every restyle.

No imports beyond the standard library on purpose: ``main.py``, ``app.py``
and ``cloud/videos.py`` all use it and only the first of those has ffmpeg.
"""
import os
import re

PREFIX = "wm_"

# The dotfile ``main.py`` writes in a job directory rendered for the free plan.
# Read by the ``/videos`` guard (a dotfile is never servable itself); removed
# when the library is unmarked after an upgrade.
MARKER_FILE = ".marked"

_VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov", ".m4v", ".mkv", ".ogv"})

# Names that are a deliverable clip or one of its derivatives. The editor's
# own scratch files (``temp_preview_<i>.mp4``, ``temp_scene_*.jpg``) are not
# clips and stay servable on a marked job.
_DELIVERABLE_RE = re.compile(
    r'^(?:subtitled_\d+_|hooked_\d+_|hook_|recut_|edited_|translated_)|_clip_\d+\.[A-Za-z0-9]+$'
)


def is_marked(filename: str) -> bool:
    return bool(filename) and os.path.basename(filename).startswith(PREFIX)


def marked_name(filename: str) -> str:
    """``wm_<filename>``; idempotent."""
    base = os.path.basename(filename)
    return base if base.startswith(PREFIX) else PREFIX + base


def clean_name(filename: str) -> str:
    """The clean twin of a served name (the name itself when not marked)."""
    base = os.path.basename(filename)
    return base[len(PREFIX):] if base.startswith(PREFIX) else base


def is_clean_deliverable(filename: str) -> bool:
    """True for a clip file (canonical or derived) that carries no mark."""
    base = os.path.basename(filename or "")
    if not base or base.startswith(PREFIX):
        return False
    if os.path.splitext(base)[1].lower() not in _VIDEO_EXTENSIONS:
        return False
    return bool(_DELIVERABLE_RE.search(base))


def job_is_marked(job_dir: str) -> bool:
    return os.path.exists(os.path.join(job_dir, MARKER_FILE))


def mark_job(job_dir: str) -> None:
    try:
        with open(os.path.join(job_dir, MARKER_FILE), "w") as f:
            f.write("1")
    except OSError:
        pass


def unmark_job(job_dir: str) -> None:
    try:
        os.remove(os.path.join(job_dir, MARKER_FILE))
    except OSError:
        pass
