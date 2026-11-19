# Clippy agent instructions

The canonical project-wide engineering and agent guide is **[CLIPPY_MASTER.md](./CLIPPY_MASTER.md)**.

For the active Clippy v1 extraction, also read **[CLIPPY_CLEANUP_MASTER.md](./CLIPPY_CLEANUP_MASTER.md)**. It contains the owner-approved product scope, phase gates, preservation invariants, current findings, and validation record. Read the focused architecture/runtime/compliance documents linked from that ledger before changing those boundaries.

## Required startup

1. Read `CLIPPY_MASTER.md` and, when working on the v1 cleanup, `CLIPPY_CLEANUP_MASTER.md`.
2. Inspect the actual checked-out branch, Git status, recent commits, remotes, and relevant source/tests.
3. Treat source code, tests, configuration, Git history, and current CI as truth. Correct documentation when verified facts change.
4. Preserve existing functionality and user data. Never reset, clean, force-push, overwrite local changes, or delete documentation without explicit approval.
5. Trace behavior end-to-end before changing routes, service boundaries, runtime paths, secrets, data migration, or rendering contracts.
6. Run focused tests for changed behavior and report exact commands/results. Never claim an unrun test passed.
7. Do not treat historical findings in `CLIPPY_REPO_AUDIT.md` as current without revalidating them against the checked-out source.

## Branch-specific note

The current product baseline is main with the v0.3.1 native Windows installer/runtime. The branch `chore/master-cleanup-phase-0` is a short-lived cleanup branch created from the v0.3.1 source baseline; its current changes are documentation-only. Do not treat it as merged into main or as a permanent integration branch.

Keep this file short. Put durable project-wide guidance in `CLIPPY_MASTER.md`, and active cleanup phase tracking in `CLIPPY_CLEANUP_MASTER.md`.
