# Clippy agent instructions

Read **[CLIPPY_REPO_AUDIT.md](./CLIPPY_REPO_AUDIT.md)** before engineering work. It is the canonical project, architecture, branch, safety, and audit handover. For Windows installer work, also read [the operations runbook](./docs/architecture/windows-installer-operations-runbook.md), [the first-run contract](./desktop/FIRST_RUN_SETUP_CONTRACT.md), and [RELEASING.md](./RELEASING.md).

1. Confirm the actual checkout, branch, remotes, recent commits, and local modifications.
2. Treat source code, tests, configuration, and Git history as the final truth; update the audit when verified facts change.
3. Read branch-specific `AGENTS.md`, platform contracts, and relevant subsystem docs when present.
4. Trace changes end-to-end and preserve user data, API contracts, authentication, ownership checks, and platform behavior.
5. Never apply stored patches blindly or claim tests/builds passed unless they were actually run.
6. Do not reset, clean, force-push, overwrite local changes, or delete operational/legal documentation without explicit approval.


## Windows installer release rules

- `main` is the primary branch. `windows-installer-release` is the Windows installer integration branch. `windows-installer-hardening` is the focused installer/runtime development branch.
- Promote changes with pull requests: hardening -> installer release -> main. Review the full compare, preserve both branch histories, and validate the target branch after every merge.
- Do not force-push, force-merge, or force-move a published release tag to bypass conflicts.
- Keep Whisper model-selection changes separate from installer lifecycle changes unless they are deliberately included and independently tested.
- Do not delete `%LOCALAPPDATA%\Clippy` as a troubleshooting shortcut. It contains user settings, output, uploads, caches, and model weights.
- Windows PowerShell 5.1 is the product setup host. When spawning it from a PowerShell 7 environment, remove inherited `PSModulePath` at the process boundary as implemented in the Rust launcher and smoke test.
- v0.2.3 is the verified release baseline. The full release and Windows validation runs are linked from the runtime contract and operations runbook. Do not infer that future commits are tested just because this release was.
