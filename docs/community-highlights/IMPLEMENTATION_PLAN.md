# Community Highlights Implementation Plan

**Status:** In progress  
**Active working branch:** `fix/community-highlights-google-oauth`  
**Base:** `main` at `38fe25cadcc7709ea69f9761a815b3f29ff25d1e` (stable release `v0.3.2`)  
**Historical branch:** `feature/community-highlights` (superseded; retained for history)  
**Product:** Clippy  
**Last updated:** 2026-11-24

## Code audit follow-up register

This register records findings from the dated source audits below. A checked item means the code change is implemented; it does not imply that automated tests, live-provider acceptance, or packaged-Windows behavior have passed.

### Batch 1 — desktop OAuth configuration and Windows data paths
- [x] Package Twitch and Google public OAuth client IDs into the desktop payload, load them in the Tauri supervisor, and pass them explicitly to the managed backend. Release publishing must fail before runtime builds when either required public ID is missing.
- [x] Persist compatible Windows paths for newly selected data directories, normalize legacy Win32 extended-prefix drive/UNC values before PowerShell path operations, and reject paths that require extended-length handling rather than stripping their prefix unsafely.
- [ ] Configure the shared repository Actions Variable `CLIPPY_GOOGLE_OAUTH_CLIENT_ID` for Google/YouTube authorization. `CLIPPY_TWITCH_CLIENT_ID` is optional during this test phase; if blank, Twitch sign-in stays disabled without affecting Google. Both values are public client identifiers, not secrets. RC and stable builds use these same variable names.

### OAuth application identity and environment separation
- [x] Record that the current Google OAuth project and Twitch developer application are temporary testing registrations. Their current display names, support/contact details, and client IDs are not the final Clippy production identity.
- [ ] Before public production release, revisit OAuth registration and branding under the final Clippy brand and brand-owned support email. Update the existing generic Actions Variables to the approved public Client IDs after review. The current workflow does not split RC and stable identities. Never put client secrets in the desktop payload or Actions Variables.
- [ ] Decide whether to move to separate development and production OAuth registrations during production cleanup. This separation is deliberately not part of the current test workflow.
- [ ] Implement production-specific OAuth identities only during the later production-cleanup phase, if required by the final provider registrations. Current RC and stable builds use one shared Google ID and one optional shared Twitch ID.
- [ ] For Google production readiness, confirm the app audience/publishing status, test-user restrictions, consent-screen branding, verified homepage/privacy-policy/terms links on a domain controlled by the Clippy brand, requested-scope classification, and any required brand/scope verification. Google documents that External apps in Testing are limited to 100 test users and authorizations for non-basic scopes expire after seven days; production publication and verification requirements depend on the requested scopes and branding. See the Google OAuth production checklist in the work log below.

### Remaining audit work
- [ ] Identify the historical Community Highlights `404 not found` on the user's installed RC. The original failing request trace was not available, so the precise cause is not yet established.
- [x] Add HTTP-level tests against the actual FastAPI app for connection status, Twitch/Google OAuth start/status/cancel, desktop-session-token enforcement, known-flow 404s, and unknown-route 404s.
- [x] Add targeted backend diagnostics for failed Community Highlights requests. Logs record method, matched route template (or redacted unmatched path), and status only; they omit request bodies, query strings, opaque flow/candidate IDs, and authorization headers.
- [x] Fix approved-candidate queue exhaustion with an explicit candidate DELETE API and dashboard control. Delete removes the candidate's local media before its metadata, refuses in-progress workers, validates the generated path remains under the capture root, and preserves metadata if Windows refuses to unlink a locked file. No candidate status is silently pruned when the queue reaches its cap.
- [ ] Persist trigger settings, capture/candidate metadata, review decisions, and recovery state across backend restart. Mark interrupted captures explicitly on startup. Keep provider tokens in Windows Credential Manager, not SQLite.
- [ ] Complete provider/capture lifecycle verification: mocked provider lifecycle/reconnect tests are incomplete; run authorized Twitch/YouTube chat and Streamlink/FFmpeg capture checks on Windows; verify audio/video continuity, timestamps, disconnect handling, and graceful shutdown. Chat reconnect exists, but capture-worker recovery is not yet proven or implemented as a bounded reconnect path.
- [ ] Validate trigger-to-media timeline drift against real captured segments. Current wall-time alignment estimates segment intervals from filesystem modification time and FFmpeg duration; it is not frame-accurate proof.
- [ ] Merge overlapping or nearby trigger windows so several reactions to one moment do not create duplicate candidates.
- [ ] Finish M4 candidate workflow: footage analysis and suggested boundaries, inline preview, frame-accurate trimming, reuse of existing edit components, and handoff of approved candidates to the renderer.
- [ ] Finish M5 hardening: review/automatic/hybrid modes, bounded retention and cleanup, structured diagnostics, long-running/restart recovery, and user-facing setup/troubleshooting documentation.
- [ ] Clarify development-platform scope: the secure credential adapter intentionally requires Windows Credential Manager and fails closed on non-Windows hosts. Docker/Linux can run the backend but cannot complete provider OAuth without a deliberate non-production credential-store strategy.
- [x] Correct the authorization-window edge case: create a blank tab synchronously from the click, set its `opener` to `null` before provider navigation, and use the same helper for the reopen action. Add executable Node tests for popup blocking, opener isolation, navigation ordering, and closed windows.
- [x] Serialize OAuth device/code exchanges, refresh-token writes, and provider disconnect through one provider-specific credential lifecycle lock. Disconnect cancels pending flows while holding that lock, stops chat sessions, revokes the latest saved grant when possible, and then removes local credentials. Add race tests proving disconnect waits for a refresh or OAuth exchange to finish before deleting its resulting credential bundle.
- [x] Remove the redundant Google `tokeninfo` request from the initial authorization-code callback; verify the granted YouTube scope from the token endpoint response while retaining PKCE, state, exact Client ID use, and refresh-time token validation.
- [x] Add phase-specific, credential-safe Google OAuth callback diagnostics and mocked success/failure tests for authorization-code exchange, scope validation, and secure credential persistence.
- [ ] Run the focused Google OAuth tests and a real packaged-Windows sign-in attempt on the active fix branch. Capture the safe backend phase diagnostic if the live flow still fails; do not log tokens, codes, callback query strings, or PKCE material.




### Branch status — 2026-11-24

- `main` is the authoritative base at `38fe25cadcc7709ea69f9761a815b3f29ff25d1e`, which is the commit underlying stable release `v0.3.2`.
- The original `feature/community-highlights` branch is a historical implementation snapshot. Its feature work was merged through PR #28; subsequent OAuth, packaging, browser-handoff, and provider-UI fixes were merged separately into `main`. Keep the branch for provenance, but do not continue development on it or merge it again.
- New work starts from `main` on `fix/community-highlights-google-oauth`. This branch is the active home for the current post-consent Google OAuth repair. The historical branch is not deleted or force-moved.

## 2026-11-24 implementation review

This review compares the current `main` source at the base commit above with the milestones and claims in this plan. A checked implementation item means the code exists; it does not mean the provider or media path has passed live acceptance.

### Confirmed implementation already present

- Provider authentication is separated from Clippy account login. Twitch uses a public Device Code flow; Google uses a desktop loopback flow with state and PKCE. Provider tokens are kept in Windows Credential Manager, and the packaged desktop supervisor supplies public OAuth Client IDs to the backend.
- Chat adapters, bounded in-memory session management, phrase/volume triggers, Streamlink resolution, FFmpeg rolling segments, segment pinning, extraction, candidate review decisions, candidate download, and explicit candidate deletion are implemented.
- The dashboard exposes provider connections, monitoring, rolling capture, trigger settings, and candidate status/review.
- Focused mocked tests exist across the provider, trigger, timeline, capture, credential-store, and API modules. The current source still lacks proof of live-provider and real-media behavior.

### Open gaps, ordered by risk

**P0 — correctness before relying on automatic highlights**

1. **Two clocks are mixed in trigger evaluation.** `TriggerEngine.add()` uses provider timestamps for message-window membership and cooldowns, while `TriggerMatch.triggered_at` uses local receipt time and the capture timeline is estimated from local file modification times. Provider clock skew, delayed delivery, or out-of-order chat messages can therefore change trigger decisions while capture uses a different clock. Use local receipt timestamps consistently for window/cooldown evaluation; retain provider timestamps as evidence/metadata. Add skewed and out-of-order event tests.
2. **Automatic trigger failures can disappear silently.** `TriggerCoordinator.on_message()` catches `ValueError` and `RollingCaptureError` from candidate creation and continues without a log or UI-visible event. Queue-full, insufficient-buffer, and capture-state conflicts can therefore drop a trigger with no actionable feedback. Surface a bounded diagnostic/event to the monitor and test each rejected-trigger reason.
3. **Segment pinning can race with rolling-buffer pruning.** `RollingCapture._prune_segments()` snapshots the protected set under its lock but unlinks segments after releasing the lock. A trigger can pin a segment after that snapshot and still lose the file to the in-progress prune pass. Serialize the final protected check and unlink with `protect_segments()`; add a deterministic concurrency regression test.
4. **Capture settings and trigger windows are not validated as one contract.** Capture start validates basic segment/retention limits, while `CaptureSessionManager.trigger()` later rejects windows when retention is less than pre + post + one segment. Pre-trigger segments are pinned immediately, but post-trigger segments are not pinned incrementally while `_finish_candidate()` waits for the post window, so those early post segments can age out before extraction. Define one explicit retention/pinning strategy: either pin completed post segments as they arrive or require enough retention for the unpinned post window. Validate/warn when settings are saved or a capture starts, and make automatic-trigger rejection visible.

**P1 — provider and capture resilience**

5. **YouTube API failures are classified too broadly.** The chat loop treats every HTTP 400/403/404 as terminal, although YouTube can use 403 for quota and rate-limit reasons that need provider-reason-aware handling and bounded backoff. Parse safe API error reasons, distinguish ended/disabled chat from quota/rate limits, and test retry-after/polling behavior. Do not blindly retry permanent permission errors.
6. **Capture has no bounded reconnect path.** Chat sessions reconnect with bounded backoff, but Streamlink/FFmpeg capture currently ends when its reader returns EOF or errors. Implement capture reconnect only after defining segment continuity, timestamp discontinuity, retry budget, and a clear terminal state; never silently concatenate across an unverified gap.
7. **Timeline alignment remains an estimate.** Segment wall intervals are derived from file modification times minus media duration. This is not frame-accurate, and the 2-second coverage tolerance is not evidence of acceptable drift. Measure drift on authorized Twitch and YouTube streams on Windows before claiming dependable pre/post boundaries.
8. **Quota and resource budgets need end-to-end limits.** Active chats/captures and rolling bytes are bounded, but YouTube API quota consumption, total candidate-media bytes, candidate age, and disk-pressure behavior do not yet have explicit product-level budgets.

**P2 — complete the actual highlight workflow**

9. **Approval is not renderer handoff.** Approve currently records an in-memory review decision; it does not create a normal Clippy job. Candidate footage is downloadable as MPEG-TS, but there is no inline playable preview, frame-accurate trim, MP4 export, or renderer handoff.
10. **Candidate state and trigger settings are volatile.** Sessions, trigger rules, candidates, and review decisions live in process memory. Restart loses the index/decisions and can leave media directories orphaned. Add durable metadata and startup reconciliation before unattended use; mark interrupted captures explicitly.
11. **Hybrid automation is still only a product decision.** Review-only, automatic, and hybrid modes are not implemented. Add explicit approval policy and safeguards only after persistence and renderer handoff exist.
12. **Operational diagnostics and user guidance are incomplete.** The new Google OAuth callback has phase-safe diagnostics, but provider chat, trigger rejection, capture synchronization, FFmpeg assembly, restart recovery, and renderer handoff still need structured, user-actionable diagnostics and troubleshooting documentation.

### Plan consistency corrections

- M1 chat reconnect/backoff is implemented in code, but provider lifecycle tests and live chat acceptance remain pending. Keep implementation and verification status separate.
- M2 Streamlink/FFmpeg and M3 trigger/candidate code exists, but live Windows continuity, clock drift, and restart behavior remain unverified.
- M4 currently means candidate status/download/approve/reject only. Its exit criteria are not met because preview, trim, analysis, and renderer handoff are absent.
- M5 rolling-segment age/size limits and session concurrency limits exist; this does not constitute complete candidate retention, disk-pressure policy, recovery, or unattended automation.
- The original progress log predates the Google browser-handoff and provider-action-gating merges (PRs #33 and #34) and the stable `v0.3.2` promotion (PR #37). The OAuth hardening from PR #32 is represented in the batch-3 entry, but its final merged validation outcome was not recorded there. The current baseline and later validation outcomes are recorded in the 2026-11-24 progress entry; future entries must continue to distinguish merged code, automated test results, and manual Windows/provider acceptance.


## Goal

Add a Clippy workflow that monitors a Twitch or YouTube live chat, detects configurable community reactions, captures the corresponding live footage, proposes a highlight, and lets the user review or automatically process it.

The user-facing starting point should be a pasted Twitch or YouTube live URL. No OBS setup, browser extension, or manual recording should be required for the intended Streamlink-based prototype.

This plan is deliberately incremental. Implement and verify one working slice at a time; do not build the entire feature before proving the provider and capture foundations.

## Decisions already made

- Support **Twitch and YouTube**.
- The user supplies a **stream URL**.
- Prototype video acquisition uses **Streamlink**, with FFmpeg for recording and extraction.
- Capture windows are runtime-configurable. Pre-trigger and post-trigger durations must never be hardcoded into the capture implementation.
- Automation is **hybrid**: candidates can require review or be processed automatically according to user settings.
- The first implementation milestone is **Twitch and YouTube chat connectivity**, before video capture.
- Do not require OBS, browser automation, or a separate user-facing recorder.
- Keep this feature isolated from the existing clip-generation pipeline until a candidate is approved or auto-approved.
- Avoid broad CI runs and Windows installer validation. Run focused tests for changed behavior; run platform validation only when a change actually affects that platform or packaging contract.

## Authentication and connection UX decisions

- Community Highlights is a first-class navigation tab. The provider connection panel is a single reusable component rendered both in that tab and in Settings & Integrations. Both placements read and mutate the same backend connection state.
- Use concise provider actions: **Sign in with Twitch** and **Sign in with Google**. Do not label the Google action "Connect YouTube with Google".
- Twitch uses its public-client Device Code Grant. On click, Clippy requests a device authorization, opens Twitch's returned activation URL (including its prefilled code) in the user's default browser, and polls in the background. The user signs in and approves in the browser; they should not have to copy a code into Clippy. Handle pending, slow-down, denial, expiry, cancellation, and network failures. Public-client refresh tokens are single-use: persist each replacement before considering refresh complete.
- Google uses the installed-desktop OAuth flow with a system browser, a loopback callback, state validation, and PKCE. It authorizes YouTube API access only; it is separate from Clippy account login. User-facing copy must explicitly say that Google is used to authorize YouTube live-chat access, does not sign the user into Clippy, and does not request Gmail access.
- Be accurate about Google's permission scope: YouTube Data API's `youtube.readonly` scope permits viewing YouTube account data and is broader than a single live chat. Do not claim the OAuth grant is limited to one stream or one chat. Request the narrowest scope the API supports for the selected read operation and explain the scope before authorization.
- Keep both provider connections optional and independent. Disconnecting one must not affect the other or Clippy account login.
- Persist provider access and refresh tokens in Windows Credential Manager. Never put tokens in browser storage, the normal Clippy settings JSON, callback URLs after exchange, logs, or frontend state. Connection-status APIs return only safe metadata, never credentials.
- Existing `cloud/oauth.py` remains exclusively for Clippy account login. Do not merge Community Highlights provider grants into that flow.
- The backend is a separately supervised Python process, while Tauri is the Windows desktop shell. Before implementation, establish a single secure credential-store boundary usable by the backend and packaged desktop runtime; do not assume a Rust-only credential store is automatically accessible to Python. Prefer a Windows Credential Manager-backed adapter with mocked tests and explicit failure behavior when the secure store is unavailable.
- OAuth client IDs are public application identifiers, not secrets, but must be registered by Clippy's app owner. Do not embed a client secret in the distributed desktop app. Verify required Twitch scopes for the chosen chat transport before implementing the connection.

## Proposed architecture

1. **Chat provider adapters**
   - Twitch adapter receives live chat events and normalizes them.
   - YouTube adapter receives live chat events and normalizes them.
   - Provider-specific authentication, reconnect, backoff, and rate-limit behavior stays inside each adapter.
2. **Trigger engine**
   - Evaluates configurable keywords/phrases, message counts, unique participants, detection windows, and cooldowns.
   - Deduplicates provider message IDs and prevents one chatter's repeated spam from satisfying unique-user thresholds.
   - Emits a provider-neutral trigger event with source timestamps and the matching evidence.
3. **Stream capture**
   - Streamlink resolves and reads the supplied live stream URL.
   - FFmpeg ingests the media and writes short rolling segments.
   - The rolling buffer retains enough footage for the configured maximum pre-trigger window plus safety margin.
   - A trigger protects the relevant earlier segments and requests the configured post-trigger duration.
   - Runtime settings control pre/post duration, quality, segment length, and retention. Existing captures retain the settings snapshot with which they started.
4. **Timeline and candidate assembly**
   - Align chat event timestamps with captured media timestamps.
   - Assemble the selected segments without unnecessary re-encoding where possible.
   - Merge overlapping/nearby triggers according to configurable rules.
5. **Highlight analysis and review**
   - Analyze only triggered captures, not the entire live stream.
   - Produce suggested clip boundaries and supporting trigger evidence.
   - Show candidates in a dedicated Community Highlights review workflow.
   - Approved candidates are handed to the existing Clippy editing/rendering pipeline.
6. **Persistence and lifecycle**
   - Persist sessions, provider cursors/IDs, trigger events, capture segments, candidate state, and automation decisions.
   - Recover or mark interrupted sessions/captures explicitly; do not silently lose candidates.
   - Bound disk usage and clean only unprotected expired segments.

## Milestones

### M0 — Repository and provider groundwork

- [x] Inspect repository instructions, main branch baseline, dependencies, backend entry points, and existing test conventions.
- [x] Create the feature branch and this implementation plan.
- [x] Trace existing credential/settings patterns before adding provider credentials or OAuth flows.
- [x] Confirm the backend runtime/deployment modes this feature must support (Docker development and packaged Windows desktop).

**Exit criteria:** implementation choices fit the current application architecture and do not introduce a second settings/authentication system unnecessarily.

### M1 — Twitch and YouTube chat connectivity (first implementation milestone)

- [x] Define a normalized chat-message model containing provider, stream ID, provider message ID, provider timestamp, local receipt timestamp, sender identity, and text. Emote normalization remains provider-adapter work.
- [x] Implement Twitch IRC live chat connection and message normalization.
- [x] Implement YouTube Data API live-chat polling and message normalization.
- [x] Implement connection lifecycle: start, stop, reconnect, bounded backoff, cancellation, and clear status/error reporting.
- [x] Parse supported Twitch channel and YouTube video/live URLs into provider-neutral stream references. Provider-specific live-chat ID resolution remains adapter work.
- [x] Add focused unit tests for normalized message validation, URL parsing, phrase/volume triggers, duplicate suppression, cooldowns, and rule-window behavior. Provider lifecycle tests remain pending.
- [ ] Add a small integration/smoke test path that can be run manually with a stream the developer can access; do not make live credentials a CI requirement.

**Exit criteria:** Clippy can accept a Twitch or YouTube live URL, connect to its chat, display/emit normalized messages, survive a transient disconnect, and stop cleanly. No video capture is included in M1.

### M2 — Streamlink/FFmpeg capture proof of concept

- [x] Add Streamlink as a pinned backend dependency and use its Python stream API. Packaged Windows import verification remains part of the acceptance pass.
- [x] Implement Twitch and YouTube URL resolution through Streamlink (live-stream smoke verification remains outstanding).
- [x] Implement the Streamlink-reader to FFmpeg-stdin stream-copy path (real process integration remains outstanding).
- [x] Implement FFmpeg segmented output and bounded age/size retention, including segment pin/release primitives (live continuity verification remains outstanding).
- [ ] Verify audio/video continuity, timestamp metadata, stream disconnect/reconnect behavior, and graceful shutdown on Windows.
- [x] Add a bounded capture-session manager with isolated output directories, immutable per-session settings snapshots, a two-session concurrency cap, safe status snapshots, and bounded worker shutdown.
- [x] Expose protected API operations to start, list, inspect, and stop capture sessions; stop owned capture and chat workers during API shutdown.
- [x] Add configurable pre-trigger/post-trigger window selection, segment protection, and lossless MPEG-TS assembly. The initial clock bridge estimates completed segment wall intervals from file modification times and FFmpeg segment durations; real-stream accuracy is not yet proven.
- [ ] Test capture and extraction with streams the developer is authorized to capture.

**Exit criteria:** an isolated backend proof of concept can capture a live stream from a URL, retain a bounded rolling buffer, and extract arbitrary configured time windows reliably. Code paths and mocked tests are in place; the live Windows proof remains outstanding.

### M3 — Trigger detection and capture coordination

- [x] Implement configurable phrase and community-volume rules, exposed through the Community Highlights monitor.
- [x] Add unique-user thresholds, provider-message deduplication, and per-rule cooldowns.
- [ ] Merge overlapping/nearby trigger windows to avoid duplicate candidates.
- [x] Coordinate chat receipt timestamps with completed rolling segments using a documented file-mtime/duration estimate. Validate drift on Windows before tightening accuracy guarantees.
- [x] Protect pre-trigger segments, wait for the configured post-trigger duration, validate coverage/gaps, and assemble the candidate without re-encoding.
- [ ] Persist trigger/candidate state and recover interrupted work after backend restart.

**Exit criteria:** a simulated or live chat trigger consistently produces the requested pre/post footage window. Mocked lifecycle coverage is authored; real Windows validation remains pending.

### M4 — Candidate analysis and review

- [ ] Analyze triggered footage and propose clip boundaries.
- [x] Create an in-memory candidate lifecycle with capture status, processing status, segment count, and error reporting. Durable persistence remains pending.
- [x] Add Community Highlights UI for candidate status, file download, approve, and reject.
- [ ] Add inline preview and frame-accurate start/end trimming.
- [ ] Reuse existing preview/editing components where appropriate.
- [ ] Route approved candidates into the existing Clippy renderer.

**Exit criteria:** a user can review a candidate, adjust its boundaries, and produce a normal Clippy output.

### M5 — Hybrid automation and hardening

- [ ] Add review-only, automatic, and hybrid processing modes.
- [ ] Add bounded disk retention and capture concurrency controls.
- [ ] Add structured diagnostics for provider, capture, synchronization, analysis, and rendering failures.
- [ ] Verify long-running sessions and recovery from backend restart.
- [ ] Document user-facing setup and troubleshooting.

**Exit criteria:** the feature can run unattended within configured resource limits and does not silently lose or duplicate candidates.

## Runtime configuration contract

All durations and thresholds are settings, not constants embedded in the capture workflow. Initial configuration should include:

- `pre_trigger_seconds`
- `post_trigger_seconds`
- `segment_seconds`
- `buffer_retention_seconds` (validated to cover the maximum pre-trigger window plus safety margin)
- `max_buffer_size_mb` or an equivalent bounded storage budget
- `stream_quality`
- trigger keywords, message/unique-user thresholds, detection window, and cooldown
- automation mode and candidate retention policy

Validate settings at the API boundary. Applying changed settings affects new triggers; an already-running capture uses an immutable settings snapshot.

## Engineering constraints

- Keep provider-specific protocol details out of the trigger engine and UI.
- Do not block FastAPI's event loop with Streamlink/FFmpeg process waits or synchronous network operations.
- Every background task/process must have an owner, cancellation path, timeout/health reporting, and cleanup path.
- Treat pasted URLs and provider payloads as untrusted input. Reuse existing URL validation and subprocess/environment-sanitization patterns where applicable.
- Do not pass server-only secrets into media subprocesses.
- Use argument arrays for subprocess execution; do not build shell command strings from user input.
- Bound message queues, segment retention, active sessions, and capture processes.
- Keep capture failure independent from chat monitoring and keep analysis failure independent from capture.
- Preserve existing Clippy generation, editing, publishing, and installer behavior.
- Do not claim support for a platform or capture mode until its focused tests and manual smoke test have passed.

## Validation policy

- Prefer focused pytest tests for backend behavior and focused dashboard tests/build checks for UI changes.
- Do not run the full CI matrix or Windows installer validation for documentation-only or isolated backend changes.
- Run Windows validation only when touching Windows-specific process handling, packaging/runtime manifests, installer/updater behavior, or when a real Windows smoke test is necessary to verify Streamlink/FFmpeg process behavior.
- Record exact commands and results below. A skipped validation must be identified as skipped, not passed.

## Progress log


### Live chat transport foundation — 2026-11-20

- Added provider token refresh before chat connections. Twitch refresh rotation is persisted immediately before token validation, and provider refresh/validation operations are serialized to prevent concurrent use of one-time Twitch refresh tokens. Twitch grants are validated on connection and at least hourly during long-running sessions. Google refresh preserves the existing refresh token when Google does not rotate it. A rejected YouTube access token triggers a forced refresh and one retry.
- Added Twitch IRC over WebSockets. The adapter authenticates using the connected account, joins the requested channel, handles PING/PONG, parses tagged PRIVMSG events, and normalizes provider message IDs, timestamps, sender identity, and text.
- Added YouTube live-chat polling through the YouTube Data API. It resolves the active live-chat ID from the video, follows page tokens and the provider's polling interval, and normalizes message identity, timestamp, author, and text. The adapter stops cleanly when the video has no active live chat and reports non-retryable provider errors.
- Added a bounded in-memory session manager (maximum two active sessions, 250 buffered messages per session), cancellation, reconnect backoff, and safe session snapshots. Added protected API operations to start, list, inspect, and stop sessions.
- Added the Community Highlights monitor UI. Users can paste a Twitch or YouTube stream URL, start chat monitoring, see connection state and recent messages, and stop a session. This milestone explicitly does not yet record video or create highlight candidates.
- Added the pinned `websockets` dependency for Twitch IRC. The existing `httpx` dependency handles YouTube API requests.
- Added focused tests for Twitch IRC message normalization, safe session snapshots, and provider token refresh.
- **Validation:** all new tests remain unexecuted in this environment. No live Twitch/YouTube chat session has been run. Provider connection checkboxes above reflect implementation, not a verified smoke test. The manual integration/smoke test remains outstanding.


### Google desktop OAuth foundation — 2026-11-20

- Added a Google installed-desktop authorization flow using the system browser, a dynamically allocated IPv4 loopback listener, random state, and PKCE S256. The callback binds only to `127.0.0.1`, accepts the root loopback redirect, validates state, exchanges the code server-side, and closes its listener on terminal outcomes.
- Requests only `https://www.googleapis.com/auth/youtube.readonly`. No Gmail, OpenID, profile, or Clippy-account scopes are requested. The access token is checked through Google's token-info endpoint for the expected application audience (when returned) and the required YouTube scope.
- Stores access/refresh tokens and expiry metadata through the Windows Credential Manager adapter. A prior refresh token is preserved if Google omits a replacement during reauthorization.
- Added start/status/cancel/disconnect API routes and enabled the shared **Sign in with Google** card. Google and Twitch now use independent flow state and credential targets.
- Added focused mocked tests for PKCE URL construction, loopback binding, scope selection, state validation, expiry, and cancellation.
- **Configuration requirement:** the public Google Desktop OAuth client ID must be supplied as `CLIPPY_GOOGLE_OAUTH_CLIENT_ID`. The public Twitch client ID uses `CLIPPY_TWITCH_CLIENT_ID`. Both are documented in `.env.example`; neither flow embeds or requires a client secret.
- **Validation:** tests have been authored but not executed in this environment. No live provider authorization or Windows Credential Manager smoke test has been performed. Packaged Windows builds still need the app-owned public client IDs configured before provider sign-in can be enabled for end users.


### Twitch OAuth foundation — 2026-11-20

- Added a Twitch Device Code Grant backend using the public-client flow. Clippy requests only `chat:read`, keeps the device code server-side, and returns Twitch's prefilled activation URL plus an opaque flow ID to the UI. The browser activation URL is host-validated before opening.
- Added polling lifecycle handling for pending approval, Twitch slow-down responses, denial, expiry, cancellation, and transient network failures. Successful grants are validated against Twitch's token-validation endpoint for the configured client ID and required scope before saving.
- Twitch access and refresh tokens, expiry, granted scopes, and account identity are saved through the Windows Credential Manager adapter. API responses do not return tokens or device codes.
- Added protected API operations for starting/polling/cancelling Twitch authorization and disconnecting Twitch. Connection metadata now reports whether Twitch sign-in is configured.
- Enabled the Twitch button in the shared Community Highlights connection component. It opens the browser, polls in the background, updates connection status, and supports cancellation/disconnection. Google sign-in remains intentionally disabled until its separate PKCE/loopback flow exists.
- Added focused mocked lifecycle tests for activation URL safety, device-code non-disclosure, pending state, client/scope validation, secure persistence, and cancellation.
- **Configuration requirement:** the public Twitch application client ID must be supplied as `CLIPPY_TWITCH_CLIENT_ID`. No client secret is used or embedded. The packaged app still needs an application-owned client ID configured in its runtime before the button becomes available.
- **Validation:** tests have been authored but not executed in this environment. No live Twitch authorization or Windows Credential Manager smoke test has been performed. This slice is not considered verified or complete until those checks run.

### Credential status integration — 2026-11-20

- Connected the safe connection-status API to the Windows Credential Manager adapter. It reports whether provider credentials are saved without ever serializing token fields.
- The API distinguishes unavailable secure storage from a provider with no saved credentials and from unreadable/corrupt credential data. It never falls back to browser storage or settings JSON.
- Updated the shared panel to explain that Windows Credential Manager is only available in the packaged Windows desktop environment.
- Expanded focused API tests to verify connected-state reporting and that access-token values and field names never appear in the response.
- Provider authorization remains disabled until the OAuth lifecycle and client application configuration are implemented.


### Windows credential-store foundation — 2026-11-20

- Confirmed the packaged desktop backend uses the same pinned `requirements.txt` whose SHA-256 is checked by the runtime manifest. Adding a Python dependency therefore flows through the existing payload/runtime integrity contract; no separate installer-side package list is required.
- Added a Windows-only credential-store adapter using Python Keyring's Windows Credential Manager backend. It fails closed on non-Windows platforms and if the selected keyring backend is not the Windows Vault backend; it does not fall back to plaintext or an OS-inappropriate backend.
- The adapter stores provider token bundles as JSON under separate provider identities, validates provider names and payload shape, and never includes credential values in raised error messages.
- Added focused tests using a fake Windows Vault backend for persistence, provider separation, malformed payload rejection, unsupported platforms, and fail-closed backend selection.
- The adapter is not yet called by OAuth endpoints. Provider sign-in remains disabled until Twitch/Google OAuth, token refresh/revocation, and connection lifecycle are integrated and tested.
- Validation not run: no local checkout or Python test runner is available in this session. No CI or Windows validation was started.


### Shared Community Highlights entry point — 2026-11-20

- Added Community Highlights to the shared navigation definition used by the desktop rail, mobile drawer, and mobile overflow navigation.
- Added the first Community Highlights landing view and a reusable provider-connection panel. The same React component is mounted in the feature tab and Settings & Integrations.
- Added the safe backend connection-status endpoint. It returns only provider state metadata and currently reports both providers as not connected and authorization unavailable. No fake connected state or nonfunctional active sign-in button is presented.
- Added the Google permission explanation requested by the user: Google authorization is separate from Clippy account sign-in, does not request Gmail access, and the YouTube read-only permission may cover other YouTube account data.
- Added a focused test for the connection-status response shape and absence of credential fields.
- This is a UI/API foundation only. OAuth flows, Windows Credential Manager persistence, provider connection lifecycle, and live chat adapters are not implemented yet.
- Validation not run: this session has GitHub repository access but no local checkout or test runner. No CI or Windows validation was started.


### 2026-11-20

- Inspected `AGENTS.md`, `CLIPPY_MASTER.md`, `CLIPPY_REPO_AUDIT.md`, the current `main` branch, backend entry points, and dependency manifest.
- Confirmed `main` HEAD was `61edcd5027e3f4e05c8019896e25af0e1cfa19f3`.
- Created `feature/community-highlights` from that `main` commit.
- Added this plan before implementation work.
- No application code or dependencies changed yet.


### Authentication UX and desktop integration inspection — 2026-11-20

- Confirmed the dashboard has one shared `navItems` definition in `dashboard/src/App.jsx` that drives the desktop rail, mobile drawer, and bottom tab bar. Community Highlights should be added there once, with its own `activeTab` view.
- Confirmed Settings & Integrations is rendered in the same `App.jsx` view tree. The same provider connection component can be mounted in both locations instead of duplicating authentication logic or state.
- Confirmed the native Windows shell is Tauri 2 and already exposes an `open_external_url` command. Its backend is a separately supervised Python process with a per-launch local API token. The OAuth callback and token persistence must respect this process boundary and must not expose provider tokens to the frontend.
- Confirmed the Tauri Rust crate currently has no credential-store dependency, and the Python requirements currently have no Windows credential-store package. Secure storage therefore needs an explicit implementation and packaging decision; it is not already provided by the current app.
- Twitch official documentation confirms public desktop clients should use Device Code Grant. The returned `verification_uri` can carry a prefilled device code, enabling one-click browser handoff without asking the user to copy/paste a code. Public-client refresh tokens are one-time-use and expire after 30 days of inactivity; refresh replacement must be persisted safely. [Twitch OAuth documentation](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/)
- Google official documentation supports the installed desktop flow using the system browser and loopback callback. The `youtube.readonly` scope is the available read-only YouTube Data API scope and is broader than one live chat; it does not grant Gmail access. [Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app) · [YouTube authorization](https://developers.google.com/youtube/data/guides/authentication) · [Google OAuth scopes](https://developers.google.com/identity/protocols/oauth2/scopes)
- No application source, dependency manifest, or runtime packaging file changed during this inspection. No tests/builds were run.

### Additional M1 findings — 2026-11-20

- The current backend is a single FastAPI application in `app.py` (8,482 lines at inspection); dashboard navigation is composed in `dashboard/src/App.jsx`.
- Existing `requirements.txt` includes `yt-dlp` and `httpx`, but no Streamlink or dedicated live-chat client. Do not add a capture dependency until M2.
- Existing `cloud/oauth.py` is the cloud account sign-in flow. It is not a YouTube Data API authorization integration and must not be reused as though it grants live-chat API access.
- Twitch's current IRC documentation requires a user access token with `chat:read`; Twitch recommends EventSub for chat integrations. This means a reliable URL-only experience needs a deliberate Twitch authorization flow or a supported shared-app authorization design.
- YouTube documents `liveChatMessages.streamList` with a Python/gRPC sample. The simpler polling endpoint is an alternative, but quota and API credential handling must be accounted for.
- The upstream `chat-downloader` package supports Twitch and YouTube without authentication, but its latest PyPI release is old (0.2.8, September 2023). A recently updated personal fork exists, but it explicitly offers no support. Neither is selected as a production dependency yet.
- No chat connection code or dependencies have been added. M1 implementation should start only after the credential/connection approach is chosen and its lifecycle can be tested.


### Implementation progress — 2026-11-20

- Added the `community_highlights` Python package with provider-neutral `ChatMessage` and `StreamReference` contracts.
- Added strict Twitch channel and YouTube video/live URL parsing. Channel/playlist URLs and unsupported hosts are rejected before any provider request.
- Added a deterministic trigger-engine foundation for phrase matches and message-volume thresholds, including unique-user counting, provider message-ID deduplication, per-rule cooldowns, and bounded in-memory history. This is an early M3 primitive, not connected to live providers yet.
- Added `tests/test_community_highlights.py` covering those pure-Python behaviors.
- No new runtime dependencies, FastAPI routes, dashboard UI, credentials, network clients, or video-capture code have been added.
- Validation status: tests have **not** been executed in this session because there is no local checkout or remote test-execution facility available through the GitHub connection. The test file was reviewed from GitHub after creation; local pytest verification remains required.
- Authentication UX decision: expose one shared Community Highlights Connections panel in both the new Community Highlights tab and Settings & Integrations. Both surfaces must render the same component and read/write the same backend connection state; connecting or disconnecting a provider in either location is immediately reflected in the other.
- Provider connections are separate from Clippy account sign-in. The UI labels should make the purpose explicit (for example, “Connect YouTube with Google” and “Connect Twitch”). Users may connect either provider independently; neither is mandatory to use the other.
- Desktop OAuth direction: Twitch supports a public-client Device Code Grant, which avoids shipping a Twitch client secret and returns refreshable user tokens. Google documents a Desktop OAuth client flow using the system browser, loopback callback, and PKCE; desktop client credentials are public-client material, not a server secret. Request only the narrow YouTube read scope required by the selected chat transport.
- Keep the existing cloud/oauth.py Google sign-in flow separate. It authenticates Clippy cloud accounts with openid email profile; it does not grant YouTube Data API access and must not be widened to mix product login with Community Highlights authorization.
- Persist provider refresh tokens locally using an OS-backed credential store where available; never put tokens in browser localStorage, the frontend settings JSON, URLs, or logs. Expose connection status and disconnect/revoke actions through a provider-neutral backend API. Confirm storage integration against the existing desktop packaging/runtime before choosing a dependency.
- Transport-specific scopes are finalized with the Twitch/YouTube adapters, using least privilege. Twitch chat access must use the scope required by the selected supported transport (IRC/EventSub); YouTube chat access uses the narrow read-only scope supported by the selected Live Chat API method.
- Provider adapters will not be represented as complete until authorization, refresh/reconnect, disconnect, cancellation, and mocked lifecycle tests exist.


### Authentication UX decision — 2026-11-20

- User confirmed the same provider-connection UI should appear on the Community Highlights tab and in Settings & Integrations.
- Implement one reusable React connection panel, not two independent implementations. Both placements call the same API and reflect the same persisted state.
- Use separate provider authorizations: Twitch account authorization for Twitch chat; Google authorization for YouTube Live Chat. These are not Clippy account sign-in.
- Twitch's official Device Code Grant supports public clients without a client secret and provides refresh tokens. This is a good fit for a locally installed Windows app.
- Google's official desktop OAuth guidance treats desktop clients as public clients, recommends PKCE, and supports a local loopback callback on desktop. Use the system browser for consent.
- Do not reuse or broaden the existing cloud/oauth.py login flow. It only requests OpenID Connect identity scopes for Clippy cloud login.
- Store refresh tokens outside browser storage and ordinary settings files, preferably in the OS credential vault. Add clear connection status and disconnect/revoke behavior.
- The UI can be implemented independently of the eventual chat transport, but exact scopes must match the selected transport and be kept least-privilege.
- Official references: Twitch OAuth grant types and public device flow (https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/); Google desktop OAuth and PKCE (https://developers.google.com/identity/protocols/oauth2/native-app); YouTube Data API authorization/scopes (https://developers.google.com/youtube/v3/guides/authentication).

### M2 — Streamlink/FFmpeg rolling capture foundation — 2026-11-20

- Added the pinned `streamlink==8.6.3` dependency and a provider-neutral resolver using Streamlink's Python API. Twitch and YouTube URLs are normalized through the existing parser before being passed to provider plugins; URL credentials, query strings, and fragments are not forwarded.
- Added `RollingCapture`, a worker-thread capture primitive that opens the resolved Streamlink reader and pipes bytes to FFmpeg over stdin. It uses an argument array with `shell=False`, stream-copy mode (`-c copy`), and the FFmpeg segment muxer to write MPEG-TS files. Only audio/video streams are mapped; there is no re-encoding in this foundation.
- Added runtime configuration validation for segment duration, retention duration, buffer-size budget, quality, output directory, and FFmpeg executable. The retention pass prunes expired/over-budget older segments while preserving the newest in-progress segment.
- Added a bounded FFmpeg CSV segment index containing each completed segment's media-timeline start/end PTS. The index window is sized from configured retention and segment duration; index reads reject malformed rows, path traversal, non-finite timestamps, and files already removed by retention. These values are media-timeline seconds, not wall-clock timestamps, so chat-to-video clock alignment remains a separate required step.
- Added segment pin/release operations so a future trigger coordinator can protect already-written pre-trigger segments from normal rolling-buffer pruning while it waits for post-trigger footage. Protected segments have their own byte-budget check, preventing the pin set from growing without bound.
- Shutdown closes FFmpeg stdin to allow muxer finalization, then uses bounded wait/terminate/kill fallbacks. Pipe writes loop until the full chunk is accepted, including partial writes from unbuffered OS pipes. Streamlink reader cleanup is performed in the worker's `finally` path. The worker honors the existing `FFMPEG_PATH` environment setting and fails before opening a provider stream if FFmpeg cannot be located. Blocking resolver/read/write/process operations are explicitly intended to run outside the FastAPI event loop.
- Added focused mocked tests for FFmpeg argument construction, config validation, age pruning, segment pinning, stream piping (including partial OS-pipe writes), safe CSV index parsing, stale/missing segment filtering, protected-storage budget enforcement, and missing-FFmpeg handling.
- Updated the Windows runtime builder's import smoke check to include Streamlink and explicitly import the Windows Credential Manager backend. The builder consumes the root pinned requirements file, so no separate dependency list or runtime manifest hash was changed here.
- **Still outstanding:** real FFmpeg/Streamlink integration, capture reconnect behavior, and Windows validation. Pre/post-trigger selection and candidate assembly are now implemented as a first pass, but their file-mtime clock alignment is approximate and must be measured against real streams. Segment duration is a target and may extend to the next keyframe when stream-copying.
- **Validation:** tests have been authored but not executed in this environment. No live provider stream or FFmpeg process was exercised. Packaged Windows runtime build/import check has not been run. The earlier resolver-only M2 note is superseded by this fuller rolling-capture progress entry.


### M2 capture-session lifecycle — 2026-11-20

- Added a supervised capture-session manager. Each capture receives a unique output directory and an immutable configuration snapshot, so changing settings for a later session cannot mutate an active capture.
- Limited concurrent rolling captures to two. Completed sessions are retained for status inspection and reclaimed when a new session needs capacity; a worker that cannot stop within the bounded shutdown window is reported as an error rather than silently marked stopped.
- Added start/list/status/stop API endpoints with request-bound validation for segment duration, retention, buffer budget, and Streamlink quality. Status responses contain only the provider and normalized stream identifier; they do not echo the pasted URL, query parameters, credentials, or resolved media URL.
- Added an FFmpeg-start callback so a session is reported as recording only after the process has actually launched, rather than when the Python worker thread merely starts.
- Added API shutdown cleanup for owned capture and chat workers. Capture shutdown waits off the FastAPI event loop and uses the capture worker's bounded Streamlink/FFmpeg cleanup path.
- Added a separate **Record rolling buffer** action and live capture-status list to the Community Highlights monitor. Chat monitoring and video capture can now be started/stopped independently for the M2 smoke test; this is deliberately not presented as automatic trigger capture.
- Added focused mocked tests for unique session directories, immutable settings snapshots, unsupported URLs, concurrency limits, stop behavior, sanitized status, and reclaiming a finished session slot.
- **Known limitation:** Streamlink reads may block until their configured 30-second timeout. Stop/shutdown therefore has a 45-second bounded join window. A real Windows Streamlink/FFmpeg run is required to validate that the reader and FFmpeg process actually unwind correctly under the packaged runtime.
- **Validation:** tests have been authored but not executed in this session. No real stream, FFmpeg process, or Windows runtime has been exercised.

### Windows validation gate requested by the user

At the end of the capture/trigger implementation slice, begin a focused Windows validation pass so the user can test the feature on their Windows machine. The focused runner is `desktop/validate-community-highlights.ps1`. This is an explicit milestone exit activity, not a full CI/installer matrix. It must include:

- Build/import-check the packaged Python runtime with Streamlink and Keyring included.
- Run focused Community Highlights pytest tests on Windows.
- Launch the desktop app and confirm both provider authorization panels render in the feature tab and Settings & Integrations.
- Verify Twitch and Google authorization handoff, secure credential persistence, chat start/stop, and sanitized session status.
- Configure segment length, buffer retention, storage cap, and Streamlink quality in the monitor; confirm new sessions snapshot these settings.
- With FFmpeg installed and a stream the user is authorized to capture, use **Record rolling buffer**, inspect segment growth/index updates, stop it, and confirm the process exits cleanly.
- Start chat monitoring and rolling capture for the same stream. Trigger with a configured phrase and with **Clip now**; verify pre-trigger protection, post-trigger wait, candidate assembly, download, and approve/reject behavior. Check timestamp drift and segment gaps against the visible stream timeline.
- Record exact PowerShell commands and observed results. Anything not actually run remains marked pending; do not call the milestone validated until the user has completed the live-stream portion.


### M2/M3 implementation slice — 2026-11-20

- Added `timeline.py` to select completed FFmpeg segments overlapping a requested pre/post wall-clock window. FFmpeg CSV PTS remains media-relative; the first implementation estimates each segment's wall interval from its file modification time minus its indexed media duration.
- Added strict coverage validation. A candidate is rejected instead of silently assembled when the pre-window is missing, the post-window has not completed, or a material segment gap is detected. Current tolerance is 2 seconds and must be checked against real Windows segment timing.
- Added `extraction.py` to assemble selected MPEG-TS segments through FFmpeg's concat demuxer with `-c copy`, no shell, bounded execution time, a temporary manifest, and cleanup. This creates a lossless TS candidate; it does not yet guarantee MP4 compatibility across every provider codec.
- Added a candidate worker lifecycle. At trigger time it pins available pre-trigger segments, waits for the configured post-trigger interval, refreshes the segment index, pins the selected window, validates coverage, assembles the candidate, and releases pins in a `finally` path. Candidate count is bounded.
- Connected both Twitch and YouTube normalized chat messages to a provider-neutral trigger coordinator. Default rules recognize `clip it` / `clip that` and a configurable message-volume threshold with unique-user count, time window, and cooldown. Capture is triggered only when a matching provider/stream rolling capture is actively recording.
- Trigger timestamps now use local chat receipt time, not provider event timestamps, because host file modification times are the current capture-clock reference.
- Added API operations for trigger settings, candidate listing/status/download, manual **Clip now**, and approve/reject decisions. The dashboard exposes trigger controls and candidate status/review actions.
- Added focused mocked tests for timeline selection, coverage rejection, lossless assembly arguments, trigger coordination, candidate extraction, and review decisions. Tests are authored but have not been run in this environment.
- **Known limitations:** file-mtime alignment is an estimate, not a frame-accurate clock mapping; segment boundaries can move to keyframes; trigger settings and candidate decisions are currently in memory and reset when the backend restarts; overlapping-trigger merging, inline preview, trim controls, automatic processing, AI analysis, and renderer handoff are not implemented.
- **Validation:** no local test runner is available here. No real FFmpeg/Streamlink process, live chat, Windows Credential Manager, or packaged Windows runtime has been exercised. Do not treat the capture/trigger path as validated until the requested Windows acceptance pass is complete.


### Candidate review and capture settings UI — 2026-11-20

- Exposed segment duration, rolling retention, maximum buffer size, and Streamlink quality in the monitor. These values are sent only when starting a new capture; existing sessions retain their original configuration snapshot.
- Kept the pasted stream URL in the input after starting chat or capture so the user can start both independent workers for the same stream without retyping it.
- Added authenticated candidate-file download and in-memory approve/reject decisions. Only candidates in the ready state can be reviewed; decisions are reflected in the candidate list.
- Added an explicit **Clip now** action for controlled testing without needing to post a trigger phrase in the live chat.
- Rejected candidate media is deleted immediately when the file is not locked by an active Windows download; a locked-file cleanup failure is surfaced on the candidate instead of failing the review decision. Pending and approved candidates are preserved while the in-memory review queue is below its cap.
- Improved trigger error handling so a storage-budget or capture conflict does not tear down the provider chat transport. Manual trigger conflicts return a clear API conflict response.
- **Not yet implemented:** inline playback preview, start/end trim controls, persistence of trigger settings and review decisions across backend restart, automatic processing mode, and renderer handoff.
- **Validation:** code and focused tests are committed to the feature branch, but no tests/builds have been executed in this environment. The Windows validation pass remains the next acceptance activity after the capture/trigger slice is reviewed.


### Windows runtime preflight update — 2026-11-20

- Extended the packaged Python runtime import smoke check to import `keyring.backends.Windows.WinVaultKeyring`, not merely the top-level Keyring package. This catches a missing Windows Vault backend or dependency before the runtime archive is produced.
- This is a validation guard only; the Windows runtime build has not been run in this session. The full focused Windows acceptance pass remains pending.


### Windows validation runner prepared — 2026-11-20

- Added `desktop/validate-community-highlights.ps1`. It runs only the focused Community Highlights pytest files, verifies the Streamlink/HTTP/FastAPI imports and the actual Windows Credential Manager backend import, and checks whether FFmpeg is available.
- The script has an optional `-BuildRuntime` switch for the packaged Python runtime build. It is intentionally opt-in because the CPU/CUDA runtime build downloads and stages the full Clippy ML dependency set and is substantially heavier than the focused tests.
- **Not run here:** this environment has no attached Windows checkout or PowerShell session. The script is committed for the user-run Windows acceptance pass; no test/build result is being claimed.


#### Start the Windows preflight

Run from the repository root in PowerShell after switching to the feature branch:

```powershell
git fetch origin
git switch feature/community-highlights
git pull
.\desktop\validate-community-highlights.ps1
```

If the project uses a virtual environment, pass its Python executable explicitly:

```powershell
.\desktop\validate-community-highlights.ps1 -Python .\.venv\Scripts\python.exe
```

The full packaged-runtime build is opt-in because it stages the complete Clippy ML runtime:

```powershell
.\desktop\validate-community-highlights.ps1 -BuildRuntime -Variant cuda
```

After the preflight passes, continue with the interactive sign-in, chat, rolling capture, trigger, candidate download, and review checks above. Report actual results; do not mark the live acceptance complete based on the mocked test suite alone.


### Initial GitHub Actions validation — 2026-11-20

- Opened draft PR [#28](https://github.com/helalxp/clippy/pull/28) to run the repository's existing CI and Windows desktop validation workflows. The feature branch was brought up to date with the single main-only documentation commit by a two-parent merge commit; the newer feature implementation plan was retained. The PR remains a draft and has not been merged.
- The first backend CI run completed with **1,375 passed, 30 skipped, and 3 failed**. The failures exposed (1) a duplicate protect call for a segment already pinned at trigger time, (2) a test assertion reading process options from the fake process instead of the mocked Popen invocation, and (3) malformed CSV test fixtures that wrote literal backslash-n sequences rather than separate rows.
- Fixed candidate assembly to pin only segments not already protected; corrected the Popen assertion and CSV fixture row separators. These are targeted fixes based on the recorded failure traces.
- Both the general frontend build and the Windows desktop dashboard build stopped at the same incompatible icon import: `CircleAlert` is not exported by the repository's pinned `lucide-react@^0.344.0`. Replaced it with the supported `AlertCircle` export in both Community Highlights components.
- The first Windows run successfully checked out the PR and provisioned Node, Python **3.12.10**, and Rust, but did not get past the dashboard build, so PowerShell contracts, backend syntax, Rust tests, and the NSIS installer were skipped. CPU/CUDA runtime-package jobs were still running when these fixes were prepared; no runtime-package pass is claimed.
- **Status:** fixes committed for a fresh PR validation run. No live Twitch/YouTube OAuth, chat, Streamlink capture, or real FFmpeg extraction has been exercised; those remain manual acceptance checks.


### PR #28 merged and Windows release-candidate validation — 2026-11-20

- Squash-merged [PR #28](https://github.com/helalxp/clippy/pull/28) into `main` at `08c94272c9fc0355d21e9491780d3228d3cf72dc`. GitHub reported the PR as clean and mergeable before merge.
- GitHub Actions completed successfully for the merged feature head: frontend build passed; backend suite reported **1,378 passed, 30 skipped, 0 failed**.
- Windows desktop validation passed all steps: synchronized version validation, dashboard build, PowerShell installer-script validation, packaged backend/renderer payload preparation, Pester runtime/payload contract tests, Python syntax, Rust check, Rust tests, complete NSIS installer build, and artifact retention.
- Both relocatable Python runtime package builds passed: **CPU and CUDA**. GitHub retained the installer, CPU runtime, and CUDA runtime artifacts from this validation run.
- Interactive Twitch/Google authorization, actual live chat ingestion, real Streamlink/FFmpeg capture, and user-machine playback remain acceptance tests for the pre-release candidate. Automated build success does not claim those live-provider paths are proven.
- The published stable release is `v0.3.1`; the most recent earlier RC is `v0.3.1-rc.4`. Prepared the next candidate as `0.3.2-rc.1` and synchronized the canonical version across `VERSION`, Tauri config, Rust package/lockfile, and dashboard package/lockfile. Independent `remotion`, `render-service`, and CLI package versions remain unchanged.
- The release workflow is tag-driven. Pushing tag `v0.3.2-rc.1` after this version-preparation commit will run release validation, build both Python runtimes, produce and sign the Windows NSIS installer, publish a GitHub prerelease, and attach the updater manifest/checksum/runtime assets. The RC should be installed manually for testing because the production updater endpoint resolves the latest stable release, not GitHub prereleases.

### Focused repair batch 1 — public OAuth configuration and Windows path compatibility — 2026-11-21

**Changes made**
- Added a generated `community-highlights-oauth.json` file to the staged desktop payload. It contains only `schemaVersion`, `twitchClientId`, and `googleOauthClientId`; it never contains a provider client secret.
- Validated the public IDs during payload preparation and wired the shared GitHub Actions Variables through both the Windows validation payload build and tagged release build. The tagged-release gate requires Google and format-validates Twitch only when it is supplied.
- Updated the Tauri supervisor to load the packaged public-ID file and explicitly set `CLIPPY_TWITCH_CLIENT_ID` and `CLIPPY_GOOGLE_OAUTH_CLIENT_ID` for the backend, rather than relying on ambient developer-machine environment variables. Missing config remains non-fatal for older development installations; release packaging is gated.
- Replaced the storage-path canonicalization used for Clippy data configuration with `dunce::canonicalize`, which emits the most compatible Windows path when that can be done safely.
- Added `storage-path.ps1` to normalize legacy extended drive and UNC paths before the runtime setup uses PowerShell path joins. It refuses unsupported device paths and paths that genuinely require extended-length handling rather than silently corrupting them.
- Updated the clean runtime smoke fixture to reproduce a legacy extended path and added focused Pester and Rust tests, including a Windows test that passes the exact Rust-persisted path to Windows PowerShell `Join-Path`.
- Narrowed Windows runtime-package change detection to actual Python runtime inputs. For payload, PowerShell, or Rust-only changes, the Windows validation job still runs, but the CPU/CUDA Python runtime packages and full runtime smoke download are skipped.

**Validation status:** the user confirmed that the focused batch-1 CI and Windows validation completed successfully. The CPU/CUDA Python runtime builds were skipped because no Python runtime inputs changed. The test OAuth Client IDs have not yet been configured in repository Actions Variables; the tagged-release workflow intentionally refuses to proceed until both public IDs are supplied. The subsequent batch-2 changes are validated separately.

**Explicitly not addressed in this batch:** API 404 diagnosis/route-level tests, candidate queue deletion/capacity, restart persistence, live capture reconnect and continuity, timeline drift validation, overlapping-trigger merge, M4 preview/trim/renderer handoff, and M5 hardening. These remain in the audit register above and are not being marked complete.


### OAuth testing identity and production transition

The Google Cloud OAuth project and Twitch Developer application currently configured for this feature are temporary **testing registrations**. The current names and support/contact information are not the final Clippy brand identity. The current provider registrations are being used for development and friend testing. The build does not distinguish test and production Client IDs: RC and stable tags read the same two generic Actions Variables. Any final production registration/branding transition is deferred to the later production-cleanup phase.

Before a public production release:
1. Establish the final Clippy brand identity and brand-owned support/contact email.
2. Create or configure separate production Google and Twitch application registrations, using the final app display name, support email, and required production callback/redirect settings for the actual implemented flows.
3. Complete Google's production audience, consent-screen branding, homepage/privacy-policy/terms, scope classification, and any applicable verification steps. The homepage and privacy policy must be hosted on a verified domain controlled by the brand, and the privacy policy must accurately disclose access, use, storage, and sharing of YouTube user data.
4. During the later production-cleanup phase, update the existing generic Actions Variables to the final public Client IDs after registrations and branding are ready. No separate *_TEST or *_PRODUCTION variable sets are used in the current workflow.
5. Keep client secrets out of the desktop app, packaged OAuth JSON, GitHub Actions Variables, frontend, and logs. The desktop OAuth clients are public clients; the current implementation uses PKCE for Google and Device Code Grant for Twitch.

Google's current policy documentation says External apps in Testing are limited to 100 test users and authorizations for scopes beyond the basic profile/email subset expire after seven days. A production app is subject to applicable branding and scope verification before general distribution. The exact verification path depends on the final audience and scope classification. References: Google Cloud Help, "Manage App Audience", "Manage OAuth App Branding", and "Verification requirements".


### Focused repair batch 2 — API 404 observability and candidate queue deletion — 2026-11-21

**Changes made**
- Added FastAPI HTTP-level tests against the real application object rather than testing only the connection-status helper. The tests exercise the exact connection endpoint, both providers' OAuth start/status/cancel routes, desktop-session-token enforcement, a known flow returning 404, and an unmatched route returning 404.
- Added a narrowly scoped backend warning for failed /api/community-highlights requests. It records HTTP method, matched route template (or an unmatched path with opaque IDs redacted), and response status. It deliberately excludes query strings, request bodies, headers, flow IDs, candidate IDs, and tokens.
- Added DELETE /api/community-highlights/candidates/{candidate_id} and a Delete action in the candidate list. Deletion is explicit and confirmed in the UI.
- Candidate deletion refuses to run while its extraction worker is active. It re-derives and checks the expected file path under the configured capture root before unlinking; if the file is locked or cannot be removed, candidate metadata remains so the user can retry.
- Removed automatic pruning of terminal candidate metadata. At the 20-item limit, users must explicitly delete an item; approved candidates are never silently discarded.

**Validation status:** the first backend CI run reported 1,390 passed, 30 skipped, and one failed test. The failure was in the new test fixture: connection_status had captured the original credential-store class in a default argument, so monkeypatching did not replace the Windows-only store. The function now resolves its default dependency at call time. That run also exposed an overly broad log-redaction threshold that hid the static 'community-highlights' path segment; the threshold is now limited to opaque IDs of 24+ characters and a regression test checks the route remains readable. Frontend CI passed. Final CI and one Windows validation on the final batch-2 commit are pending. CPU/CUDA Python runtime builds remain skipped because no Python runtime inputs changed.

No live provider authorization is performed by CI. The historical 404 cause remains unconfirmed until a failed request from the installed RC can be matched to the new safe backend diagnostic (or shown not to reach the backend at all).

**Scope boundary:** this batch does not implement restart persistence, capture reconnect, timeline calibration, trigger-window merging, AI analysis, preview/trim, renderer handoff, or M5 hardening.


### Focused repair batch 3 — OAuth token binding, provider disconnect, and browser handoff — 2026-11-21

**Changes made**
- Replaced the prior fail-open Google tokeninfo check with a shared strict validator used by both initial authorization and refresh. It requires a non-empty, syntactically valid `aud` field and requires `azp` (the authorized party that requested the token) to exactly match Clippy's configured Google OAuth Client ID. It deliberately does **not** require `aud == azp`: Google's token types documentation states that the audience can differ from the authorized party when OAuth clients belong to the same Cloud project.
- Added regression tests for a matching authorized party, missing/malformed authorized-party data, a wrong client, and the valid case where `aud` differs from `azp`. The refresh path is also tested for rejecting missing `azp`.
- Added a provider revocation adapter. Google sends the stored refresh token to Google's documented revocation endpoint. Twitch sends the stored access token and public Client ID to Twitch's documented access-token revocation endpoint. Tokens are sent in request bodies, not URLs; provider request details and token values are never logged.
- Disconnect now blocks new chat starts for that provider, stops its active chat sessions, attempts provider-side revocation, and removes local Windows Credential Manager credentials. If remote revocation cannot be confirmed, Clippy still disconnects locally and returns an explicit `not_confirmed` status with instructions to review provider account connections. Credential Manager deletion failure remains a 503 and does not claim local disconnection.
- The Twitch response is carefully worded as access-token revocation. Twitch's public documentation describes revoking an access token; this implementation does not claim more than the provider confirms. The user is directed to Twitch Settings > Connections when remote status cannot be confirmed.
- Google disconnect asks for confirmation before revocation. Google's documentation states that revocation removes all scopes granted to the Google Cloud project and invalidates tokens for every OAuth client registered in that project. The confirmation warns users that another Clippy or unrelated client sharing the project will also be affected; keep this project dedicated to Clippy.
- Reworked browser authorization popup handling. Clippy opens a blank window synchronously during the click gesture, sets `window.opener = null` before navigating to the provider, and uses the same safe helper for reopening. Added Node built-in tests and wired `npm test` into both Linux CI and Windows desktop validation.
- The backend now shares a provider-specific credential lifecycle lock across token refresh, OAuth credential persistence, and Disconnect. The lock is held while provider token exchanges and validation are in flight, so Disconnect waits for any newly issued token to be saved, cancels all remaining flows, revokes the latest saved grant where supported, and deletes local credentials before releasing the lock. This closes a race where a late refresh or OAuth callback could otherwise restore credentials after a successful local disconnect.
- Added async regression tests for refresh/disconnect ordering, both Twitch device-code and Google loopback callback/disconnect ordering, and late OAuth start requests attempting to register after a disconnect. Added defensive response-shape validation for provider JSON so malformed responses become safe authorization errors instead of backend 500s.
- Clarified the Google disconnect success message: a confirmed revocation invalidates grants/tokens for every OAuth client in the same Cloud project, not merely a possible subset.

**Validation status:** an initial backend run stopped at test collection because the disconnect helper's return annotation used `Any` without importing it. The failure was diagnosed from the CI traceback and the missing import was added. The latest CI run is queued/running against the subsequent commit, including the import correction, credential-race tests, malformed-response tests, dashboard unit tests, and frontend build. Windows desktop validation is also queued for the same branch. No live OAuth authorization or provider revocation is performed by CI. Test credentials are still not configured in the repository Actions Variables.

**Provider-specific scope and limitations**
- Google: the implementation revokes the stored refresh token; Google's documented revocation has project-wide effects for grants and clients within that Cloud project. Keep this OAuth project dedicated to Clippy and do not share it with unrelated products.
- Twitch: the documented revoke endpoint accepts an access token. A successful response confirms the access-token revocation request; it is not represented as proof that every provider-side grant has been removed. If Twitch cannot confirm revocation, users are directed to inspect the app in their Twitch Connections settings.
- Local disconnect is independent of provider availability: chat sessions are stopped and local credentials are deleted even when remote revocation cannot be confirmed. The UI explicitly communicates that distinction.

**Official documentation checked**
- Google Cloud token types and tokeninfo fields: https://docs.cloud.google.com/docs/authentication/token-types
- Google OAuth 2.0 for Desktop Apps, PKCE, and token revocation (including project-wide revocation behavior): https://developers.google.com/identity/protocols/oauth2/native-app
- Twitch token revocation: https://dev.twitch.tv/docs/authentication/revoke-tokens/
- Twitch access-token lifecycle and validation: https://dev.twitch.tv/docs/authentication/validate-tokens/
- Twitch Device Code Grant and public-client refresh behavior: https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/
- Browser popup and `noopener` return semantics: https://developer.mozilla.org/en-US/docs/Web/API/Window/open



### Shared OAuth Client ID configuration — 2026-11-21

The user chose to keep one shared OAuth configuration for development, friend testing, release candidates, and stable builds. Separate test/production variable sets are intentionally deferred to the later production-cleanup phase.

**Current configuration**
- GitHub Actions reads `CLIPPY_GOOGLE_OAUTH_CLIENT_ID` for both RC and stable tags. This value is required because the current live test path is Google sign-in and YouTube chat access.
- GitHub Actions reads `CLIPPY_TWITCH_CLIENT_ID` for both RC and stable tags, but it is optional for this phase. When blank, the payload contains an empty Twitch ID, the connection status reports Twitch authorization unavailable, and the Twitch sign-in button remains disabled. It does not block Google sign-in or packaging.
- A non-empty ID is still format-validated. Neither value is a client secret; no provider client secret is packaged.
- Windows PR validation and tagged releases use the same generic variable names. There are no `*_TEST` or `*_PRODUCTION` variables in the current workflow.
- Final brand ownership, production registration, consent-screen verification, and any eventual production-specific identity changes remain a separate cleanup milestone.

**Validation after this configuration change:** pending a fresh backend CI run, frontend CI run, and Windows desktop validation on the new commit. The preceding Windows validation passed its build and contract checks; CPU/CUDA runtime rebuild and first-run runtime smoke were skipped because no Python runtime inputs changed. The preceding frontend build passed; the backend CI job was still running at the time of this update. No live Google authorization, live YouTube chat, Twitch authorization, or stream capture has been completed by CI.

### Branch refresh and current baseline — 2026-11-24

- Created `fix/community-highlights-google-oauth` from current `main` at `38fe25cadcc7709ea69f9761a815b3f29ff25d1e` (the commit underlying stable `v0.3.2`).
- Reclassified `feature/community-highlights` as historical/superseded. It remains available for provenance; it is not the active development branch and must not be used as a merge base.
- PR #33 (Google browser handoff) and PR #34 (provider action gating) are merged into main. PR #37 promoted `v0.3.2` to stable.
- Latest mainline evidence: the backend test job and frontend build passed; Windows desktop validation passed. The release workflow built CPU and CUDA runtime packages. The separate Windows PR-validation job skipped runtime rebuilds because no Python runtime inputs changed.
- None of those results constitutes live Google OAuth, live chat, real Streamlink/FFmpeg capture, timestamp-drift, or user-machine media playback acceptance.

### Google post-consent callback repair — 2026-11-24

- The user added their Google account to the OAuth Test users list. The original Google 403 tester restriction no longer occurs; the remaining failure is after the consent screen, during callback completion.
- Updated `community_highlights/google_oauth.py` to validate the granted YouTube scope from the authorization-code token response instead of making a second `tokeninfo` request during initial sign-in. The code exchange remains bound to the configured public Client ID, the original redirect URI, the one-time PKCE verifier, and validated OAuth state. Refresh-time token validation remains unchanged.
- Added safe callback diagnostics identifying the failing phase and exception category, plus HTTP status/provider error identifier when available. Request URLs, response bodies, authorization codes, access/refresh tokens, and PKCE material are not logged. The generic user-facing error remains unchanged.
- Kept the final flow-state check and synchronous Credential Manager read/write under the Google flow lock so user cancellation cannot race between the final check and credential persistence.
- Added mocked tests for successful code exchange and secure save, no redundant tokeninfo request, explicit missing YouTube scope, standards-compliant omitted-scope handling when the requested scope is unchanged, and a credential-save failure whose logs must not contain test secrets.
- **Validation status:** tests are authored but have not been executed in this GitHub-only editing session. No actual Google consent flow or Windows Credential Manager write has been exercised on this branch. The next acceptance step is to run the focused tests, then reproduce the packaged-Windows sign-in and inspect only the new safe phase diagnostic if it still fails.


