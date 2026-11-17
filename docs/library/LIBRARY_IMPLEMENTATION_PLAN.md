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
3. **Media and export:** generate per-clip thumbnails plus a project cover during archival; export only clips, captions, and portable metadata.
4. **Desktop/frontend:** use the native streaming download path for MP4/ZIP; display project and clip thumbnails; preserve cloud History and active-job flows.
5. **Automated verification:** run backend tests and the dashboard production build on PR; run Windows desktop validation, Rust checks, PowerShell validation, and installer build on PR.
6. **Installed Windows acceptance:** install the PR build; generate several projects; restart; verify permanent storage is independent of temporary job cleanup; toggle retention between new projects; verify thumbnails, rename, caption edits, clip deletion, project deletion, downloads, Explorer reveal, ZIP contents, and cloud History.

## Merge gate

Keep the PR in draft until automated checks pass and the packaged Windows acceptance cases are completed. Feature integration does not modify `main`; merge must be a separate, explicit action after review and verification.
