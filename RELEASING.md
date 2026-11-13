# Clippy Windows release process

Clippy uses semantic versioning. The canonical version is stored in the repository-root `VERSION` file.

## Version rules

- Patch (`0.2.1`): backwards-compatible fixes.
- Minor (`0.3.0`): backwards-compatible features and improvements.
- Major (`1.0.0`): intentional breaking changes or the first stable public contract.

Before preparing a release, update `VERSION` and keep these files synchronized:

- `desktop/src-tauri/tauri.conf.json`
- `desktop/src-tauri/Cargo.toml` and `desktop/src-tauri/Cargo.lock`
- `dashboard/package.json` and `dashboard/package-lock.json`

Run the consistency check:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\validate-version.ps1
```

The local installer build runs this check automatically. The payload builder copies the canonical `VERSION` into the installed application payload.

## Runtime release assets

The runtime builder creates a manifest for each runtime variant:

- `clippy-python-cpu.manifest.json`
- `clippy-python-cuda.manifest.json`

A runtime that fits below the configured 1.75 GiB part target remains one ZIP asset. Larger runtimes are split into deterministic, ordered binary parts. The manifest records the application version, variant, original archive name, exact archive size and SHA-256, and every part's filename, size, and SHA-256.

The release setup engine downloads the manifest and each listed part from the exact matching release tag, verifies every part, reconstructs the original ZIP using streaming file I/O, and verifies the complete archive before extraction. Interrupted part downloads can resume. A missing release asset produces an explicit HTTP 404 diagnostic instead of three pointless retries.

Do not rename or manually replace a runtime part without regenerating its manifest and checksums.

## Release branch and flow

The active Windows installer integration branch in this repository is `windows-installer-release`. The runtime/release hardening work is developed on `windows-installer-hardening`. Keep the hardening branch separate until its clean-machine installer checks have passed. After acceptance, compare and merge it into `windows-installer-release`; do not create a release tag from an untested branch.

Release sequence:

1. Finish and review the work on `windows-installer-hardening`.
2. Run the PowerShell contract tests and the Windows desktop validation workflow.
3. Confirm the branch is mergeable into `windows-installer-release`. Complete the merge only after the installer has passed the two-PC test.
4. Update the canonical version and synchronized manifests if the release needs a new version.
5. Push a tag matching the canonical version, for example `v0.2.3`, from the accepted release commit.
6. The `Clippy Windows Release` workflow builds CPU and CUDA runtime packages, verifies their manifests and reconstructed archives, runs tests, builds the NSIS installer, and signs it.
7. The workflow creates a **draft GitHub Release**, uploads the installer, checksums, runtime manifests, and runtime assets, then verifies each uploaded asset's name and exact size.
8. Only after that verification succeeds does the workflow publish the release.
9. Users download the single NSIS installer from the published GitHub Release and run it. The installer obtains its matching runtime assets automatically.

The workflow rejects tags whose version does not match `VERSION`. It never downloads runtime assets from `latest`.

## Required GitHub Actions secrets

The current public-release workflow requires both:

- `WINDOWS_CODESIGN_CERTIFICATE_PFX_BASE64`
- `WINDOWS_CODESIGN_CERTIFICATE_PASSWORD`

These must contain a valid Authenticode signing certificate and its password. The workflow intentionally stops before building/publishing a public installer if either secret is missing. Do not disable signing checks merely to get a release out.

## Update behavior

This is an installer-based update channel, not an in-app auto-updater. Users install each published release manually. User data and separately stored AI model weights must remain outside the versioned application payload.
