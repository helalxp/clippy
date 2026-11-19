# Clippy agent instructions

Read **[CLIPPY_MASTER.md](./CLIPPY_MASTER.md)** as the canonical project-wide engineering guide. For the Clippy v1 extraction/cleanup, also read **[CLIPPY_CLEANUP_MASTER.md](./CLIPPY_CLEANUP_MASTER.md)** and the focused contracts linked from it.

1. Confirm the actual checkout, branch, remotes, recent commits, and local modifications before editing.
2. Treat source code, tests, configuration, Git history, and current CI as the final truth. Historical audit findings must be revalidated.
3. Read branch-specific `AGENTS.md`, platform contracts, and relevant subsystem docs when present.
4. Trace changes end-to-end and preserve user data, API contracts, local API authorization, ownership boundaries, and platform behavior.
5. Inspect callers, persistence, packaging, tests and rollback behavior before removing or relocating code.
6. Never apply stored patches blindly or claim tests/builds passed unless they were actually run.
7. Do not reset, clean, force-push, overwrite local changes, or delete operational/legal documentation without explicit approval.

## Branch and Windows release rules

- `main` is the authoritative product branch. Create short-lived feature/fix branches from latest main and return through pull requests.
- `chore/master-cleanup-phase-0` is a short-lived cleanup branch created from the v0.3.1 main baseline. It is not a permanent integration/release branch and its work is not merged until explicitly promoted.
- Current stable release baseline: **v0.3.1**, published 2026-11-19. Do not rely on old v0.2.3 release-status claims in historical docs.
- For changes affecting Tauri/Rust, PowerShell setup, runtime provisioning, installer/updater, Windows paths/processes, or packaged behavior, run Windows desktop validation on the relevant PR head. Revalidate after conflict resolution or later source changes.
- Keep the CI/Windows validation runs to the minimum necessary, but never skip checks that cover changed security, data-safety, runtime, or release contracts.
- Do not force-push, force-merge, or force-move a published release tag to bypass conflicts.
- Keep Whisper model-selection changes separate from installer lifecycle changes; reproduce the symptom and work from current main.
- Do not delete `%LOCALAPPDATA%\Clippy` as a troubleshooting shortcut. It contains user settings, output, uploads, caches, models and logs.
- Windows PowerShell 5.1 is the product setup host. When spawning it from PowerShell 7, remove inherited `PSModulePath` at the process boundary and keep the smoke-test coverage.
- Preserve signed updater verification, application-payload rollback, runtime integrity checks, per-launch API token, loopback binding, and user-data preservation.
