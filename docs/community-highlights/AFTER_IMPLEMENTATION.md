# Community Highlights: After Implementation

**Status:** Initial feature rollout accepted with tracked refinements  
**Active branch:** `fix/community-highlights-google-oauth`  
**Release version being prepared:** `v0.3.3`  
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

**Observed:** A Community Highlights candidate can be shorter than 45 seconds, but generation can reject it before the normal pipeline starts.

**Confirmed cause:** The shared `MIN_SOURCE_SECONDS` guard defaults to 45 seconds and is applied to the staged Community Highlights candidate in `app.py`, as well as ordinary uploaded sources. A chat-triggered candidate is already a bounded highlight rather than a full-length source video, so applying the same source minimum creates a contract mismatch.

**Preferred refinement:** Introduce a source-specific duration policy for Community Highlights candidates. Preserve the existing minimum for ordinary URL/file uploads unless a separate product decision changes it. Do not simply lower the global minimum.

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

**Preferred refinement:** Keep the requested window as the source of truth, record the actual assembled duration and effective boundaries, and make the allowed tolerance explicit. If exact boundaries are a product requirement, evaluate trimming/re-encoding only at the final assembly boundary rather than complicating the rolling capture path.

**Acceptance criteria:**
- Persisted settings used by the trigger coordinator match the values shown as saved in the UI and survive restart.
- A single trigger produces a measured output duration within a documented tolerance of the requested pre + post duration.
- Tests cover segment-boundary rounding, delayed segment completion, filesystem timestamp drift, gaps, and merged triggers.
- The UI distinguishes requested pre/post values from the actual candidate duration and indicates when multiple triggers expanded a candidate.
- No media is silently presented as frame-accurate until the timeline is made frame-accurate.

### P1: Candidate triggers sometimes occur without the configured phrase

**Observed:** A candidate can be created even though the configured phrase is not present in the recent chat.

**Confirmed behavior that likely explains some reports:** A rule currently fires when **either** a phrase matches **or** the chat-volume threshold is reached. The default volume rule is 12 messages from at least 5 unique viewers within 10 seconds. That path deliberately creates a candidate without a phrase; the candidate's reason is recorded as `chat_volume` rather than `phrase`.

This means a trigger without the phrase is not automatically evidence of a phrase-matching defect. The current UI also exposes the volume thresholds alongside the phrases, but the distinction deserves much stronger explanation and visibility.

**Further investigation:** If candidates still appear unexpectedly when neither the phrase nor the configured volume threshold was met, capture a redacted event trace of message counts, unique sender counts, configured window, cooldown, and the candidate reason. Check provider message duplication, reconnect overlap, phrase normalization/substring matching, and candidate merging. Do not log raw chat content or viewer identifiers.

**Preferred refinement:**
- Make phrase-only, volume-only, and combined triggering explicit user-selectable modes, or provide an equally clear enable/disable control for the volume rule.
- Show the trigger reason on each candidate and in its detail view.
- Explain the active thresholds before monitoring starts.
- Keep phrase matching deterministic and add tests for punctuation, whitespace, casing, substring false positives, duplicate messages, cooldowns, and out-of-order events.

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

These are already present in the implementation plan and remain follow-up work rather than newly confirmed defects:

- Complete live Twitch authorization, chat, rolling capture, candidate extraction, and disconnect acceptance.
- Test long-running provider reconnects, quota/rate-limit handling, and terminal chat states.
- Measure trigger-to-media timeline drift on real authorized streams.
- Define a total candidate-media age/byte budget and disk-pressure behavior.
- Improve setup and troubleshooting documentation, including provider-specific error guidance.
- Revisit exact frame trimming and candidate boundary editing after the duration measurements are available.

## Release-prep verification record

For the PR head that included the Gemini-key handoff fix, GitHub Actions reported:

- Backend CI full test job: passed.
- Dashboard unit tests and production build: passed.
- Windows desktop validation: passed, including synchronized-version validation, PowerShell payload contracts, Python syntax, Whisper smoke, Rust checks/tests, and NSIS installer build.
- CPU/CUDA runtime rebuilds: skipped because the Python runtime package did not change.

The user's live test additionally confirmed that the approved candidate reached the standard results card and generated a clip.

These checks establish a solid merge baseline, but do not imply that the post-implementation items above have been fixed. The CI run predates the `v0.3.3` metadata-only version bump; the version-bump commit must pass the same workflows before merge.

## Working rule

Fix these items incrementally, one stable issue at a time. For each fix, add a focused regression test that protects the intended behavior, update this register, and keep unrelated pipeline behavior unchanged.
