# Community Highlights: After Implementation

**Status:** Initial feature merged; post-implementation corrections in progress  
**Merged baseline:** `main` contains Community Highlights and version metadata `0.3.3`; tag/publication status must be verified separately.  
**Active correctness branch:** `fix/community-highlights-correctness` (draft PR #42)  
**Active timing-metrics branch:** `fix/community-highlights-window-metrics` (draft PR #44)  
**Active UI branch:** `ui/community-highlights-workflow` (draft PR #43)  
**Last updated:** 2026-11-26

## Purpose

This document is the post-implementation register for issues observed while using Community Highlights, UI refinements, and follow-up investigations. It is deliberately separate from the [implementation plan](IMPLEMENTATION_PLAN.md), which tracks implementation milestones, integration work, and technical acceptance.

The current release is intended to make the working feature available while these refinements are handled incrementally. The items below are not silently treated as fixed, and their acceptance criteria should be used when each is addressed.

## What is implemented

The current feature path includes:

- Google and Twitch provider authorization code, with provider credentials stored in Windows Credential Manager.
- Live chat monitoring for a selected stream and a separate Streamlink/FFmpeg rolling media buffer.
- Configurable phrase and chat-volume trigger rules, plus configurable pre-trigger and post-trigger windows.
- Candidate extraction, merging of nearby trigger windows, persistent candidate/review state, inline preview, download, reject, and delete actions.
- An approval handoff into the existing Clippy processing pipeline, targeting one vertical Short rather than introducing a separate renderer or job queue.
- Generation status synchronization so the candidate reflects the normal pipeline job lifecycle.

**User-verified on 2026-11-26:** an approved candidate successfully entered the normal pipeline, generated a clip, and opened the standard results card for that job. This confirms the end-to-end handoff path in the user's current test environment. It does not substitute for testing every provider or all stream/media boundary cases.

**Provider coverage note:** YouTube chat/capture/candidate preview and the approval-to-results handoff have been exercised by the user. Twitch live capture and chat remain unverified in the current acceptance record.

## Known issues and refinement backlog

### P1: Approved candidates shorter than 45 seconds are rejected

**Observed:** A Community Highlights candidate can be shorter than 45 seconds, but generation previously rejected it before the normal pipeline started.

**Confirmed cause:** `app.py` applied the generic `MIN_SOURCE_SECONDS` guard to the staged candidate. That guard defaults to 45 seconds and is intended for ordinary URLs/uploads, not already-trimmed highlight media.

**Fix authored on `fix/community-highlights-correctness`:** Keep the generic 45-second guard unchanged for ordinary sources. Validate a Community Highlights candidate against the clip selector's actual minimum duration instead. A valid 30-second candidate should pass; media shorter than the configured clip-selection minimum gets a candidate-specific explanation. A regression test sets the generic guard to 45 seconds and exercises a 30-second candidate. PR #42 backend/frontend CI and Windows desktop validation passed on 2026-11-26; the NSIS installer build passed. The clean first-run CPU runtime smoke and CPU/CUDA rebuild jobs were skipped because no Python runtime inputs changed.

**Acceptance criteria:**
- A valid, readable approved candidate shorter than 45 seconds can enter the one-Short pipeline.
- Ordinary uploads and URL sources still follow the existing `MIN_SOURCE_SECONDS` rule.
- Empty, unreadable, or too-short-to-process candidates fail with a clear, source-specific message and leave the candidate retryable.
- Idempotency, source-file preservation, and candidate generation-state recovery continue to work on failure.

### P1: Requested pre/post windows do not always match the output duration

**Observed:** Setting values such as 30 seconds before and 30 seconds after does not always produce footage with those exact boundaries.

**Implementation findings and likely contributors:**
- The candidate window is calculated from the trigger timestamp and the configured pre/post values.
- The timeline maps completed segments to wall-clock intervals using file modification time and the segment's media duration. This is an estimate, not a frame-accurate clock.
- Segment selection includes whole overlapping MPEG-TS segments. Candidate assembly remuxes those segments into MP4 with stream copy (`-c copy`), rather than trimming/re-encoding at the exact requested boundaries.
- Nearby triggers can be merged into one candidate before it is sealed. The merged candidate intentionally uses the union of the requested windows, so it can be longer than the settings for the first trigger alone.
- Capture segment length is therefore relevant to the boundary precision. The default segment size is four seconds.

These findings explain why the current implementation can differ from an exact 30/30 split, but they do not quantify the drift on every real stream. The observed cases should be measured before choosing a fix.

**Current implementation on `fix/community-highlights-window-metrics`:**
- Persist the candidate's requested/effective UTC window bounds (`window_start` / `window_end`) in the candidate snapshot and state store. Older records without these fields restore with null bounds.
- After MP4 assembly, use FFprobe to measure the actual container duration. Prefer `FFPROBE_PATH`, then FFprobe beside the configured FFmpeg executable, then PATH. This runs after assembly and is best-effort: missing/unavailable FFprobe or invalid output leaves the candidate ready with `actual_duration_seconds: null`.
- Persist and restore `actual_duration_seconds` when it is finite and positive. Invalid saved metrics are discarded. No rolling capture or stream-copy behavior is changed.

**Important limitation:** this measures the output file's duration. It does not prove that the chat trigger was aligned to the exact requested wall-clock boundaries. The filesystem-mtime timeline estimate and whole-segment selection remain approximate, and merged candidates intentionally span the union of their windows.

**Remaining refinement and acceptance:**
- Measure drift between trigger receipt and video content on authorized real streams, separately for YouTube and Twitch.
- Test segment-boundary rounding, delayed segment completion, filesystem timestamp drift, gaps, and merged triggers using reproducible fixtures.
- Display requested bounds, measured actual duration, and merged-trigger count as distinct values. Never calculate or label the difference as exact timing error until wall-clock alignment has been measured.
- Decide whether final-stage trimming is required only after the real-stream measurements. Do not re-encode the rolling buffer.
- No media is presented as frame-accurate until the timeline itself is made frame-accurate.

### P1: Candidate triggers sometimes occur without the configured phrase

**Observed:** A candidate can be created even though the configured phrase is not present in recent chat.

**Confirmed existing behavior:** The old trigger rule fired when **either** a phrase matched **or** chat-volume reached its threshold. The default volume rule is 12 messages from at least 5 unique viewers within 10 seconds. A candidate without the phrase could therefore be expected under the previous default configuration.

**Additional confirmed causes:**
- The trigger engine used local receipt time for chat-volume windows. YouTube can return messages in batches, so messages published across more than the configured window could arrive together and appear to be a burst.
- Transient YouTube retries discarded the live-chat continuation token. The original session-start check did not suppress all backlog replayed after a later reconnect.
- Saving settings rebuilt the trigger engine and discarded in-memory provider-message deduplication and cooldown state.
- Phrase matching used substring matching, allowing false positives such as a configured phrase inside a larger word.

**Fixes authored on `fix/community-highlights-correctness`:**
- Use provider publication timestamps for trigger windows/cooldowns while retaining local receipt time for trigger-to-capture coordination.
- Preserve YouTube's live-chat ID, continuation token, and latest publication-time watermark across retries within the same running chat session. Older replayed backlog stays visible but is not sent to trigger evaluation.
- Preserve deduplication and cooldown state when rules are updated.
- Normalize Unicode, punctuation, and whitespace before deterministic whole-phrase matching.
- Expose `phrases`, `chat_volume`, and `either` modes; older saved settings default to `either` so existing behavior is preserved.

Focused regression tests are authored, and PR #42 backend/frontend CI plus Windows desktop validation passed. Live acceptance for YouTube reconnect/backlog suppression and Twitch remains pending.

**Acceptance criteria:**
- Phrase-only mode never creates a candidate from chat volume alone.
- Volume-only mode never requires a configured phrase.
- Combined mode retains the current OR behavior and identifies the actual reason for each candidate.
- Duplicate provider events and reconnect replays do not cause duplicate candidates.
- Diagnostics remain content-free and do not expose raw chat text, stream URLs, or viewer IDs.

### P1: Major Community Highlights UI redesign

**Observed:** The current UI is difficult to scan and needs a substantial redesign before the feature feels polished.

**Desired direction:**
- Organize the page around the actual workflow: connect provider, select stream, start chat and recording, configure triggers, review candidates, then generate.
- Make chat monitoring and rolling capture status obvious, with clear controls for start, stop, and errors.
- Separate normal settings from advanced capture/trigger settings, and explain which settings apply to new sessions versus active sessions.
- Make phrase and volume trigger modes visually distinct.
- Give candidates a compact summary: trigger reason, stream/provider, requested window, actual duration, trigger count, preview, and generation state.
- Make candidate review and approval actions unambiguous, with progress and retry states.
- Improve spacing, hierarchy, responsive behavior, and empty/error/loading states. Avoid a dense settings wall.

**Acceptance criteria:** The complete workflow is usable at the supported desktop window sizes without awkward scrolling or ambiguous controls, all states have a clear user-facing explanation, and the redesigned UI keeps the existing backend API contracts unless a specific contract change is justified.

### P2: Remaining operational hardening

The following items remain open after the source audit and are not covered by the first correctness batch:

- Complete live Twitch authorization, chat, rolling capture, candidate extraction, and disconnect acceptance.
- Complete packaged-Windows acceptance for YouTube reconnect/cursor recovery and Twitch IRC `RECONNECT`, alongside Twitch live chat, capture, candidate extraction, and disconnect.
- Test long-running provider reconnects, quota/rate-limit handling, and terminal chat states.
- Measure trigger-to-media timeline drift on real authorized streams. The chat-rule clock fix does not make the current segment-mtime/duration capture alignment frame-accurate.
- Define a total candidate-media age/byte budget and disk-pressure behavior.
- Improve setup and troubleshooting documentation, including provider-specific error guidance.
- Revisit exact frame trimming and candidate boundary editing after the duration measurements are available.

## Lifecycle and restart clarification

Candidate metadata and review decisions are persisted and restored by the current backend. Completed candidate MP4s are preserved across a backend restart when their paths pass the storage checks. Active chat connections are not resumed. Active rolling captures and in-progress candidate assembly workers cannot resume; they are marked interrupted/failed and disposable rolling segments are cleaned during startup reconciliation. Trigger-engine message IDs, recent-message windows, and cooldown state are in memory and do not survive a backend process restart. The new YouTube continuation fields are also session-memory state, not durable restart state.

This corrects the older implementation note that candidate metadata was memory-only. It does not mean interrupted live capture or extraction can continue after a process restart.

## Pre/post duration: measurable, but not yet precise

The capture timeline still estimates segment wall time from filesystem modification time plus FFmpeg media duration. Extraction includes whole overlapping TS segments and remuxes with stream copy. Nearby triggers intentionally merge into the union of their requested windows. Capture settings are snapshotted when a buffer starts, so edits do not change an already-running capture.

**Implemented on `fix/community-highlights-window-metrics` (draft PR #44):** candidate snapshots and durable state now retain the effective UTC `window_start`/`window_end` bounds. After assembly, FFprobe records the completed MP4's `actual_duration_seconds` when available. Probe failure is fail-open and leaves the candidate ready with a null measurement. Older candidate state without these fields remains compatible.

The measured MP4 duration describes the resulting file; it does not prove the video content is aligned to the exact chat-relative wall-clock boundaries. Segment mtime drift, keyframe/segment edges, and intentional merging still need real-stream measurement. Final-stage trimming should be considered only after those measurements. Do not re-encode the rolling buffer.

## Current UI scope

The full workflow-first redesign is authored separately on `ui/community-highlights-workflow` (draft PR #43). It combines chat and recording start/stop, makes partial state recoverable, keeps provider connections reusable, collapses advanced capture settings and diagnostics, distinguishes saved trigger settings, and simplifies candidate review with trigger reason and merged-trigger count. The candidate row displays measured MP4 duration when the optional backend field is available.

The dashboard/backend CI run for the current UI branch passed. Packaged-Windows responsive acceptance and live start/stop testing remain pending.

## Release-prep verification record

For the PR head that included the Gemini-key handoff fix, GitHub Actions reported:

- Backend CI full test job: passed.
- Dashboard unit tests and production build: passed.
- Windows desktop validation: passed, including synchronized-version validation, PowerShell payload contracts, Python syntax, Whisper smoke, Rust checks/tests, and NSIS installer build.
- CPU/CUDA runtime rebuilds: skipped because the Python runtime package did not change.

The user's live test additionally confirmed that the approved candidate reached the standard results card and generated a clip.

Current follow-up validation record (2026-11-26):
- Correctness PR #42: backend test suite and dashboard build passed; Windows desktop validation passed, including NSIS installer build. CPU/CUDA runtime rebuilds and clean-first-run CPU smoke were skipped because the Python runtime inputs did not change.
- Workflow UI PR #43: backend test suite and dashboard unit/build job passed for the current UI head. It is stacked on PR #42, so packaged-Windows validation remains pending.
- Window-metrics PR #44: backend test suite and dashboard build passed. It is stacked on PR #42; packaged-Windows verification of FFprobe discovery/fail-open behavior remains pending.

These checks do not replace live provider/timing acceptance. No live Twitch acceptance or real-stream pre/post drift measurement is claimed.

## Working rule

Fix these items incrementally, one stable issue at a time. For each fix, add focused regression tests, update this register, and keep unrelated pipeline behavior unchanged. Keep the full Community Highlights UI redesign separate from correctness fixes so it can be reviewed as one coherent workflow.
