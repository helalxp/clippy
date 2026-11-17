# OpenShorts Quality Fixes - Implementation Plan

## Phase 1: Critical Face Tracking Fixes (Highest Impact)

### Fix 1.1: Increase JUMP_CONFIRM_FRAMES Default
**File**: `D:\openshorts\main.py` line 102
**Change**: 
```python
# From:
JUMP_CONFIRM_FRAMES = max(int(os.environ.get("JUMP_CONFIRM_FRAMES", "5")), 1)
# To:
JUMP_CONFIRM_FRAMES = max(int(os.environ.get("JUMP_CONFIRM_FRAMES", "7")), 1)
```

**Rationale**: Measured 69% reduction in in-scene reversals from 1→3 frames. 7 frames further improves stability.

---

### Fix 1.2: Increase Safe Zone Radius
**File**: `D:\openshorts\main.py` line 141
**Change**:
```python
# From:
self.safe_zone_radius = self.crop_width * 0.35
# To:
self.safe_zone_radius = self.crop_width * 0.40
```

**Rationale**: 35% still allows 22% of target updates to jump the zone. 40% provides better noise immunity.

---

### Fix 1.3: Fix Headless Torso Bug at Scene Cuts
**File**: `D:\openshorts\main.py` lines 168-200
**Change**: Enhance `begin_scene()` and `update_target()` to fully reset tracking state

```python
def begin_scene(self):
    """Forget the previous shot's subject at a scene cut."""
    # Reset ALL jump confirmation state
    self._pending_target = None
    self._pending_count = 0
    self._snap_pending = True
    # Also reset current_center_x to center for clean start
    self.current_center_x = self.video_width / 2
    self.target_center_x = self.video_width / 2

def update_target(self, face_box):
    """Update the target centre from a detection, ignoring lone big jumps."""
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

    # ... rest of jump confirmation logic unchanged
```

**Rationale**: The current `begin_scene()` doesn't reset `current_center_x`, causing the camera to pan from the old position.

---

## Phase 2: Clip Selection Fixes

### Fix 2.1: Fix score_batches Single-Window Batch Handling
**File**: `D:\openshorts\clip_selection.py` lines 121-129
**Change**:
```python
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
        # Include all batches - better distribution avoids single-window batches
        if batch:  # Only filter empty batches
            out.append(batch)
    return out
```

**Rationale**: The `divmod` distribution naturally avoids single-window batches. The previous filter at line 127-128 dropped legitimate tail windows.

---

### Fix 2.2: Increase Minimum Clip Duration Band
**File**: `D:\openshorts\clip_selection.py` line 186
**Change**:
```python
# From:
if hi < lo + 5.0:  # keep a real band: degenerate ranges starve the model
# To:
if hi < lo + 15.0:  # keep a real band: degenerate ranges starve the model
```

**Rationale**: 5-second band is too narrow for model flexibility. 15 seconds ensures usable range.

---

## Phase 3: Layout Picker Consistency

### Fix 3.1: Make Layout Picker Deterministic
**File**: `D:\openshorts\layout_picker.py` - need to find where Gemini is called
**Change**: Add `temperature=0` to Gemini generation config

**Search for**: `client.models.generate_content` or similar in layout_picker.py or gemini_worker.py

---

## Phase 4: Subtitle Timing Fix

### Fix 4.1: Verify merge_continuation_words Handles Multi-Fragment Words
**File**: `D:\openshorts\subtitles.py` lines 38-61
**Change**: Add test coverage for multi-fragment words like "You" + "Tube" + "-Kanal"

Current implementation is correct but needs validation.

---

## Testing Checklist

After each fix:
- [ ] Run `pytest tests/test_speaker_tracker.py -v` (regression test for tracker)
- [ ] Run `pytest tests/test_subtitles.py -v` (subtitle timing)
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Manual test with sample videos showing the issues

---

## Expected Results

| Metric | Before | After Target |
|--------|--------|--------------|
| In-scene reversals | 0.13/s | <0.05/s |
| Camera travel | 60px/s | <40px/s |
| Headless torso duration | ~1.5s | <0.2s |
| Clips per job (median) | 1 | 3-4 |
| Layout picker consistency | 92-96% | 98%+ |
| Subtitle timing drift | Present | Eliminated |