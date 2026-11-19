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

The release uses two distinct signing mechanisms:

**Tauri updater signing (mandatory)**

Configure both GitHub Actions repository secrets:

- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`

The release workflow checks that both are present, validates the configured Minisign public-key encoding and structure, and proves that the private key matches the public key by signing and verifying a temporary probe before starting the CPU/CUDA runtime matrix. These checks run in the `validate-signing` job and do not print or persist the private key. The private key must remain in GitHub Actions Secrets and must never be committed or printed. Tauri signs the final NSIS installer after any optional Authenticode modification; the resulting detached `.sig` is embedded in the generated `latest.json` manifest. A signed tag build is still required to verify the real release artifacts.

**Windows Authenticode signing (optional)**

- `WINDOWS_CODESIGN_CERTIFICATE_PFX_BASE64`
- `WINDOWS_CODESIGN_CERTIFICATE_PASSWORD`

If both are present, the workflow signs and verifies the installer before generating the Tauri updater signature. If neither is present, the installer can still be Tauri-updater-signed, but Windows may show an Unknown Publisher or SmartScreen warning. Supplying only one Authenticode secret fails the signing step. Authenticode and Tauri updater signing are separate; one does not replace the other.

## Update behavior

PR [#21](https://github.com/helalxp/clippy/pull/21) adds the Tauri 2 in-app updater for Windows. It downloads and verifies a complete NSIS installer update using the embedded Tauri public key and the stable GitHub endpoint:

`https://github.com/helalxp/clippy/releases/latest/download/latest.json`

This is a signed full-installer update, not a binary delta or independent runtime-component updater. The app payload keeps its previous known-good copy until runtime validation and backend/renderer health checks pass; failed startup restores the previous payload and retries service startup.

The published `v0.3.0` build predates updater support, so users on it must manually install the first updater-enabled release.

The first candidate, `v0.3.1-rc.1`, was not published: the Windows installer was generated, but Tauri rejected the updater public key because its outer Base64 value contained a newline. PR [#22](https://github.com/helalxp/clippy/pull/22) corrected the key formatting and added early public-key and private/public key-pair validation. Do not move or reuse the existing `v0.3.1-rc.1` tag.

The second candidate, `v0.3.1-rc.2`, was also not published. Release workflow run [#15](https://github.com/helalxp/clippy/actions/runs/44424600295) failed in `validate-signing`: that job invoked the checked-in updater-key validator without first checking out the tagged repository, so the runner reported `MODULE_NOT_FOUND`. The signing secrets were present and the tools installed; public-key validation and private/public key-pair verification never ran. PR [#23](https://github.com/helalxp/clippy/pull/23) implements the fix and was merged into `main` on 2026-11-19 as commit `1399053006103c7aa796114d3a25cded81b7b88b`: the job checks out the exact triggering tag before reading repository files, limits that job's token to read-only contents access, and tests this workflow requirement in the backend test suite. The rejected `v0.3.1-rc.2` tag remains unchanged.

The third candidate, `v0.3.1-rc.3`, was not published. Release workflow run [#16](https://github.com/helalxp/clippy/actions/runs/44429332589) failed in `validate-signing` because Tauri's Base64-encoded detached signature was passed directly to Minisign. PR [#24](https://github.com/helalxp/clippy/pull/24) corrected the signature decoding and added a workflow contract regression test; it was merged into `main` on 2026-11-19 as commit `a9ee1e179e69eec101b759e565534f3c7b9a80d5`. The unpublished `v0.3.1-rc.3` tag remains unchanged.

The next rollout target is `v0.3.1-rc.4`. Create the tag only after the canonical version and every synchronized manifest pass validation on the merged `main` commit:

1. Publish `v0.3.1-rc.4` as a prerelease and manually install it over an existing `v0.3.0` installation.
2. Verify startup, user-data preservation, managed-runtime reuse, and updater operation.
3. Publish stable `v0.3.1`; the prerelease installation should discover it through the stable-only `releases/latest` endpoint and install it in-app.

The current updater release does not transactionally roll back a multi-component runtime update. The first updater rollout must therefore remain application-only and must not change runtime contracts or runtime package inputs.

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
