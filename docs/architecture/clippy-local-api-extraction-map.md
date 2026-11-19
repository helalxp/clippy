# Clippy Local API Extraction Map

> **Status:** Phase 1 source map for the Phase 2 local-backend extraction.  
> **Inspected baseline:** `61edcd5027e3f4e05c8019896e25af0e1cfa19f3` (`v0.3.1`).  
> **Primary source:** `app.py`, with the frontend callers and service modules cross-checked against the same baseline.  
> **Purpose:** identify the real local-v1 API surface, hosted cross-cutting seams, and deferred endpoints before code is moved or deleted.

## 1. Classification legend

- **KEEP / LOCAL V1:** part of the local desktop workflow. Preserve behavior, request/response fields, file ownership, security checks and errors while extracting.
- **KEEP / CONTRACT FIRST:** likely local-v1 or a platform contract, but the current ownership/persistence behavior needs a test or product decision before extraction.
- **DEFER / ISOLATE:** keep the implementation and handoff evidence out of the v1 execution path. Do not delete it as part of a local API extraction.
- **REMOVE FROM DESKTOP:** inherited website or remote-only surface that should not be in the Clippy v1 native payload. Remove only after confirming no local-v1 caller uses it.
- **HOSTED ONLY:** SaaS behavior to disconnect from the desktop backend. The `cloud/` source tree has a separate commercial licence and must not be redistributed as part of Clippy v1 without resolving that licence.

## 2. Local v1 API surface to preserve

| API family | Routes observed in `app.py` | Current implementation/owner | Treatment |
|---|---|---|---|
| Health | `GET /health`, `GET /health/ready` | FastAPI and desktop runtime supervisor | **KEEP / LOCAL V1.** Keep these available to the Rust health checker. They are deliberately exempt from the per-launch token middleware. |
| Runtime and first-run config | `GET /api/config`, `GET /api/first-run/status`, `POST /api/first-run/complete` | `app.py`, `clippy_local_models.py`, `llm_backend.py` | **KEEP / CONTRACT FIRST.** Replace hosted fields such as billing/auth state with an explicit local runtime/settings contract. Keep model and local-LLM behavior. |
| Whisper model manager | `GET /api/local-models/whisper`, `POST /api/local-models/whisper/select`, `POST /api/local-models/whisper/verify`, `POST /api/local-models/whisper/download` | `clippy_local_models.py` and local settings/model paths | **KEEP / LOCAL V1.** Preserve catalog selection, custom model path, verification, asynchronous download state, and the distinction between runtime dependencies and model weights. |
| Reference templates | `GET /api/reference-templates`, `GET /api/reference-templates/{template_id}`, `POST /api/reference-templates`, `PATCH /api/reference-templates/{template_id}` | `reference_templates.py`, local data root, React `ReferenceTemplateLibrary` | **KEEP / LOCAL V1.** The owner explicitly chose to retain this feature. The files and data must remain in the configured user data directory. |
| Main generation | `POST /api/process` | `app.py` request validation, queue/job lifecycle and child-process launch; `main.py` processing engine | **KEEP / LOCAL V1.** Preserve upload and URL ingestion, rights attestation, custom watermark upload, output format/layout, clip bounds, caption/hook specifications, quality gate, job creation and response fields. Do not let optional feature handovers become hidden dependencies of the standard flow. |
| Upload slots | `POST /api/uploads`, `PUT /api/uploads/{upload_id}`, `DELETE /api/uploads/{upload_id}` | In-memory pending-upload records and local file staging | **KEEP / CONTRACT FIRST.** The MCP agent uses these routes. The standard dashboard sends multipart input directly to `/api/process`. Because MCP is deferred, preserve this API contract in the handoff and decide whether v1 still needs the public route before keeping it live. |
| Job state and source media | `GET /api/status/{job_id}`, `GET /api/source-url/{job_id}`, `GET /api/source/{job_id}` | `app.py`, `media_auth.py`, local output workspace | **KEEP / LOCAL V1.** Preserve status, logs, queue/progress, restart recovery, source preview, path validation and signed media capabilities. |
| Local Library | `GET /api/library/storage`, `POST /api/library/storage/prepare-move`, `GET/PUT /api/library/settings`, `GET /api/library/projects`, project/clip detail, thumbnail, captions, video, export and delete routes | `local_library.py`, Tauri `data_storage.rs`, `installation.rs`, `lib.rs`; React `LocalLibraryTab` | **KEEP / LOCAL V1.** This is the permanent local Library, separate from temporary `OUTPUT_DIR`. Preserve verified data moves, project/clip archive, optional source retention, captions, downloads, deletion and path reveal. |
| Desktop maintenance handshake | `POST /api/desktop/update/prepare`, `POST /api/desktop/update/cancel` | FastAPI maintenance-quiescence middleware plus Rust supervisor/updater | **KEEP / LOCAL V1.** This is part of the Tauri updater/runtime protocol, not a hosted feature. Preserve request draining and rollback/health semantics. |
| Clip editing | `POST /api/edit`, `POST /api/clip/rerender`, transcript/EDL/scenes reads, `POST /api/clip/background`, `POST /api/clip/watermark`, `POST /api/clip/reframe` | Editor/recut/reframe/watermark modules, Remotion and FFmpeg | **KEEP / LOCAL V1.** Preserve the full edit chain, ownership of the canonical clip file, edit serialization and render behavior. The helper named `require_managed_entitlement` is a no-op when billing is off; do not let this old name obscure the actual local API contract. |
| Captions, hooks, effects, translation | `POST /api/effects/generate`, `POST /api/subtitle`, `POST /api/subtitle/remove`, `POST /api/hook`, `GET /api/translate/languages`, `POST /api/translate` | FFmpeg/subtitle/hook/translation modules | **KEEP / LOCAL V1**, subject to feature acceptance tests. They are editing operations, not billing services. Preserve exact edit semantics and output URLs. |
| Render API | `POST /api/render`, `GET /api/render/{render_id}` | FastAPI proxy plus `render-service` and Remotion | **KEEP / LOCAL V1.** Preserve backend-to-renderer token, path mapping, status semantics, progress/error behavior and shared output-root contract. Renderer restart status recovery is a known separate reliability question. |
| Download/export | `GET /api/jobs/{job_id}/download-all`, local Library project ZIP/video routes | FastAPI plus native streamed Tauri file writes | **KEEP / LOCAL V1.** Preserve complete-transfer checks, safe filenames, streamed native writes and cancellation of partial output. |

### 2.1 Local Library is not cloud History

The frontend explicitly separates the cloud History view from `LocalLibraryTab`. In local mode, `HistoryTab` immediately renders `LocalLibraryTab` and does not call the hosted `/api/history` or `/api/projects` routes.

The local Library uses `/api/library/projects`, `/api/library/projects/{project_id}`, per-clip caption/video/thumbnail routes, export and delete routes. It persists project metadata and copied clip deliverables under `CLIPPY_LIBRARY_DIR`.

The older `POST /api/projects/{job_id}/restore` route is explicitly cloud-only: it returns 404 when billing is disabled and restores files from cloud storage after checking ownership in the cloud database. It is **not** the local Library restore/reopen implementation. The current `LocalLibrary` class and `LocalLibraryTab` do not expose an equivalent reopen-to-generator method. Treat that as a separate product/architecture gap to decide and design; do not silently wire the old R2 route into local mode.

## 3. Hosted SaaS seams mixed into `app.py`

The following concerns must be extracted before `cloud/` can be disconnected safely.

| Seam | Current source symbols/behavior | Phase 2 treatment |
|---|---|---|
| Billing flag and conditional imports | `BILLING_ENABLED`; conditional `import cloud`, `cloud.auth`, managed keys, metering, config and alerts | Replace with an explicit desktop/local runtime mode. The native supervisor currently does not set `BILLING_ENABLED=0` or clear hosted service variables. It inherits the parent environment. Make desktop mode fail closed and test this. |
| Identity and owner scoping | `_user_from_request`, `_owner_id`, `_assert_job_owner`, `resolve_gemini`, `resolve_upload_post`, `resolve_post_profile` | Keep the local per-launch API-token boundary. Split it from the hosted multi-tenant identity model. Keep the local Gemini BYOK resolution path; hosted managed-key resolution and cloud user ownership are not local desktop identity. |
| Entitlement and usage metering | `payment_required`, `gemini_missing_error`, `reserve_process_minutes`, `reserve_managed_action`, `require_managed_entitlement`, reservation settlement helpers | Remove hosted quota/plan/Stripe semantics from local-v1 request handling. Convert the current no-op self-host behavior into an explicit local service interface so endpoints no longer depend on cloud-named helpers. |
| Cloud-only configuration constants | `partial_offer`, `plan_partial_minutes`, `free_overflow` import `cloud.config` lazily; numerous hosted action paths use `_cloud_config` plan/minute constants | Move needed local values/defaults into a local config contract only if the local flow uses them. Current `reserve_process_minutes` returns before metering in local mode; do not copy all pricing/plan constants into Clippy. Add import tests proving local desktop startup does not need the cloud package. |
| R2 history/archive | `_archive_managed_job`, `_archive_clip_edit_bg`, `_restore_job_files`, `_restore_for_public_path`, cloud history/project restore | Disconnect R2 archive and restore from local jobs. Local Library archiving in `local_library.py` is the local durable path. Preserve the distinction between temporary job workspace and local Library. |
| Hosted job lifecycle | `_autopilot_job_finished`, `_notify_clips_ready`, `_notify_clip_activity`, `_record_job_alert`, `_track_job_outcome`, `_track_proxy_usage`, cloud lifecycle startup and proxy watch loop | Separate post-job local bookkeeping from hosted autopublish, lifecycle email, cloud analytics/revenue, admin alerting and proxy-cost accounting. Keep user webhooks only if the product owner confirms them as a v1 local integration. |
| Hosted application startup | `lifespan()` conditionally calls `cloud.setup_async`, account/video callbacks, Autopilot, lifecycle and proxy-watch loops; `cloud.setup_sync(app)` conditionally attaches hosted routes | Keep local job recovery, queue and runtime readiness; remove cloud startup hooks only after each local callback is accounted for. |
| Cloud Library restrictions | A number of `/api/library/*` routes return 404 when `BILLING_ENABLED` is true, while desktop storage-move/update routes reject billing mode | Once the desktop mode is forced local-only, make the Library/update API contract explicit and remove contradictory hosted-mode branches. Do not delete those guards without confirming the local API is never shared with a multi-tenant server. |
| Source URL and proxy accounting | `cloud.proxy_ledger` used for paid proxy budgets, usage accounting, bot-check/proxy events and billing alerts | Keep URL validation, yt-dlp behavior and the local download path. Remove managed proxy ledger dependencies from local jobs. Do not remove URL validation or the existing download safety controls with the ledger. |

## 4. Deferred features and their API surfaces

The product owner selected these for later/future work. The feature code must be isolated from the v1 navigation/execution path and documented under `docs/roadmap/deferred/`; UI entries that remain visible must say **Under investigation**.

### 4.1 Social publishing and scheduling — DEFERRED

Routes in `app.py`:
- `POST /api/social/post`
- `GET /api/social/user`
- `GET /api/social/analytics`
- `GET /api/social/analytics/posts`
- `GET /api/social/analytics/impressions`
- `GET /api/social/scheduled`
- `DELETE /api/social/scheduled/{job_id}`

Dependencies include Upload-Post API keys, connected profile selection, network permissions, scheduling APIs, `social_metrics.py`, and cloud profile-token/analytics logic. `dashboard/src/App.jsx` stores the Upload-Post key and profile selection and exposes connect/calendar/results actions.

Keep social publishing separate from the clip-generation/editing API. Do not remove user watermark features because social publishing is deferred. Do not revoke or delete any existing account credentials as part of removing the UI.

### 4.2 Thumbnail Studio — DEFERRED

Routes in `app.py`:
- `POST /api/thumbnail/upload`
- `POST /api/thumbnail/analyze`
- `POST /api/thumbnail/titles`
- `POST /api/thumbnail/generate`
- `GET /api/thumbnail/frames/{session_id}`
- `POST /api/thumbnail/describe`
- `POST /api/thumbnail/publish`
- `GET /api/thumbnail/publish/status/{publish_id}`

This feature has its own upload/transcription session state, generated frames and title conversation, Gemini calls, thumbnail image generation, and optional social publishing. It currently also calls hosted entitlement/metering helpers and uses in-memory session ownership records. Keep its storage, external-provider and restart limitations in the handoff; do not let it dictate the core generation API.

### 4.3 AI UGC / SaaS Shorts — DEFERRED

Routes in `app.py`:
- `POST /api/saasshorts/analyze`
- `POST /api/saasshorts/actor-upload`
- `POST /api/saasshorts/actor-options`
- `GET /api/saasshorts/gallery`
- `POST /api/saasshorts/post`
- `GET /api/saasshorts/actor-gallery`
- `POST /api/saasshorts/generate`
- `GET /api/saasshorts/status/{job_id}`
- `GET /api/saasshorts/voices`
- Public HTML routes `/gallery` and `/video/{video_id}`

Dependencies include fal.ai, ElevenLabs, actor images, public AWS S3 gallery uploads/listing, optional Upload-Post publishing and its own job state. The current `s3_uploader.py` is imported at FastAPI module import time and provides both this gallery behavior and a separate local-mode job-artifact upload path (see Section 5).

### 4.4 MCP / AI-agent integration — FUTURE

`app.py` imports `mcp_server.py` and mounts its router at `/mcp`. The MCP server forwards tool calls back into the app's own FastAPI routes. In cloud mode it requires hosted API-key/OAuth identity; in self-host mode its code preserves BYOK behavior. The MCP tool set includes process, upload, status, list clips, quota, subtitles, recut and social publishing.

The MCP server is not a separate processing engine. It is an alternate API caller and depends on the underlying request contracts. For v1, preserve this architecture knowledge and its security implications, but take the active `/mcp` router/UI out of the user-facing product until the future integration is reapproved. Only then decide whether `/api/uploads`, webhook support, and agent-specific fields remain in the core local API.

## 5. Confirmed high-priority findings for Phase 2

### 5.1 Unexpected S3 upload path in local mode

This is a confirmed data-boundary issue in the current source:

1. In the successful-job branch of `run_job`, `app.py` calls `upload_job_artifacts(output_dir, job_id)` whenever `BILLING_ENABLED` is false.
2. `s3_uploader.upload_job_artifacts` iterates over the job directory and attempts to upload every top-level MP4 and JSON file.
3. `upload_file_to_s3` reads `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION` from the process environment. The artifact uploader uses `AWS_S3_BUCKET` or defaults to `my-clips-bucket`.
4. The call is asynchronous/fire-and-forget and has no explicit user opt-in or UI control.
5. The Tauri supervisor starts the backend with an inherited environment. Its current environment builder does not remove AWS credential variables or explicitly force `BILLING_ENABLED=0`.

On machines without AWS credentials, the helper usually returns without uploading. That does not make the path safe: if credentials are present in the inherited environment (or a local `.env` file is loaded), generated clips and JSON metadata are sent to S3. This contradicts the expected local-first delivery boundary.

**Required Phase 2 fix:** remove this implicit upload from the Clippy desktop path, remove the unnecessary `s3_uploader` import from the core API, and make the desktop environment explicitly reject/clear AWS/cloud configuration. Do not replace this with another silent remote backup. Local Library persistence remains handled by `local_library.py`.

Before deleting `s3_uploader.py` or the `boto3` dependency, first isolate its deferred UGC gallery functions and prove there is no remaining local-v1 caller. A future publishing/UGC feature may choose its own explicit object storage, consent and credentials.

### 5.2 Desktop mode does not explicitly force local-only configuration

The Rust supervisor sets `CLIPPY_DESKTOP_MODE=1`, but it does not currently set `BILLING_ENABLED=0` or clear the hosted-service environment. The backend process inherits ambient environment values. A machine with stale `BILLING_ENABLED=true` can cause `app.py` to try importing the hosted `cloud/` package even though the desktop payload does not include that package.

**Required Phase 2 fix:** the Tauri backend launch contract must explicitly run local-only, remove hosted credential/config variables, and have a startup assertion that desktop mode cannot initialize billing, hosted auth, cloud storage or managed keys. Test with hostile/stale environment variables set before launching the backend.

### 5.3 Per-launch API security must remain independent of hosted accounts

The current desktop token middleware checks `X-Clippy-Token` on all routes except `OPTIONS`, `/health`, and `/health/ready`. It permits a query-token fallback only for read-only media paths that cannot attach headers. The Tauri supervisor provides the per-launch token; it is not a cloud JWT and must not be replaced by one.

The legacy `_assert_job_owner` helper is a no-op when billing is off. That is acceptable only because the desktop backend is protected by its per-launch API token and is bound to loopback. Preserve both conditions. Do not expose the backend on a LAN or public interface while using the local no-owner mode.

### 5.4 Local Library reopen is not the hosted restore endpoint

The current cloud restore route `POST /api/projects/{job_id}/restore` immediately returns 404 when billing is off and otherwise reads the cloud database/R2. The local Library route set does not presently expose an equivalent reopen-to-generator endpoint. `LocalLibraryTab` opens project detail for browsing, caption edits and downloads but does not call the cloud restore route.

This is a gap to decide separately. Do not preserve the cloud restore route merely because its URL sounds local, and do not claim local project rehydration is implemented until an end-to-end source/workspace reconstruction contract is designed and tested.

## 6. Route families that do not belong in the desktop payload

### 6.1 Public SEO/website tools — REMOVE FROM DESKTOP

`free_tools.py` is mounted by `app.py` and provides `GET /api/tools/youtube-transcript` and `POST /api/tools/youtube-metadata`. Its module documentation describes public website/SEO pages. Those endpoints belong with the separate website (or may be retired) rather than the Clippy desktop application.

The public `/gallery` and `/video/{video_id}` HTML pages are also website/UGC-gallery surfaces, not local Library pages. They are listed with SaaS Shorts in Section 4.3.

### 6.2 Analytics/telemetry — REMOVE FROM V1

The dashboard imports `track` throughout its workflow and the old OpenPanel bootstrap remains in `dashboard/index.html`. The explicit product decision is **no analytics or telemetry in v1**. Merely leaving it disabled by environment variable is not the agreed v1 treatment. Phase 7 must remove the runtime script/config and event emitters without deleting local diagnostics or user-visible job logs.

## 7. Recommended extraction order for Phase 2

1. Add characterization tests around local desktop startup, per-launch API auth, generation, Library persistence, editing, export, media URLs and renderer requests.
2. Make Tauri desktop startup explicitly local-only; test hostile inherited cloud/AWS environment variables.
3. Remove the implicit AWS S3 job-artifact upload from local mode and prove a successful desktop job makes no remote storage request.
4. Extract local settings/model services, local Gemini key resolution and local job/Library persistence behind local modules/interfaces.
5. Extract the job queue/lifecycle and editing routes with explicit local dependencies. Keep cloud callbacks in a clearly separate optional adapter until Phase 3.
6. Separate R2 history/archive/restore and hosted ownership/meters from the local job/Library path.
7. Isolate deferred social, Thumbnail Studio, SaaS Shorts, MCP and public website routes based on their handoff documents.
8. Only after the desktop payload has no import/call path to hosted services, remove `cloud/` and cloud-only dependencies in Phase 3.

Do not split `app.py` into arbitrary folders as a first step. The extraction should follow these actual responsibilities and preserve the endpoint contracts.

## 8. Phase 2 test requirements derived from this map

- Tauri startup remains loopback-only, provides a fresh token and can only start the local backend/renderer.
- Desktop launch with `BILLING_ENABLED=true`, stale Stripe/database/R2/AWS variables and a stray system Python/Node environment still starts the intended local configuration without importing cloud code or using those credentials.
- A normal local job accepts an upload and a supported URL, validates rights acknowledgement and source URL, creates/updates a local Library project, serves valid media, and completes its rendering path.
- A completed local job writes to the local Library and makes **no** AWS S3/R2/Upload-Post/OpenPanel/Stripe request.
- Library move/upgrade/repair tests preserve settings, projects, media, model weights and reference templates.
- Clip background/watermark/reframe/subtitle/hook editing preserves output paths and render contracts.
- Renderer authorization continues to reject missing/wrong tokens from desktop-origin requests.
- Deferred social/thumbnail/UGC/MCP routes cannot accidentally appear as functioning local-v1 UI.
- Website SEO routes and analytics code are absent from the packaged desktop product after their designated removal phase.

**Phase 1 result:** the local API surface and the main SaaS/deferred seams are now mapped from the source. This document is a planning and test-contract artifact; it does not change route behavior or remove any subsystem.
