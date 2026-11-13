# Clippy agent instructions

The canonical project, architecture, branch, development, and safety guide is **[CLIPPY_MASTER.md](./CLIPPY_MASTER.md)**.

## Required startup
1. Read `CLIPPY_MASTER.md` before engineering work.
2. Inspect the actual checked-out branch, Git status, recent commits, and relevant source/tests.
3. Treat source code, tests, configuration, and Git history as the truth. The master guide is orientation and must be corrected when it becomes stale.
4. Preserve existing functionality and user data. Never reset, clean, force-push, overwrite local changes, or delete documentation without explicit approval.
5. Run relevant tests/builds and report exact results. Never claim an unrun test passed.

## Branch-specific note
This branch contains the Windows-native migration work. The desktop shell is a scaffold, not proof of a completed production installer. Follow the migration status and exit criteria in `CLIPPY_MASTER.md`.

Keep this file short. Put durable project-wide guidance in `CLIPPY_MASTER.md`, not in competing agent instruction files.
