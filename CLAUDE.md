# Clippy agent instructions

The canonical project, architecture, branch, development, and safety guide is **[CLIPPY_MASTER.md](./CLIPPY_MASTER.md)**. The repository-wide audit, branch inventory, known risks, and coverage ledger are in **[CLIPPY_REPO_AUDIT.md](./CLIPPY_REPO_AUDIT.md)**.

## Required startup
1. Read `CLIPPY_MASTER.md` before engineering work.
2. Inspect the actual checked-out branch, Git status, recent commits, and relevant source/tests.
3. Treat source code, tests, configuration, and Git history as the truth. The master guide is orientation and must be corrected when it becomes stale.
4. Preserve existing functionality and user data. Never reset, clean, force-push, overwrite local changes, or delete documentation without explicit approval.
5. Run relevant tests/builds and report exact results. Never claim an unrun test passed.

## Branch-specific note
The default branch still contains the Docker-oriented OpenShorts-derived application. The Windows-native desktop migration is developed separately on `windows-native-migration`. Do not assume native desktop code is present on this branch.

Keep this file short. Put durable project-wide guidance in `CLIPPY_MASTER.md`, not in competing agent instruction files.
