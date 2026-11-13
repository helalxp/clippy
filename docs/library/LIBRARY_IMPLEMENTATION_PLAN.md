# Clippy Library v1: Implementation Plan

**Status:** Planning and codebase audit  
**Branch:** `feature/library-history`  
**Base branch:** `windows-installer-release`

## 1. Implementation approach

Do not implement the Library as a disconnected second storage system until the current generation, download, and desktop filesystem flows have been mapped. Reuse existing project/job metadata and desktop path conventions where safe, while separating permanent content from temporary job data.

## 2. Required discovery

- [x] Map the current Library/History navigation and existing screens.
- [x] Trace a single clip from successful render through the frontend result card.
- [x] Trace the single-clip Download action end to end.
- [x] Trace Download All end to end, including partial failures and archive/zip behavior if present.
- [x] Identify browser versus Tauri desktop execution paths.
- [x] Identify the actual destination directory on Windows for the native single-clip path; Download All destination is not explicitly controlled by Tauri.
- [x] Identify whether download actions copy, move, stream, or re-fetch media.
- [x] Identify progress, cancellation, completion, and error feedback.
- [x] Identify filename construction, collision handling, and extension/MIME handling.
- [ ] Inspect backend output layout, job metadata, and cleanup/retention behavior.
- [ ] Inspect desktop filesystem permissions/capabilities and any save-dialog integration.
- [x] Inspect available download tests; the located test covers source-download attempt planning, not local clip download or Download All.
- [ ] Record observed bugs separately from inferred risks.

## 3. Architecture decisions to validate against code

- Permanent project storage must be independent of temporary generation job storage.
- Project, run, and clip identities must be stable.
- Finished clips should be archived automatically after render validation.
- Original source retention is optional and OFF by default.
- Source retention copies the original; it never moves or deletes the user's input.
- Persist captions, platform variants, timestamps, thumbnails, and edit settings.
- Use relative paths within project metadata where possible.
- Keep full video reconstruction out of the v1 promise.
- Ensure cleanup is restricted to temporary workspaces.

## 4. Proposed implementation phases

### Phase 0: Audit and baseline
- Complete the Library UI and download lifecycle investigation.
- Document current behavior, exact code paths, current destination paths, and known defects.
- Identify any conflicts between existing download behavior and the new Library storage model.
- Agree on final UX with the product owner before implementation.

### Phase 1: Persistence foundation
- Define versioned project/run/clip metadata.
- Define Library root using existing Windows app-data conventions.
- Implement safe path resolution, atomic metadata writes, and project enumeration.
- Add optional source retention with OFF as default.
- Add tests for path isolation and cleanup boundaries.

### Phase 2: Generation integration
- Create project/run records at the correct lifecycle point.
- Archive validated outputs and metadata automatically.
- Recover or clearly mark interrupted/failed runs.
- Ensure a temporary job cleanup cannot remove archived files.

### Phase 3: Library UI
- Reuse/complete existing Library or History navigation.
- Add project cards, search/sort if already supported, project detail, clip list, and status indicators.
- Add rename/delete with confirmation and safe storage behavior.
- Add preview/download and caption editing.

### Phase 4: Download integration
- Decide whether downloads should save from permanent Library paths or use a shared download service.
- Support both single-clip and batch download consistently.
- Use clear destination selection/default path, collision-safe filenames, progress, cancellation, and actionable errors.
- Avoid duplicate copies when the Library itself already owns a permanent copy.
- Keep download/export semantics distinct from Library archival.

### Phase 5: Validation
- Run targeted backend and frontend tests.
- Test packaged Windows desktop behavior, not only browser development mode.
- Test restart persistence, multiple projects, source retention ON/OFF, interrupted generation, batch download, filename collisions, and insufficient disk space.
- Record exact test results and remaining limitations.

## 5. Definition of done

- The Library requirements in `LIBRARY_FEATURE_SPEC.md` are implemented or explicitly deferred.
- Download behavior is documented with verified source paths and destination semantics.
- No temporary cleanup path can delete permanent Library content.
- Windows packaged app can save, list, preview, and download archived clips.
- Batch download has clear success/failure reporting.
- Tests cover critical persistence, path safety, and download flows.
- Documentation is updated with actual implementation details, not just intended architecture.

## 6. Decision log

| Decision | Current direction |
|---|---|
| Branch | `feature/library-history` from `windows-installer-release` |
| Project naming | Automatic from original YouTube title; user can rename |
| Source retention | Optional, OFF by default |
| Permanent content | Rendered video, thumbnails, captions, platform variants, edit metadata |
| Full re-editing | Deferred; preserve future-compatible metadata |
| Project organization | Project-first, multiple runs and clips per project |
| Temporary output | Separate from permanent Library |
| Existing download behavior | Audit before changing |


## 7. Audit findings to carry into implementation

- The current HistoryTab is cloud/R2-backed. In the local Windows desktop mode, the relevant cloud routes are not mounted because `BILLING_ENABLED` defaults to false and the supervisor does not set it.
- Single clip: Tauri native stream to `%USERPROFILE%\\Downloads\\Clippy\\clip-<index>.mp4`, with collision suffixes, progress, completion path, and Explorer reveal.
- Download All: backend creates a temporary ZIP under `OUTPUT_DIR/<job_id>`, returns it via FileResponse, then deletes it. The frontend downloads it via Blob + anchor, immediately revokes the Blob URL, and does not use Tauri native file writing.
- The Windows installer stores working output under `%LOCALAPPDATA%\\Clippy\\data\\output`, not the repository's `output` folder. Local job output and uploads default to 24-hour retention.
- Download All has a likely WebView2 compatibility gap, an immediate Blob URL revocation risk, no final-path/success UI, and silent partial ZIP behavior when clip files are missing. These need packaged-runtime reproduction.
- The local Library must archive files outside the temporary job directory before cleanup and must not depend on the cloud R2 endpoints.

See `LIBRARY_DOWNLOAD_INVESTIGATION.md` for the complete source trace and exact files/functions.


## 7. Implementation status (source changes committed)

- [x] Add a standalone local Library storage service with schema-versioned project metadata.
- [x] Provision `data/library` in the Windows desktop runtime and pass its absolute path to the backend.
- [x] Reserve project records at queue time and track queued, processing, failed, interrupted, and completed states.
- [x] Archive successful local generation outputs before temporary job cleanup.
- [x] Add optional original-source copying, OFF by default, including uploaded source paths.
- [x] Add local project list/detail, rename, delete, clip delete, caption read/write, video stream, and ZIP export APIs.
- [x] Build the local Library UI with project cards, clip previews, editable platform captions, storage size, and Show in Folder actions.
- [x] Use the native Tauri file writer for both single-clip MP4 and Download All ZIP exports.
- [x] Add native File Explorer reveal commands scoped to the Library root or Clippy Downloads directory.
- [x] Add crash recovery for interrupted project directory swaps and mark unresumed jobs as interrupted.
- [x] Persist project/clip deletion tombstones so migration and sync cannot resurrect deleted content.
- [x] Add tests for archive, source retention, rename, caption updates, clip/project deletion, resync preservation, and recovery.
- [ ] Run the Python unit tests in the target runtime.
- [ ] Build the Tauri desktop app and NSIS installer.
- [ ] Execute the packaged Windows acceptance matrix on a real Windows machine.

### Explicitly deferred

- Move To / Library relocation to another drive or folder.
- Full source-based historical reconstruction and re-render.
- Nested project folders, cloud sync, and collaboration.
- Project thumbnail generation and richer search/filtering.



### Generation lifecycle

A project is now reserved after source validation/upload staging succeeds and before the job is enqueued. The project begins in `queued`, transitions to `processing`, then becomes `completed`, `failed`, `archive_failed`, or `interrupted` as appropriate. Once metadata arrives, the temporary display title is replaced by the source-video title unless the user has explicitly renamed the project.


### Synchronization and crash-safety refinements

- Rendered-media and generated-caption fingerprints prevent expensive full-project copies when the user merely opens Library or renames a project.
- Library-authored caption edits are flagged and preserved when newer generator output is synchronized.
- Project and clip deletion tombstones prevent deleted content from being re-imported.
- Clip metadata deletion is committed before media cleanup; startup removes orphan clip folders.
- Startup restores interrupted project directory swaps and removes abandoned ZIP exports.

## 8. Validation results (2026-11-13)

The first GitHub Actions run for the Library branch completed with the following results:

| Check | Result | Notes |
|---|---|---|
| Frontend build | PASS | Dashboard dependencies installed and production build completed. |
| Backend tests | PASS | The repository backend test job completed successfully, including the Library unit-test suite. |
| Windows desktop validation: dashboard build | PASS | Packaged desktop dashboard build completed. |
| Windows desktop validation: PowerShell scripts | PASS | Installer script validation completed. |
| Windows desktop validation: Python syntax | PASS | Backend syntax check completed. |
| Windows desktop validation: Rust/Tauri | PASS | Tauri application check completed. |
| Windows desktop validation: NSIS installer | PASS | Complete installer build completed and artifact-size measurement ran. |
| CPU relocatable Python runtime | PASS | Runtime build and relocation validation completed. |
| CUDA relocatable Python runtime | BLOCKED | Runtime archive was 3,194,596,811 bytes, above the workflow's 2 GiB per-asset release limit. CUDA availability was false on the hosted runner, as expected without a GPU. This is a packaging-size issue, not a Library test failure. |
| Packaged Windows smoke test | NOT RUN | A successful CI installer build is not proof of interactive behavior on the user's Windows machine. |

### Next acceptance pass

1. Install the generated NSIS artifact on a clean Windows profile and launch Clippy twice to verify Library persistence across restart.
2. Generate at least two projects with multiple clips and confirm each clip preview, caption edit, individual download, ZIP export, and Explorer reveal.
3. Confirm the Explorer actions open the project folder and select the requested archived MP4, respectively.
4. Test project and clip deletion, restart Clippy, and verify deleted entries do not return.
5. Test source retention OFF and ON using both a downloaded source and a user-uploaded source; verify the original upload is never moved or deleted.
6. Interrupt a generation, restart the app, and verify the Library status and any completed clips are preserved accurately.
7. Repeat Download All with a large project and verify the saved ZIP opens and contains every expected clip and caption file.

Do not treat the CUDA runtime packaging failure as a Library blocker. Track it separately against the Windows runtime packaging/release-size workstream. Do not merge this PR until the packaged Windows smoke test is completed and any Library-specific failures are fixed.


## 9. Follow-up hardening (2026-11-13)

- Serialized project deletion with the final archive publish operation using the Library's shared re-entrant lock.
- Added a final deletion-tombstone check while holding that lock, immediately before publishing the staging directory. This prevents a long-running archive operation from leaving a deleted project directory behind if the user deletes the project during archival.
- Added a regression test that triggers project deletion during the archive copy and asserts the archive aborts, the tombstone remains, and no project/staging directory is published.
- This follow-up was committed after the initial CI run. The GitHub connector has not reported a new workflow run or status for this follow-up commit yet, so the new regression test is not claimed as CI-verified.
