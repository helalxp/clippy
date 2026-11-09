# Clippy agent instructions

Read **[CLIPPY_REPO_AUDIT.md](./CLIPPY_REPO_AUDIT.md)** before engineering work. It is the canonical project, architecture, branch, safety, and audit handover.

1. Confirm the actual checkout, branch, remotes, recent commits, and local modifications.
2. Treat source code, tests, configuration, and Git history as the final truth; update the audit when verified facts change.
3. Read branch-specific `AGENTS.md`, platform contracts, and relevant subsystem docs when present.
4. Trace changes end-to-end and preserve user data, API contracts, authentication, ownership checks, and platform behavior.
5. Never apply stored patches blindly or claim tests/builds passed unless they were actually run.
6. Do not reset, clean, force-push, overwrite local changes, or delete operational/legal documentation without explicit approval.
