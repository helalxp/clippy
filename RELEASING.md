# Clippy Windows release process

Clippy uses semantic versioning. The canonical application version is stored in the repository-root `VERSION` file.

## Version rules

- Patch (for example, `0.2.4`): backwards-compatible fixes.
- Minor (for example, `0.3.0`): backwards-compatible features and improvements.
- Major (for example, `1.0.0`): intentional breaking changes or a first stable public contract.

Before a release, use the version-bump script from the repository root. It updates the canonical version and all application package/build manifests together:

- `desktop/src-tauri/tauri.conf.json`
- `desktop/src-tauri/Cargo.toml` and the `clippy-desktop` entry in `desktop/src-tauri/Cargo.lock`
- `dashboard/package.json` and the root package entry in `dashboard/package-lock.json`

For example, to prepare the next release candidate:

```powershell
./desktop/set-version.ps1 -Version 0.2.4-rc.4
```

The script validates SemVer, updates `VERSION`, Tauri, Cargo, Cargo.lock, the dashboard package and npm lockfile, then runs the consistency check. It does not change third-party dependency versions or create/push a Git tag. Run the check independently before building or tagging:

```powershell
./desktop/validate-version.ps1 -ExpectedVersion v0.2.4-rc.4
```

The installer build runs this check automatically. The payload builder copies the canonical `VERSION` into the installed application payload.

## Runtime release assets

The runtime builder produces a manifest for each runtime variant:

- `clippy-python-cpu.manifest.json`
- `clippy-python-cuda.manifest.json`

A runtime below the configured 1.75 GiB part target remains one ZIP asset. Larger runtimes are split into deterministic, ordered binary parts. Each manifest records the application version, variant, original archive name, exact archive size and SHA-256, and each part's filename, size, and SHA-256. The workflow verifies the parts and reconstructs the original ZIP byte-for-byte before upload. First-run setup performs the same checks before extraction.

Do not rename, replace, or recompress a runtime part manually. Regenerate the manifest and checksums by rebuilding the runtime.

## Branch and promotion model

`main` is the single authoritative branch. The former `windows-installer-hardening` and `windows-installer-release` branches completed the v0.2.3 migration and are no longer part of the ongoing release process.

Use this flow for every new feature or fix:

```text
main
 |
 | create a short-lived feature/fix branch
 v
feature/<name> or fix/<name>
 |
 | pull request, focused review and required CI
 v
main
 |
 | accepted, validated commit
 v
v<VERSION> release tag
```

- Create each branch from the latest `main`.
- Keep one feature or root-cause fix per branch where practical.
- Open the pull request against `main`, not an old installer integration branch.
- Review the complete diff and commit range. Reconcile with the latest main before merge.
- Require the relevant CI on the exact PR head. Installer/runtime changes additionally require Windows validation and packaged setup/render checks.
- Do not merge unrelated open feature PRs or combine Whisper/model-selection changes with installer lifecycle work.
- Do not delete, reset, or force-update branches unless explicitly authorized. A completed PR can be closed/merged while the branch is cleaned up separately.

## Release sequence

1. Start from a clean checkout of the latest `main`, then create a short-lived feature/fix branch.
2. Implement the scoped change and add regression tests for the reproduced behavior.
3. Run focused tests locally where available. Push the branch and open a PR against `main`.
4. Confirm all required CI is green on the exact PR head. For Windows installer/runtime changes, run the Windows desktop validation workflow, runtime package checks, payload/PowerShell contracts, Rust checks/tests, installer build, and first-run/render smoke tests.
5. Exercise the relevant packaged application flow on a real Windows machine when the change affects installation, runtime setup, hardware selection, or user-facing desktop behavior. Record any remaining limitation rather than claiming it is verified.
6. Merge the PR into `main` only after review and validation. Re-run affected checks if the merge result differs from the tested PR head.
7. For a release, update the canonical version and synchronized manifests only after the accepted code is on `main`. Run `desktop/validate-version.ps1 -ExpectedVersion "vX.Y.Z"` (the release workflow supplies the tag automatically).
8. Push a new annotated tag named exactly `v<VERSION>`. A tag push triggers `Clippy Windows Release`; do not cut a release tag from an unvalidated commit.
9. The workflow builds CPU and CUDA runtime packages, verifies their manifests and reconstructed archives, runs backend/frontend and PowerShell/Rust tests, builds the NSIS installer, and runs the clean first-run/runtime/render smoke test.
10. The workflow creates a draft GitHub Release, uploads the installer, checksum, runtime manifests and assets, verifies all expected asset names and exact sizes, and publishes only after verification succeeds.
11. Verify the published release page and manifest URLs. Confirm CPU and CUDA assets are all present and the installer checksum sidecar matches the uploaded installer.
The workflow rejects a tag whose version does not match `VERSION`. Runtime downloads use the exact embedded application version, not the moving `latest` release.

**Do not force-move an already published release tag.** If a tag-triggered run fails before publication, diagnose the failed step, fix the source, validate again, and only retarget an unpublished/rejected tag when the team deliberately chooses to reuse that version. Once a release has been published, use a new version for corrections.

## Code signing

The release workflow supports Authenticode signing when both secrets are configured:

- `WINDOWS_CODESIGN_CERTIFICATE_PFX_BASE64`
- `WINDOWS_CODESIGN_CERTIFICATE_PASSWORD`

If both are present, the workflow signs and verifies the installer. If neither is present, the current workflow emits a warning and continues with an unsigned installer. Supplying only one secret fails the signing step. For public production distribution, configure both secrets and verify the signature; do not mistake a successful unsigned release for a signed release.

## Update behavior

This is currently an installer-based update channel, not an in-app auto-updater. Users install each published release manually. User settings, projects, uploads, generated videos, caches, and downloaded model weights must remain outside replaceable application payloads.

## Verified v0.2.3 release record

The v0.2.3 release was published on 2026-11-17 after all release workflow steps passed.

- [Published release](https://github.com/helalxp/clippy/releases/tag/v0.2.3)
- [Release workflow run #5](https://github.com/helalxp/clippy/actions/runs/44066693854): CPU and CUDA runtime builds, payload/manifest checks, PowerShell contract tests, first-run setup/render smoke test, Rust tests, draft asset verification, and publication all passed.
- [Windows desktop validation run #360](https://github.com/helalxp/clippy/actions/runs/44062955499): passed on the same source commit.
- The release contains 10 assets: installer and checksum, CPU runtime and manifest/checksums, CUDA manifest, two CUDA parts, and CUDA part checksums.
- The installer was manually installed and exercised on a Windows machine through the editing workflow. A Whisper model-selection hiccup was noted for separate follow-up; it is not described as fixed by this release.

## Completed v0.2.3 branch promotion record

The v0.2.3 installer implementation is now integrated into `main`. The published
release tag was not moved or rewritten during promotion.

| Promotion/check | Result |
|---|---|
| `windows-installer-hardening` → `windows-installer-release` | PR [#14](https://github.com/helalxp/clippy/pull/14), merged 2026-11-17; merge commit `b2086ea27b9237c0a85d0638a24952336b77fcc7` |
| `windows-installer-release` → `main` | PR [#3](https://github.com/helalxp/clippy/pull/3), merged 2026-11-17; merge commit `e238e92c599c7f34357d2093db0b95dae102a7e4` |
| Post-merge Windows integration validation | [Run #368](https://github.com/helalxp/clippy/actions/runs/44086793620), passed on integration commit `6873f5dcc101f8af804481d2434cdf05900e95a5`; CPU/CUDA runtime builds and Windows installer validation all passed |
| Post-merge general CI | [PR CI](https://github.com/helalxp/clippy/actions/runs/44086795898), passed backend tests and frontend build on the same integration commit |
| Main push CI | [Run after merge](https://github.com/helalxp/clippy/actions/runs/44090057236), passed on merge commit `e238e92c599c7f34357d2093db0b95dae102a7e4` |
| Main docs-refresh CI | [Run #44090278204](https://github.com/helalxp/clippy/actions/runs/44090278204), passed on audit-refresh commit `0062eaf12e8d2ff0e22c67cd9cfa8f4d64ad1a49` |

The current `main` branch is the authoritative source and includes the Windows installer and its documentation. The former hardening and integration branches completed their v0.2.3 promotion; use short-lived feature/fix branches from `main` for all subsequent work. Whisper model-selection remains a separate unresolved issue and must be investigated from a fresh branch, not by reviving the superseded PR #13 patch series.
