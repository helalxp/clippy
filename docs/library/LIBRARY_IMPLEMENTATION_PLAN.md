# Clippy Local Library v1: Integration and Verification Plan

**Target:** `main`  
**Working branch:** `feature/library-v1-integration`  
**Base:** `78700201434df5f901c93bfc313c77a5ebab3e13`

## Integration rules

- Never commit directly to `main` during feature development.
- Start the integration branch from the current stable `main` and selectively port the Library implementation. Do not merge the stale Library branch that is 317 commits behind.
- Preserve the current installer/runtime architecture and cloud History behavior.
- Keep one source video as one project. Do not add a separate run entity or a database for this single-user local archive.
- Reuse the app-managed FFmpeg, FastAPI, Tauri, existing atomic filesystem operations, and current frontend components.

## Delivery stages

1. **Integration foundation:** port local Library storage/API code; add mode-aware History navigation; provision the persistent data directory through the existing Tauri supervisor.
2. **Storage correctness:** snapshot the source-retention setting at project reservation; serialize metadata mutations; reconcile edits and tombstones at archive publish; preserve atomic replacement and crash recovery.
3. **Media and export:** generate per-clip thumbnails plus a project cover during archival; backfill thumbnails for older projects; authenticate native thumbnail/video requests with narrowly scoped read-only media tokens; export only clips, captions, and portable metadata.
4. **Desktop data relocation:** relocate the complete user-data root (output, uploads, Library, cached models, and reference templates) while leaving the app and managed runtimes in place. Drain active requests and jobs, check destination capacity, copy through staging with SHA-256 verification, persist the new location, restart both services, and retain the old source until the new location is healthy. Make runtime repair, native Explorer reveal, and installer reference migration honor the configured path.
5. **Desktop/frontend:** use the native streaming download path for MP4/ZIP; display project and clip thumbnails; expose the current data location and folder picker with progress; preserve cloud History and active-job flows.
6. **Automated verification:** run backend tests and the dashboard production build on PR; run Windows desktop validation, Rust checks, PowerShell validation, and complete installer build on PR. Include regression coverage for thumbnail backfill, configured data paths, and relocation safety.
7. **Installed Windows acceptance:** install the PR build; generate several projects; restart; verify permanent storage is independent of temporary job cleanup; toggle retention between new projects; verify thumbnails, rename, caption edits, clip deletion, project deletion, downloads, Explorer reveal, ZIP contents, and cloud History. Move the complete data folder to another drive; verify output, Library, cached models, and reference templates are present; restart Clippy and generate another project; test a rejected non-empty target and insufficient disk space without losing the original data.

## Merge gate

Keep the PR in draft until automated checks pass and the packaged Windows acceptance cases are completed. Feature integration does not modify `main`; merge must be a separate, explicit action after review and verification.
