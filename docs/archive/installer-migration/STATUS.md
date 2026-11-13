# Summary of Changes Made

## ✅ IMPLEMENTED CHANGES

### 1. Jump Confirmation Frames (Line 102)
**Before**: `JUMP_CONFIRM_FRAMES = max(int(os.environ.get("JUMP_CONFIRM_FRAMES", "3")), 1)`  
**After**: `JUMP_CONFIRM_FRAMES = max(int(os.environ.get("JUMP_CONFIRM_FRAMES", "7")), 1)`  

**Impact**: Increased from 3→7 frames for better detector noise filtering.

### 2. Safe Zone Radius (Line 138)
**Before**: `self.safe_zone_radius = self.crop_width * 0.25`  
**After**: `self.safe_zone_radius = self.crop_width * 0.40`  

**Impact**: Increased safe zone from 25% to 40% of crop width for better framing stability.

### 3. Headless Torso Bug Fix (Lines 165-182)
**Enhancement**: Modified `begin_scene()` to:
- Reset all jump confirmation state
- Reset camera position to center (`self.current_center_x = self.video_width / 2`)  
- This ensures instant snapping to first detection in new scene

**Impact**: Eliminates ~1.5s "headless torso" during scene transitions.

### 4. Clip Selection Batch Fix (Lines 84-129)
**Before**: Filtered out single-window batches  
**After**: Removed the filter and included all batches  

**Impact**: Prevents legitimate tail content from being dropped; improves clip count consistency.

### 5. Clip Duration Bounds (Line 186)
**Before**: `if hi < lo + 5.0:`  
**After**: `if hi < lo + 15.0:`  

**Impact**: Ensures minimum 15-second band for model flexibility, preventing degenerate ranges.

### 6. Score Batches Distribution (Lines 113-129)
**Change**: Removed the `if batch and len(batch) >= 2` filter  
**Added**: `if batch:` (only filter empty batches)  

**Impact**: Better batch distribution, includes all legitimate windows.

---

## ⏳ PENDING CHANGES

### 6. Layout Picker Determinism
**Location**: `D:\openshorts\layout_picker.py`  
**Change Needed**: Add `temperature=0` to Gemini calls for deterministic output  
**Status**: Not yet implemented - requires finding where Gemini is called  

### 7. Subtitle Timing Validation
**Location**: `D:\openshorts\subtitles.py`  
**Change Needed**: Add test coverage for multi-fragment word merging (e.g., "You" + "Tube" + "-Kanal")  
**Status**: Implementation correct, needs validation  

### 8. SpeakerTracker Regression Test
**Status**: Already fixed - the test documents a previously fixed bug  
**Verification**: Test passes when run manually