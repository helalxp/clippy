# Clippy Download Lifecycle Investigation

**Status:** Source-code audit completed; packaged-runtime reproduction still pending  
**Branch:** `feature/library-history`  
**Base branch:** `windows-installer-release`  
**Audited source:** branch snapshot created from `windows-installer-release` at `19dc53a434771364c6fd3b8fc4d9c5af4b80d3d9`

> This document separates verified source-code behavior from runtime hypotheses. The packaged Windows app has not yet been launched in this audit, so UI/runtime defects are not described as reproduced.

## 1. Executive findings

1. **The single-clip download and Download All are two different implementations.**
2. **Single-clip desktop downloads have a native Tauri file-writing path** and are saved to `%USERPROFILE%\\Downloads\\Clippy\\`.
3. **Download All does not use that native Tauri path.** It fetches a ZIP as a browser Blob and triggers an HTML anchor download. In the Windows WebView2 app, the destination is not controlled by Clippy's native download commands.
4. The Download All object URL is revoked immediately after the anchor click, unlike the single-clip browser path which waits 60 seconds. This is a credible race risk, especially in an embedded webview, but still needs runtime reproduction.
5. Download All displays only a transient `zipping…` state. It has no percentage/progress, final path, reveal-folder action, or success confirmation. The frontend cannot tell the user where the ZIP landed.
6. **The existing Library & History screen is cloud/R2-backed, not a local Windows Library.** Its API routes are mounted only when `BILLING_ENABLED` is true. The desktop supervisor does not set that flag; the backend defaults it to false. In the normal local desktop mode, `/api/history` and `/api/projects` therefore are not mounted.
7. Local generated files live under the managed Clippy installation data directory, not the repository checkout. The Windows desktop supervisor sets `OUTPUT_DIR` to `%LOCALAPPDATA%\\Clippy\\data\\output` (or `%CLIPPY_HOME%\\data\\output` when overridden) and `UPLOAD_DIR` to the sibling `uploads` directory.
8. Local job output is temporary: self-host/local mode defaults `JOB_RETENTION_SECONDS` to 86,400 seconds (24 hours), and a five-minute cleanup loop deletes expired job directories. This is incompatible with the requested permanent local Library unless archived content is moved/copied outside the temporary job tree.
9. The cloud Library already groups clips by job and can restore archived editing state, but it stores clips/metadata in R2 and does not retain the original source video. The restore flow explicitly marks `noSource`; it can restore clip-level editing state, not a full source-based session.

## 2. Existing UI and Library/History behavior

### Navigation

- `dashboard/src/App.jsx` defines a visible navigation item: `Library & History`, tab id `history`.
- The active tab renders `<HistoryTab onReopenProject={restoreProject} />`.
- The old `Gallery` import is commented out; the current screen is `HistoryTab`.

### Current HistoryTab

File: `dashboard/src/components/HistoryTab.jsx`

- On mount, it requests `GET /api/history` and `GET /api/projects`.
- Videos are grouped by `job_id`; the project is effectively a generation job.
- The screen shows a project title/date/clip count, individual video previews, and direct download links.
- A project gets a `reopen project` action when the projects API returns a matching project.
- Reopening calls the parent callback, which posts to `/api/projects/{job_id}/restore`.
- It does not currently provide local project rename/delete, local storage browsing, source-retention controls, or a self-hosted local-library API.

### Cloud-only limitation

- `cloud/__init__.py::setup_sync` mounts `cloud.videos.router`.
- `app.py` calls `cloud.setup_sync(app)` only inside `if BILLING_ENABLED:`.
- `BILLING_ENABLED` defaults to false when the environment variable is absent.
- `desktop/src-tauri/src/supervisor.rs` supplies `OUTPUT_DIR`, `UPLOAD_DIR`, model paths and other runtime variables, but does not set `BILLING_ENABLED`.
- Therefore the existing `/api/history` and `/api/projects` routes belong to managed cloud mode. The existing HistoryTab is not a functioning persistent local Library for the standard self-hosted Windows desktop mode.

### Existing cloud project persistence

File: `cloud/videos.py`

- `archive_job` uploads generated clip files and the job metadata JSON to Cloudflare R2.
- It also archives the clean canonical clip when the delivered version is a derived subtitle/recut version, plus intermediate twins needed for later clip editing.
- It upserts `UserVideo` rows and a `Project` row.
- The Project title is currently taken from the first archived clip title (`_clip_title`), not explicitly from the original YouTube source title.
- `GET /api/projects` lists the user's project rows.
- `GET /api/history` returns signed, time-limited R2 view/download URLs.
- `PUT /api/projects/{job_id}/state` stores browser-only Remotion layers and current server filenames.
- `POST /api/projects/{job_id}/restore` rehydrates archived files from R2 into the server's temporary output directory.
- In `App.jsx::restoreProject`, the restored project sets `noSource = true`, with a code comment explaining that the source video was never persisted. Thus this is clip-level restoration, not full original-source reconstruction.

## 3. Local Windows storage locations

### Runtime root

File: `desktop/src-tauri/src/supervisor.rs`, `RuntimePaths::discover`

- Root: `%LOCALAPPDATA%\\Clippy`, unless `CLIPPY_HOME` overrides it.
- Application payload: `<root>\\app\\current`.
- Runtime: `<root>\\runtime`.
- Render output: `<root>\\data\\output`.
- Uploaded source files: `<root>\\data\\uploads`.
- Models: `<root>\\data\\models`.
- Settings: `<root>\\settings.json`.
- Logs: `<root>\\logs`.

Default concrete paths:
- Generated job output: `%LOCALAPPDATA%\\Clippy\\data\\output\\<job_uuid>\\`
- Uploaded input: `%LOCALAPPDATA%\\Clippy\\data\\uploads\\<job_uuid>_<original_filename>`

### Per-job output

File: `app.py`, process submission and job worker.

- Each job gets `OUTPUT_DIR/<job_uuid>`.
- `main.py` writes a source-title-based metadata file (`*_metadata.json`) and clips named approximately `<source_title>_clip_<n>.mp4`.
- Derived versions are written beside the canonical clip with prefixes such as `subtitled_<timestamp>_`, `hooked_<timestamp>_`, and `wm_`.
- URL jobs are submitted with `--keep-original`, so their downloaded source is initially retained inside the job output directory.
- Uploaded files are stored in the separate uploads directory. They are not automatically copied into a permanent project archive.

### Temporary retention

File: `app.py`

- `JOB_RETENTION_SECONDS` defaults to 86,400 seconds (24 hours) when billing is disabled.
- `cleanup_jobs()` wakes every 300 seconds and calls `_sweep_expired_job_dirs`.
- Expired job directories are recursively deleted unless the job is still active.
- Uploaded source files are also swept after the same retention window.
- Output-size caps can remove old job directories earlier if configured and exceeded.
- The self-host completion path calls `upload_job_artifacts` as a background backup, but this is not the local Library API and does not make the existing HistoryTab available in desktop mode.

**Implication:** The app's working output folder is not a permanent archive. A local Library must move/copy validated deliverables and metadata into a separate permanent root before the temporary job directory is cleaned.

## 4. Single-clip download trace

### Frontend

File: `dashboard/src/components/ResultCard.jsx`

1. The clip's `download` button calls `downloadClip()`.
2. The source is `currentVideoUrl`, which is initialized from the current `clip.video_url`. Blob preview URLs are fetched directly; API media URLs go through `apiFetch`.
3. It streams the response body using a reader when available.
4. It reports preparing/downloading/completed/error states and byte/percentage progress.
5. In browser mode, it accumulates chunks into a Blob, triggers an anchor download named `clip-<index>.mp4`, and reports `your browser Downloads folder`.
6. In Tauri desktop mode, it writes chunks to native commands in 256 KiB pieces:
   - `begin_clip_download`
   - `append_clip_download_chunk`
   - `finish_clip_download`
   - `cancel_clip_download` on failure

### Native destination

File: `desktop/src-tauri/src/lib.rs`

- `clip_download_root()` resolves to `%USERPROFILE%\\Downloads\\Clippy` (or `$HOME/Downloads/Clippy` fallback).
- The directory is created automatically.
- `begin_clip_download` creates a new MP4 file with collision suffixes: `clip-1.mp4`, `clip-1 (2).mp4`, etc.
- It sanitizes the requested filename stem and always forces the `.mp4` extension.
- `append_clip_download_chunk` appends bytes.
- `finish_clip_download` flushes the file and rejects empty output.
- `cancel_clip_download` deletes an incomplete file.
- `reveal_clip_download` opens Explorer and selects the saved file.
- The frontend displays the final absolute path and offers `show in folder`.

### Limitations

- Filenames are generic clip indexes, not project/source titles.
- The native helper is MP4-specific and cannot directly save a ZIP.
- There is no destination picker; the folder is fixed to Downloads/Clippy.
- The flow is substantially better instrumented than Download All.

## 5. Download All trace

### Frontend

File: `dashboard/src/App.jsx::handleDownloadAll`

1. Calls `GET /api/jobs/{job_id}/download-all`.
2. Fetches the complete response as a Blob.
3. Creates an object URL and triggers an anchor download.
4. Uses the filename `openshorts_clips_<first-eight-job-id-chars>.zip`.
5. Immediately calls `URL.revokeObjectURL(url)` after the click.
6. Shows only `zipping…` while the request is active.
7. On error, uses a browser alert. On success, it returns to the idle button state without showing the final destination or a success confirmation.

It does not call the Tauri native download commands. There is no byte progress, cancellation, final path, or reveal-folder action.

### Backend

File: `app.py::download_all_clips`

1. Calls `_ensure_job_files` to ensure the job files are present (in cloud mode this can restore them from R2).
2. Reads the job metadata and prefers the current in-memory clip `video_url`, falling back to metadata/canonical filenames.
3. Includes files that exist on disk. Missing clip files are skipped rather than causing an explicit partial-download error.
4. Builds a ZIP in the temporary job directory named `clips_<unix_timestamp>.zip`.
5. Returns it as a `FileResponse` with attachment name `openshorts_clips_<job-id-prefix>.zip`.
6. Removes the temporary ZIP with a response background task after the response is sent.

### Confirmed design gaps / probable defects

- **Desktop parity gap:** Download All uses browser anchor download while single clip explicitly uses native file writes because the source comments say WebView2 can silently swallow an `<a download>` click. This makes Download All a strong candidate for the reported Windows desktop failure.
- **Object URL lifecycle risk:** Download All revokes the Blob URL immediately after `anchor.click()`; the single-clip browser fallback intentionally waits 60 seconds. Immediate revocation may race the webview/browser consuming the Blob. This needs runtime reproduction.
- **No success evidence:** The UI does not report the ZIP's final path or offer Explorer reveal. The button returning to idle is not proof the file was saved.
- **No transfer progress:** The UI only reports ZIP creation/request activity, not bytes downloaded.
- **Partial ZIP can look successful:** Backend silently skips missing clips and still returns a ZIP if at least one clip exists. The user is not told that some expected clips were omitted.
- **Potential concurrent ZIP collision:** The temporary ZIP name has second-level timestamp precision. Two simultaneous Download All requests for the same job within one second can target the same path.
- **No generic native file saver:** Current Tauri commands enforce MP4 and are not suitable for ZIP output without a generalized safe file-download command.

These are source-based findings. The first two are high-priority runtime hypotheses, not yet reproduced in the packaged app.

## 6. Library downloads

File: `dashboard/src/components/HistoryTab.jsx`

- History clip downloads use a direct anchor to `v.download_url`.
- Those URLs are signed R2 links produced by `cloud/videos.py::history`.
- This is cloud-specific and does not use the Windows native download path or display a saved destination.
- A local Library should download from its permanent local project path through a unified desktop save/export service, rather than depending on signed R2 links.

## 7. Tests found

- `tests/test_download_plan.py` tests YouTube source-download attempt ordering and proxy fallback. It is not a test of local clip downloads or the Download All ZIP.
- The initial branch tree did not reveal a dedicated frontend/desktop test suite for single-clip saving, Download All, destination selection, or Windows WebView2 behavior.
- No packaged-app runtime test has been executed during this source audit.

## 8. Recommendations for the Library/download redesign

1. Establish a permanent local Library root separate from `data/output` and `data/uploads`.
2. Archive validated videos, thumbnails, captions, platform variants, and edit metadata before the temporary job directory expires.
3. Keep original source footage optional and OFF by default. When enabled, copy it into the project archive; never move/delete the user's original input.
4. Make Library downloads/export and post-generation downloads use one shared native desktop download service.
5. Generalize the native writer to support a safe set of export types (at minimum MP4 and ZIP), with filename sanitization, collision handling, streaming progress, cancellation, completion validation, and reveal-in-folder.
6. Use meaningful filenames based on project title and clip index, with stable unique suffixes.
7. Give Download All an explicit ZIP progress/success/failure state and final path.
8. Report missing clips as a partial failure instead of silently producing an incomplete archive.
9. Avoid immediately revoking Blob URLs if a browser fallback remains.
10. Keep browser mode supported with browser-native download behavior and honest destination messaging.



## 10. Other similarly named download code (do not confuse these paths)

### Runtime dependency downloader

File: `desktop/src-tauri/src/downloader.rs`

This is the installer's runtime-component downloader, not the generated-clip downloader. It downloads runtime component ZIPs into its configured output directory, supports HTTP range resume, reports component download progress, verifies SHA-256, and extracts archives. The user-facing clip download commands are instead in `desktop/src-tauri/src/lib.rs`.

### Legacy Gallery

Files: `dashboard/src/components/Gallery.jsx` and `GalleryCard.jsx`

- The old Gallery fetches `/api/gallery/clips` and uses a separate browser Blob/anchor download.
- `GalleryCard` also revokes its Blob URL immediately after clicking the anchor.
- The current App shell comments out the Gallery import, and the active History screen is `HistoryTab`. Treat Gallery as legacy/unused unless a future route reactivates it.

### Existing source-retention knobs

File: `app.py`

- `SOURCE_RETENTION_SECONDS` is an environment-level retention timer, not a per-project user setting.
- It defaults to `JOB_RETENTION_SECONDS`.
- URL jobs are submitted with `--keep-original`, retaining the downloaded source in the temporary job output until the source/job cleanup policy removes it.
- Uploaded source files are stored in `UPLOAD_DIR` and swept using `JOB_RETENTION_SECONDS`.
- None of this is the agreed permanent Library source-retention feature. The new per-project option must copy source media into permanent Library storage only when enabled, while leaving the user's original input untouched.

## 11. Runtime validation still required

- [ ] Reproduce single-clip download in the packaged Windows app.
- [ ] Reproduce Download All in the packaged Windows app.
- [ ] Verify actual destination and file integrity for both actions.
- [ ] Test a large clip and a multi-clip ZIP.
- [ ] Test filename collisions.
- [ ] Test a missing clip in the ZIP source set.
- [ ] Test disk full / permission denied.
- [ ] Test app close during transfer.
- [ ] Test browser mode separately.
- [ ] Confirm the UI reports final path and success only after native save completion.


## 12. Library implementation update

The branch now contains the first local Library implementation:

- New `local_library.py` service and `tests/test_local_library.py`.
- Permanent Windows Library root: `%LOCALAPPDATA%\\Clippy\\data\\library`, passed to the backend as `CLIPPY_LIBRARY_DIR`.
- Completed jobs are archived automatically; completed jobs still available in the temporary output retention window are imported when the Library is opened.
- Project metadata is versioned. The project tree stores clip videos and platform captions separately from non-video workspace metadata. Original source is copied only when the persistent Library setting is enabled.
- Local Library APIs provide listing, detail, rename, delete, clip delete, caption read/write, video serving, and project ZIP export.
- Library UI provides project and clip Show in Folder actions, caption editing, individual downloads, ZIP export, rename and deletion.
- Native Tauri commands now support safe streamed MP4 and ZIP downloads and reveal archived paths in Windows Explorer.
- ResultCard single downloads and Download All now use the same native file-writing command family in packaged desktop mode.
- Download All now stages ZIPs with unique names and refuses to silently return an incomplete archive when any expected clip is missing.

### Runtime and build status

Source changes and unit tests have been committed, but no test execution or packaged Windows installer build has been performed in this audit environment. These checks remain mandatory before release. In particular, verify WebView2 streaming, File Explorer path reveal, the actual installed Library path, large ZIP transfers, disk-full behavior, and interruption recovery on Windows.

### Deferred by product decision

**Move To** is not part of v1. The Library root is fixed to the managed Clippy data location for this release. A future relocation feature must implement a verified copy, path/config update, restart/recovery handling, and safe cleanup before it is exposed.


## 13. Generation lifecycle and recovery

- Local projects are reserved when generation is queued, before the worker starts.
- The Library records queued/processing/failure/interruption states, not only completed projects.
- Completed output is archived after rendering; if archival fails, the project remains visible as `archive_failed` and is retried when the Library is loaded or the active project is synchronized.
- Restart recovery marks non-resumed queued/processing projects as interrupted. Resumed jobs keep their project record and update it when the worker starts again.
- User project renames and individual clip deletions survive synchronization. Tombstones prevent the original temporary job from recreating deleted projects or clips.


## 14. Synchronization and export reliability refinements

- A per-clip render fingerprint (source index, output filename, file size, and nanosecond mtime) avoids copying unchanged MP4 files every time the user opens Library.
- A separate caption digest detects changes to generated platform copy even when the video file is unchanged.
- Library-edited captions are marked user-authored and are not overwritten by later generator syncs.
- Download and export completion checks compare transferred byte count with the HTTP content length when available.
- Project/clip tombstones prevent deleted content from being re-imported. Startup cleanup handles orphan clip directories and abandoned ZIP exports.
