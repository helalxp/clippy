# Clippy Windows release process

Clippy uses semantic versioning. The canonical application version is stored in the repository-root `VERSION` file.

## Version rules

- Patch (for example, `0.2.4`): backwards-compatible fixes.
- Minor (for example, `0.3.0`): backwards-compatible features and improvements.
- Major (for example, `1.0.0`): intentional breaking changes or a first stable public contract.

Before a release, update `VERSION` and keep these files synchronized:

- `desktop/src-tauri/tauri.conf.json`
- `desktop/src-tauri/Cargo.toml` and the `clippy-desktop` entry in `desktop/src-tauri/Cargo.lock`
- `dashboard/package.json` and the root package entry in `dashboard/package-lock.json`

Run the consistency check:

```powershell
./desktop/validate-version.ps1
```

The installer build runs this check automatically. The payload builder copies the canonical `VERSION` into the installed application payload.

## Development changes versus official releases

**A version increment represents an official distributable application release, not an individual code change.** Do not bump the application version for every commit, fix branch, pull request, merge, internal build, or CI correction.

During normal development:
- Commit and merge independently validated fixes without changing the application version.
- Group multiple compatible fixes and improvements into a single release when practical.
- Use ordinary internal/test builds to validate changes; these do not need a new public release identity.
- Do not publish multiple different installers under an already-published version.

Increment the version when preparing a new official installer release for users:

| Change being shipped | Version increment |
|---|---|
| Backward-compatible bug fixes, small corrections, maintenance | Patch: 0.2.3 → 0.2.4 |
| Backward-compatible user-facing feature or substantial improvement | Minor: 0.2.3 → 0.3.0 |
| Intentional breaking change or stable public-contract transition | Major: 0.2.3 → 1.0.0 |
| Pre-release candidate for the next version | Prerelease identifier, e.g. 0.2.4-rc.1, 0.2.4-rc.2, then final 0.2.4 |

Choose the increment based on the most significant change included in the release. A release containing several bug fixes and a new backward-compatible feature is normally a minor release, not several patch releases. Keep prerelease identifiers ordered and do not treat an RC as a separate stable release.

Once a version has been published, its tag, installer, embedded payload version, and runtime assets are an immutable release identity. Never replace a published installer or force-move its tag while retaining the same version. A correction to a published release requires a new version. Reusing a version is only a controlled recovery option for an unpublished/failed candidate, after confirming no public release has been published.

## What the application version controls

The canonical application version is copied from root VERSION into the packaged application payload. At first launch, desktop/setup-runtime.ps1 reads that embedded version and constructs exact-version GitHub Release URLs, including the runtime manifest and archive parts. It does not resolve runtime downloads through a moving latest URL.

Therefore, publishing a new installer under an existing published version is unsafe: the installer would share the same release identity and versioned runtime asset location. The version is an installation/release contract, not merely the text displayed in the UI.

## Application version versus runtime component identity

The application version and managed runtime compatibility are separate concerns.

The runtime state/fingerprint is based on runtime component identities and compatibility inputs, including Python, Node.js, FFmpeg, the Remotion browser, and the SHA-256 of the packaged Python requirements. The application version itself is not part of the runtime compatibility fingerprint.

On an application upgrade, first-run setup checks the existing managed runtime. If the runtime manifest, component versions, dependency hash, required files, and health checks still match, setup reuses the healthy runtime and exits without reinstalling it. A version bump alone therefore does not imply that users must redownload the multi-gigabyte CPU/CUDA runtime.

Runtime changes can require component repair/replacement or a new runtime package. In particular, dependency changes affect the requirements hash; Python/CUDA, Node, FFmpeg, or Remotion/browser changes affect their corresponding compatibility checks. The setup script is authoritative for the exact behavior. Do not promise runtime reuse when a runtime compatibility input has changed or a health check fails.

## Current release-pipeline cost and future improvement

The current tag-triggered release workflow builds both CPU and CUDA runtime packages for each application release, even when the change is application-only (for example, a frontend-only fix). Existing installations can still reuse healthy runtimes, but CI spends time rebuilding and uploading runtime assets.

**Future TODO, not implemented:** decouple application releases from runtime package releases. Introduce independently versioned or content-addressed runtime artifacts, publish/rebuild them only when runtime inputs change, and let an application release reference an immutable runtime manifest/version. Preserve strict SHA-256 verification, exact compatibility checks, reproducible builds, and a reliable first-install path. Do not implement this by silently reusing mutable assets or weakening release/version validation.

A future in-app updater is also not currently implemented; the supported distribution path remains manual installation of each published installer release.

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
