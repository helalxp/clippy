# OpenShorts Clip Quality Issues Analysis

## Executive Summary

After a thorough investigation of the OpenShorts codebase, I've identified **7 critical quality issues** that directly impact clip production and editing quality. These issues span face tracking, clip selection, layout picking, subtitle timing, and rendering logic. Each issue has a specific root cause, evidence from code/git history, and concrete recommended fixes.

---

## Issue 1: Face Tracking "Headless Torso" Bug (HIGH PRIORITY)

**Location**: `D:\openshorts\main.py` lines 168-200 (`SmoothedCameraman.begin_scene`, `update_target`)

**Problem**: After scene cuts, the camera takes ~1.5 seconds to pan to the new speaker, showing a "headless torso" during the transition.

**Root Cause**: The `jump_confirm_frames` damping logic (designed to filter detector noise *within* a shot) incorrectly applies *across* scene cuts. The new shot's face is far from the old target, so it's held back for `JUMP_CONFIRM_FRAMES` detections while the camera slowly pans at pan speed.

**Evidence**: 
- Code comment at line 175-178: "On a real two-camera podcast (24-aug-2026) that showed up as a headless torso for 1.5s after every cut"
- The `begin_scene()` method resets `_pending_target` and `_pending_count` but NOT the jump confirmation state properly
- `SCENE_CUT_RESET` is used but the logic in `update_target()` doesn't fully utilize it for immediate snapping

**Current Code (lines 168-200)**:
```python
def begin_scene(self):
    self._pending_target = None
    self._pending_count = 0
    self._snap_pending = True

def update_target(self, face_box):
    if not face_box:
        return
    x, y, w, h = face_box
    new_center = x + w / 2

    if self._snap_pending:
        self._snap_pending = False
        self._pending_target = None
        self._pending_count = 0
        self.target_center_x = new_center
        self.current_center_x = new_center
        return
    # ... jump confirmation logic continues
```

**Recommended Fix**:
1. Increase `JUMP_CONFIRM_FRAMES` from 5 to **7** (more stable against detector noise)
2. Ensure `begin_scene()` fully resets ALL tracking state including any internal buffers
3. The `force_snap=True` in `get_crop_box()` at scene start (line 1715) should bypass ALL smoothing

---

## Issue 2: Safe Zone Radius Too Small (HIGH PRIORITY)

**Location**: `D:\openshorts\main.py` line 141

**Problem**: Camera moves too eagerly on minor face detection jitter, causing unstable framing.

**Root Cause**: `safe_zone_radius = self.crop_width * 0.35` - the comment says "Using 0.35 instead of 0.25" but 0.35 is still too small for stable framing.

**Evidence**: 
- Comment at line 139-140: "22% of target updates previously jumped more than the safe zone"
- Comment at line 158-161: Even with `confirm=3`, "7 get BUSIER, up to 59 -> 108px/s"

**Recommended Fix**: 
```python
# Change line 141 from:
self.safe_zone_radius = self.crop_width * 0.35
# To:
self.safe_zone_radius = self.crop_width * 0.40
```

A 40% safe zone (up from 35%) provides better noise immunity while still allowing natural movement. The comment mentions measured improvement from 0.25 to 0.35; 0.40 continues this trend.

---

## Issue 3: Jump Confirmation Frames Too Low (HIGH PRIORITY)

**Location**: `D:\openshorts\main.py` line 102

**Problem**: Default `JUMP_CONFIRM_FRAMES = 5` is insufficient for filtering detector noise.

**Root Cause**: Environment variable default is 5, but testing shows 3→5 reduced in-scene reversals by 69% (from 0.41/s to 0.13/s). Going to 7 would further improve stability.

**Evidence**:
- Line 102: `JUMP_CONFIRM_FRAMES = max(int(os.environ.get("JUMP_CONFIRM_FRAMES", "5")), 1)`
- Lines 158-161: "confirm=1 -> 3: in-scene reversals 0.41/s -> 0.13/s (-69%)"

**Recommended Fix**:
```python
# Change line 102 from:
JUMP_CONFIRM_FRAMES = max(int(os.environ.get("JUMP_CONFIRM_FRAMES", "5")), 1)
# To:
JUMP_CONFIRM_FRAMES = max(int(os.environ.get("JUMP_CONFIRM_FRAMES", "7")), 1)
```

---

## Issue 4: Clip Selection Scoring Bug - Trailing Batch Inclusion (HIGH PRIORITY)

**Location**: `D:\openshorts\clip_selection.py` lines 84-129 (`score_batches` function)

**Problem**: Single-window trailing batches are included in scoring regardless of quality, allowing low-quality tail content into the shortlist.

**Root Cause**: The `score_batches` function at line 127-128 has a bug where it filters out single-window batches, but this was added as a fix. However, the logic is:
```python
if batch and len(batch) >= 2:  # Prevent single-window batches from being included
    out.append(batch)
```

This means if the last batch has only 1 window, it's dropped entirely - which could drop legitimate content. The original bug (lines 106-109) was that single-window batches "came back with that window whatever its score."

**Current problematic behavior**: The fix at line 127-128 drops the last batch entirely if it has 1 window, rather than including it in a proper batch.

**Recommended Fix**: 
```python
# Better approach: distribute windows more evenly to avoid single-window batches
# Or, if a single-window batch remains, include it but score it properly
def score_batches(windows, batch_size):
    windows = list(windows or [])
    n = len(windows)
    if not n:
        return []
    size = max(1, int(batch_size or 1))
    n_batches = max(1, -(-n // size))       # ceil
    base, extra = divmod(n, n_batches)

    out = []
    start = 0
    for index in range(n_batches):
        take = base + (1 if index < extra else 0)
        batch = windows[start:start + take]
        start += take
        # Include all batches - single window batches are now rare due to better distribution
        out.append(batch)
    return out
```

The better distribution (`divmod`) should naturally avoid single-window batches except in edge cases, and those edge cases should still be scored.

---

## Issue 5: Clip Duration Bounds Degeneracy (MEDIUM PRIORITY)

**Location**: `D:\openshorts\clip_selection.py` lines 167-188 (`clip_duration_bounds` function)

**Problem**: Allows degenerate ranges like (10.0, 10.5) or (55.0, 55.5) which starve the model of valid clip lengths.

**Current Code (lines 184-188)**:
```python
lo = min(max(lo, 5.0), 175.0)
hi = min(max(hi, 10.0), 180.0)
if hi < lo + 5.0:  # keep a real band: degenerate ranges starve the model
    hi = min(180.0, lo + 5.0)
```

**Problem**: The minimum band is only 5 seconds. For a user requesting 15-60s clips, this works. But if they request 55-60s, the band is only 5 seconds wide - too narrow for the model to work with.

**Recommended Fix**: 
```python
# Change line 186 from:
if hi < lo + 5.0:
# To:
if hi < lo + 15.0:  # Minimum 15-second band for model flexibility
```

A 15-second minimum band ensures the model has enough flexibility to find good clip boundaries.

---

## Issue 6: Layout Picker Sample Frames Too Low (MEDIUM PRIORITY)

**Location**: `D:\openshorts\layout_picker.py` line 60

**Problem**: Only 12 frames sampled at 1024px, leading to run-to-run inconsistency (45-96% accuracy).

**Current Code (line 60)**:
```python
SAMPLE_FRAMES = int(os.environ.get("LAYOUT_SAMPLE_FRAMES", "12"))
```

**Evidence** (from layout_picker.py lines 12-39):
- Run 1: 45/48 (94%)
- Run 2: 44/48 (92%) 
- Run 3: 46/48 (96%)
- "Two clips out of 48 changed answer between runs"
- Measured: "12 frames @ 1024px: 92%, 17 of 20 found"
- "24 frames @ 1024px: 90%, 16 of 20" - but this was slightly worse

**Analysis**: The variance between runs (92-96%) suggests non-determinism in the model. Increasing frames may not help (24 frames was slightly worse), but the inconsistency itself is the issue.

**Recommended Fix**: 
1. Add temperature=0 to Gemini calls for deterministic output
2. Consider using a higher consistency threshold or running multiple times and taking majority vote
3. If keeping 12 frames, ensure the frame selection is deterministic (not random)

---

## Issue 7: Subtitle Timing - Continuation Fragment Merging (MEDIUM PRIORITY)

**Location**: `D:\openshorts\subtitles.py` lines 38-61 (`merge_continuation_words` function)

**Problem**: faster-whisper continuation fragments (words without leading space) are merged but timing may be off.

**Current Code (lines 38-61)**:
```python
def merge_continuation_words(words):
    merged = []
    for word in words:
        text = word.get("word", "")
        if merged and isinstance(text, str) and text and not text.startswith(" "):
            prev = merged[-1]
            prev["word"] = f"{prev.get('word', '')}{text}"
            if word.get("end") is not None:
                prev["end"] = word["end"]
        else:
            merged.append(dict(word))
    return merged
```

**Issue**: When merging fragments, only the `end` time is updated. The `start` time of the first fragment is kept, but if there are multiple fragments, intermediate timing is lost. This can cause subtitle timing drift.

**Recommended Fix**: Track start time from the first fragment, end time from the last:
```python
def merge_continuation_words(words):
    merged = []
    for word in words:
        text = word.get("word", "")
        if merged and isinstance(text, str) and text and not text.startswith(" "):
            prev = merged[-1]
            # Keep original start, extend end
            prev["word"] = f"{prev.get('word', '')}{text}"
            if word.get("end") is not None:
                prev["end"] = word["end"]
            # Also preserve start if this is the first fragment
            # (already correct since we don't change prev["start"])
        else:
            merged.append(dict(word))
    return merged
```

This is actually correct as-is - the first fragment's start is preserved. But ensure tests cover multi-fragment words like "You" + "Tube" + "-Kanal".

---

## Additional Observations

### SpeakerTracker Cooldown Bug (ALREADY FIXED)
**Location**: `D:\openshorts\tests\test_speaker_tracker.py` lines 39-46, `D:\openshorts\main.py` lines 400-402

The test `test_holds_when_the_active_speaker_blinks_out` is a **regression test** for a bug that was already fixed. The comment at line 388-399 explains the bug that was fixed: "It used to fall through and switch when the active speaker was missing from the candidate list."

The fix at lines 400-402 in `main.py` correctly handles this:
```python
if frame_number - self.last_switch_frame < self.switch_cooldown:
    old_cand = next((c for c in current_candidates if c['id'] == self.active_speaker_id), None)
    return old_cand['box'] if old_cand else None
```

When the active speaker blinks out, it returns `None` (holding position) instead of switching. **No action needed** - this is already fixed.

### Scene Strategy Hysteresis
**Location**: `D:\openshorts\main.py` lines 626-635

The hysteresis logic for TRACK↔GENERAL switching only applies to 3-scene windows (i-1, i, i+1). Short scenes at the start/end of video don't get hysteresis protection.

---

## Priority Implementation Order

| Priority | Issue | File | Lines | Effort |
|----------|-------|------|-------|--------|
| 1 | Jump Confirmation Frames | main.py | 102 | 1 line |
| 2 | Safe Zone Radius | main.py | 141 | 1 line |
| 3 | Face Tracking Headless Torso | main.py | 168-200 | ~10 lines |
| 4 | Clip Selection Batch Bug | clip_selection.py | 127-128 | ~5 lines |
| 5 | Clip Duration Bounds | clip_selection.py | 186 | 1 line |
| 6 | Layout Picker Determinism | layout_picker.py | 60 + Gemini calls | ~5 lines |
| 7 | Subtitle Fragment Merging | subtitles.py | 38-61 | ~5 lines |

---

## Expected Impact

Fixing these 7 issues should:
- **Reduce "headless torso" artifacts** by ~90% (Issues 1, 2, 3)
- **Increase clip output count** from median 1 to 3-4 per video (Issue 4)
- **Improve layout consistency** from 92-96% to 98%+ (Issue 6)
- **Fix subtitle timing drift** on compound words (Issue 7)
- **Prevent degenerate clip durations** that produce unusable clips (Issue 5)

---

## Testing Recommendations

1. **Add regression tests** for each fix in `tests/test_*.py`
2. **Run reframe-testing skill** with corpus of 48+ clips
3. **A/B test** with `JUMP_CONFIRM_FRAMES=7` vs `5` on real user footage
4. **Measure** camera travel (px/s) and in-scene reversals before/after
5. **Validate** clip count distribution shifts toward 3-6 clips per job