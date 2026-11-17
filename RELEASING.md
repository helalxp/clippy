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

## Runtime release assets

The runtime builder produces a manifest for each runtime variant:

- `clippy-python-cpu.manifest.json`
- `clippy-python-cuda.manifest.json`

A runtime below the configured 1.75 GiB part target remains one ZIP asset. Larger runtimes are split into deterministic, ordered binary parts. Each manifest records the application version, variant, original archive name, exact archive size and SHA-256, and each part's filename, size, and SHA-256. The workflow verifies the parts and reconstructs the original ZIP byte-for-byte before upload. First-run setup performs the same checks before extraction.

Do not rename, replace, or recompress a runtime part manually. Regenerate the manifest and checksums by rebuilding the runtime.

## Branch promotion model

Use this promotion path:

```text
windows-installer-hardening
        |
        | tested implementation and fix branch
        v
windows-installer-release
        |
        | integration branch; validate again after merge
        v
main
        |
        | release tags are cut from the accepted commit
        v
v< VERSION >
```

- `windows-installer-hardening` is the working branch for installer/runtime hardening and its focused CI.
- `windows-installer-release` is the integration branch for accepted Windows installer work.
- `main` is the repository's primary branch. Promote the integration branch to main only after the first merge and post-merge validation are complete.

Use pull requests for both promotions. Review the file diff and compare commit ranges before merging. Do not merge unrelated open feature PRs as part of this promotion. In particular, a separate Whisper/model-selection change should remain separate until it is independently investigated and tested.

## Release sequence

1. Finish the implementation on `windows-installer-hardening`. Commit the code and the related docs/runbooks together.
2. Confirm the branch validation workflow is green. This includes runtime package builds, version validation, PowerShell contract tests, Rust checks/tests, payload preparation and NSIS installer build.
3. Install and exercise the produced installer on a real Windows machine. Check first-run setup, app launch, the main video workflow, runtime reuse, and user-data preservation. Record any follow-up issue separately; do not mark an untested feature as verified.
4. Open and merge a PR from `windows-installer-hardening` into `windows-installer-release`.
5. Wait for the Windows validation workflow on `windows-installer-release` to pass after the merge.
6. Update or open the PR from `windows-installer-release` into `main`. Review the final comparison against main, including changes that originated on the long-lived installer branch, then merge it.
7. After the accepted code is on the intended release source branch, update the canonical version and mirrored manifests for a new release if required. Run `desktop/validate-version.ps1 -ExpectedVersion "vX.Y.Z"` (the release workflow supplies the tag automatically).
8. Push a new annotated tag named exactly `v<VERSION>`. A tag push triggers `Clippy Windows Release`; do not cut a release tag from an unvalidated commit.
9. The workflow builds CPU and CUDA runtime packages, verifies their manifests and reconstructed archives, runs backend/frontend and PowerShell/Rust tests, builds the NSIS installer, and runs the clean first-run/runtime/render smoke test.
10. The workflow creates a draft GitHub Release, uploads the installer, checksum, runtime manifests and assets, verifies all expected asset names and exact sizes, and publishes only after verification succeeds.
11. Verify the published release page and the manifest URL used by the installer. Confirm CPU and CUDA assets are all present and that the installer checksum sidecar matches the uploaded installer.

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
