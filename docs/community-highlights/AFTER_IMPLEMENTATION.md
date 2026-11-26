# Community Highlights: After Implementation

**Status:** Initial feature merged; post-implementation corrections in progress  
**Merged baseline:** `main` contains Community Highlights and version metadata `0.3.3`; tag/publication status must be verified separately.  
**Active fix branch:** `fix/community-highlights-correctness`  
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

**Fix authored on `fix/community-highlights-correctness`:** Keep the generic 45-second guard unchanged for ordinary sources. Validate a Community Highlights candidate against the clip selector's actual minimum duration instead. A valid 30-second candidate should pass; media shorter than the configured clip-selection minimum gets a candidate-specific explanation. A regression test sets the generic guard to 45 seconds and exercises a 30-second candidate. CI has not yet run.

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

Focused regression tests have been authored for the above behavior. CI and real provider acceptance are still pending.

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
- [x] Enforce a 5 GiB total candidate-media byte budget and retain 2 GiB free space on the output drive before assembly. A failed preflight affects only the new candidate; existing MP4s remain untouched. Candidate age is intentionally unbounded: ready media never expires automatically and remains until the user rejects or explicitly deletes it.
- Improve setup and troubleshooting documentation, including provider-specific error guidance.
- Revisit exact frame trimming and candidate boundary editing after the duration measurements are available.

### Candidate media storage and retention policy

Candidate MP4 storage is capped at 5 GiB across Community Highlights capture folders. Before stream-copy assembly, Clippy estimates output size from the selected TS segments using the larger of 5% or 16 MiB as overhead, accounts for concurrent in-flight reservations, and requires at least 2 GiB of free space to remain on the output drive. If either limit would be exceeded, only the new candidate fails with an actionable message. Existing ready, approved, or pending MP4s are never removed to make room. There is no automatic age expiry; candidate media remains until the user rejects or explicitly deletes it. Orphaned and deletion-pending MP4 files are included in the byte count and are not silently removed.

## Lifecycle and restart clarification

Candidate metadata and review decisions are persisted and restored by the current backend. Completed candidate MP4s are preserved across a backend restart when their paths pass the storage checks. Active chat connections are not resumed. Active rolling captures and in-progress candidate assembly workers cannot resume; they are marked interrupted/failed and disposable rolling segments are cleaned during startup reconciliation. Trigger-engine message IDs, recent-message windows, and cooldown state are in memory and do not survive a backend process restart. The new YouTube continuation fields are also session-memory state, not durable restart state.

This corrects the older implementation note that candidate metadata was memory-only. It does not mean interrupted live capture or extraction can continue after a process restart.

## Pre/post duration: still open

The current capture timeline estimates segment wall time from filesystem modification time plus FFmpeg media duration. Extraction includes whole overlapping TS segments and remuxes with stream copy. Nearby triggers intentionally merge into the union of their requested windows. Capture settings are snapshotted when a buffer starts, so edits do not change an already-running capture. The manual “Clip now” action currently sends the values in the UI, while automatic chat triggers use persisted backend settings; the UI must make saved versus unsaved settings explicit.

The reliable next step is to persist/display requested bounds and actual candidate duration, include merged-trigger count, and measure real drift on an authorized live stream. Only then decide whether a final-stage trim is needed. Do not re-encode the rolling buffer.

## Current UI scope

The current branch adds the explicit trigger-mode selector only. It is **not** the requested full tab redesign. The complete redesign remains a separate implementation slice: one clear start/stop workflow for chat plus recording, streamlined main settings, collapsed advanced capture settings, visible state/errors, and compact candidate review with trigger reason/count and actual duration.

## Release-prep verification record

For the PR head that included the Gemini-key handoff fix, GitHub Actions reported:

- Backend CI full test job: passed.
- Dashboard unit tests and production build: passed.
- Windows desktop validation: passed, including synchronized-version validation, PowerShell payload contracts, Python syntax, Whisper smoke, Rust checks/tests, and NSIS installer build.
- CPU/CUDA runtime rebuilds: skipped because the Python runtime package did not change.

The user's live test additionally confirmed that the approved candidate reached the standard results card and generated a clip.

These historical checks establish a merge baseline for the feature branch; they do not validate the current correctness branch. The current branch must pass its own backend, dashboard, and Windows validation workflows before it is ready to merge.

## Working rule

Fix these items incrementally, one stable issue at a time. For each fix, add focused regression tests, update this register, and keep unrelated pipeline behavior unchanged. Keep the full Community Highlights UI redesign separate from correctness fixes so it can be reviewed as one coherent workflow.
