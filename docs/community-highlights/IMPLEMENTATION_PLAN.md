# Community Highlights Implementation Plan

**Status:** In progress  
**Feature branch:** `feature/community-highlights`  
**Base:** `main` at `61edcd5027e3f4e05c8019896e25af0e1cfa19f3`  
**Product:** Clippy  
**Last updated:** 2026-11-20

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
- Updated the Windows runtime builder's import smoke check to include Streamlink. The builder consumes the root pinned requirements file, so no separate dependency list or runtime manifest hash was changed here.
- **Not implemented yet:** real FFmpeg/Streamlink integration, wall-clock alignment between chat receipt timestamps and FFmpeg media PTS, pre/post-trigger window selection and assembly, capture reconnect behavior, and coordination with live-chat triggers. Capture API/session lifecycle is now implemented, but it has only mocked-test coverage so far. Segment duration is a target and may extend to the next keyframe when stream-copying.
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

At the end of M2, begin a focused Windows validation pass so the user can test the feature on their Windows machine. This is an explicit milestone exit activity, not a full CI/installer matrix. It must include:

- Build/import-check the packaged Python runtime with Streamlink and Keyring included.
- Run focused Community Highlights pytest tests on Windows.
- Launch the desktop app and confirm both provider authorization panels render in the feature tab and Settings & Integrations.
- Verify Twitch and Google authorization handoff, secure credential persistence, chat start/stop, and sanitized session status.
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
