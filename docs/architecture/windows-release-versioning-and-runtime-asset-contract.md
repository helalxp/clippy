# Windows Release Versioning and Runtime Asset Delivery Contract

**Status:** v0.2.3 published; release CI and Windows desktop validation passed; real Windows install exercised through the editing workflow  
**Implementation branch:** `windows-installer-hardening` (promotion target: `windows-installer-release`, then `main`)  
**Application version:** `0.2.3`  
**Last reviewed:** 2026-11-17

## 1. Purpose

This document defines how Clippy's Windows installer version, application payload, Python runtime packages, GitHub Release tag, runtime download URLs, and checksums must stay aligned.

The production requirement is simple:

> A user downloads one Clippy installer, installs it, opens it, and Clippy automatically downloads and installs the exact runtime package required by that installer. The user must not need PowerShell commands, manually supplied archives, Python, or environment-variable overrides.

This document records the implemented delivery contract and the verified v0.2.3 release baseline. Subsequent changes must repeat the CI, clean first-run, and real-machine gates; the v0.2.3 result is not a blanket approval for future releases.

## 2. Canonical application version

The repository-root `VERSION` file is the single source of truth for the Clippy application version.

The following files must contain the same application version:

- `VERSION`
- `desktop/src-tauri/tauri.conf.json`
- `desktop/src-tauri/Cargo.toml`
- `desktop/src-tauri/Cargo.lock` entry for `clippy-desktop`
- `dashboard/package.json`
- `dashboard/package-lock.json` root package entry

The existing `desktop/validate-version.ps1` checks these values and, when supplied, checks the expected release tag. It is already called by `desktop/build.ps1` and by `.github/workflows/release-windows.yml`.

Required release-tag format:

```text
VERSION = 0.2.3
Git tag  = v0.2.3
Release  = v0.2.3
```

A release must not be published if the tag does not match the canonical `VERSION`.

## 3. Application payload version

`desktop/prepare-payload.ps1` copies the root `VERSION` file into the staged application payload. The runtime setup engine reads:

```text
%LOCALAPPDATA%\Clippy\app\current\VERSION
```

That value determines which GitHub Release the installed app will use for its runtime download.

The build must validate the canonical version before creating the payload. The payload version must be treated as immutable after packaging. A setup script must never infer its release version from the latest GitHub release, a branch name, or a hard-coded fallback.

## 4. Runtime asset naming and release contract

The implemented release contract uses this convention:

| Item | Expected value for version 0.2.3 |
|---|---|
| Release tag | `v0.2.3` |
| CPU runtime manifest | `clippy-python-cpu.manifest.json` |
| CUDA runtime manifest | `clippy-python-cuda.manifest.json` |
| CPU runtime asset | `clippy-python-cpu.zip` while it remains below the part-size threshold |
| CUDA runtime assets | Ordered `clippy-python-cuda.partNNN` files when multipart |
| Per-variant metadata | `clippy-python-<variant>.parts.sha256` |
| Example manifest URL | `https://github.com/helalxp/clippy/releases/download/v0.2.3/clippy-python-cuda.manifest.json` |

The archive asset names are intentionally stable within each versioned release. The release tag supplies the application-version boundary. The local cache filename may include the application version to avoid collisions between cached packages.

The release workflow must publish the installer, installer checksum, CPU runtime archive and checksum, and CUDA runtime archive or its multipart representation and manifest/checksums to the same matching release.

A successful installer build is not proof that the runtime download is available. The matching release and all required runtime assets must exist before the installer is distributed.

## 5. Audit findings

### 5.1 Historical audit finding: no published GitHub Release (resolved)

This was true during the initial audit, before v0.2.3 was published. It is now resolved: [Clippy v0.2.3](https://github.com/helalxp/clippy/releases/tag/v0.2.3) was published on 2026-11-17 and contains the installer, checksums, CPU runtime assets, CUDA manifest, and both CUDA runtime parts. The release workflow verifies the expected asset names and exact sizes before publication.

### 5.2 Historical audit finding: installed application version differed from the audited source version

The user's installed setup log reports a local download/cache filename:

```text
clippy-python-cuda-0.2.1.zip
```

The old setup implementation used the application version in the local cache filename but constructed the remote release URL with an unversioned asset name. Therefore, the historical log's filename alone did **not** prove that GitHub was asked for an asset with the `.0.2.1` suffix.

The installed payload is using application version `0.2.1`; the audited branch has `VERSION = 0.2.3`. Under the current contract, the expected remote URLs are:

```text
Installed 0.2.1 (old format): /releases/download/v0.2.1/clippy-python-cuda.zip
Current 0.2.3 (manifest):     /releases/download/v0.2.3/clippy-python-cuda.manifest.json
```

This was a historical version mismatch observed during the pre-release audit. It was resolved by publishing v0.2.3 from the validated source commit. The installed payload now embeds its own canonical version and constructs runtime URLs from that exact version; it must never fall back to a moving `latest` release.

For every future release, build the installer from the accepted release commit and verify that its embedded payload version matches the tag before distribution.

### 5.3 Confirmed: current version consistency checks are useful but do not publish releases

`desktop/validate-version.ps1` checks the application manifests and optional tag. The release workflow invokes it before building the installer.

This prevents several source-level version mismatches, but it cannot create a missing release asset by itself. The release workflow must complete successfully and publish the runtime assets.

### 5.4 Implemented: runtime archive builder handles the GitHub asset-size limit

`desktop/build-python-runtime.ps1` now creates the complete runtime ZIP, computes its whole-archive SHA-256, and calls `desktop/runtime-archive.ps1` to produce a manifest and release-safe assets. Files below the 1.75 GiB target remain a single ZIP; larger files are segmented into ordered binary parts. The builder reconstructs the parts and tests extraction/imports from that reconstructed archive. The original multi-part ZIP is not uploaded as an oversized release asset.

### 5.5 Implemented: release workflow handles manifest-based runtime assets

`.github/workflows/release-windows.yml` now:

1. Builds CPU and CUDA runtime archives in a matrix.
2. Uploads all per-variant runtime assets and metadata as workflow artifacts.
3. Downloads those artifacts in the publishing job.
4. Runs `desktop/validate-runtime-assets.ps1` to validate manifests, parts, and reconstructed archive hashes.
5. Runs the PowerShell runtime contract tests.
6. Builds and signs the installer.
7. Creates a draft release, uploads the installer and runtime assets, verifies every expected asset name and exact size through the GitHub API, and publishes only after verification.

The actual Windows Actions run remains the authoritative validation of this workflow.

### 5.6 Branch roles and merge timing

`windows-installer-release` is the integration target and `windows-installer-hardening` is the isolated implementation branch. The draft pull request is #10. The branches currently share a merge base at the current integration-branch head, so the hardening branch is ahead without the target containing unique commits. The pull request currently reports `mergeable: true`. Do not merge until both user test PCs pass.

### 5.7 Runtime download resilience

The audited setup engine already has useful production-oriented download behavior:

- HTTPS requests with redirects enabled.
- Three attempts for interrupted downloads.
- HTTP Range-based continuation of partial downloads.
- Validation of the server's Content-Range response.
- Preservation of partial data for retry.
- SHA-256 verification of the completed runtime archive before extraction.

The downloader now detects HTTP 404 and stops retrying, reporting the exact missing asset URL and reminding the user to verify the matching release. The existing resumable transfer behavior is reused for every manifest-listed part.

## 6. Release gates and version-mismatch prevention rules

The following rules should be treated as release gates:

1. **One canonical version:** only the root `VERSION` file is edited to select the next application version; the existing validator checks all mirrored manifests.
2. **Tag equality:** a release tag must be exactly `v<VERSION>`.
3. **Payload equality:** the packaged payload's `VERSION` must equal the canonical source version used to build the installer.
4. **Release equality:** the runtime downloader uses the payload version to construct the release URL. It must not use `latest`.
5. **Asset contract equality:** the release workflow and setup engine must share one documented asset naming convention.
6. **Pre-publication gate:** the release workflow must verify that every required runtime asset and checksum/manifest is present, correctly named, and valid before publishing the installer.
7. **Post-publication gate:** after publishing, the workflow should query the created release and verify that every required asset is attached and has the expected size before the release is considered ready.
8. **Fail clearly:** a missing asset should produce a diagnostic naming the requested release tag and asset. It must not be presented as a generic Python installation failure.
9. **No manual customer overrides:** local archive environment variables remain development/test hooks only. They are not part of the customer installation procedure.

## 7. CUDA archive size and multipart implementation

### 7.1 Platform constraint

GitHub documents that each individual release asset must be under 2 GiB. A release may contain up to 1,000 assets, and GitHub does not impose a total-size limit on the release assets.

Official reference: [GitHub Docs: About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

The current CUDA archive is approximately 3.35 GB, so it cannot be attached as one GitHub Release asset.

### 7.2 Recommendation: split the completed archive into binary parts

**Implemented:** the builder segments the completed ZIP as raw byte ranges for the current GitHub Releases hosting plan.

The build should first create and validate the complete ZIP archive. It should then split that exact byte stream into ordered binary parts, each comfortably below the platform limit. A conservative target is approximately 1.75 GiB per part rather than attempting to approach 2 GiB.

Illustrative assets:

```text
clippy-python-cuda.part001
clippy-python-cuda.part002
clippy-python-cuda.manifest.json
clippy-python-cuda.parts.sha256
```

The exact number of parts must be calculated from the archive size; larger future archives may produce more than two parts. Part names must be deterministic and zero-padded.

This is byte-level segmentation of the already-compressed ZIP, not recompression into independent ZIP files. Concatenating the parts in the specified order reconstructs the original ZIP byte-for-byte.

### 7.3 Manifest contract

The manifest should contain at least:

- Manifest schema version.
- Clippy application release version.
- Runtime package variant (`cpu` or `cuda`).
- Original archive filename and exact byte length.
- Original archive SHA-256.
- Ordered list of part filenames.
- Exact byte length and SHA-256 for every part.
- Total part count.

The release tag, manifest application version, and setup payload version must agree.

### 7.4 Installer download and reconstruction flow

For a multipart runtime, the setup engine now:

1. Read the manifest from the same versioned GitHub Release.
2. Validate the manifest schema, application version, runtime variant, part count, names, and declared sizes.
3. Download each part to the managed Clippy download directory, using the existing resumable-download mechanism.
4. Verify each part's exact size and SHA-256 before accepting it.
5. Concatenate the parts in manifest order using buffered file streams. Do not load the multi-gigabyte archive into memory.
6. Verify the reconstructed archive's exact byte length and whole-file SHA-256.
7. Extract only after all integrity checks pass.
8. Preserve verified parts after an interrupted setup so a retry does not download completed parts again.
9. Remove temporary parts and reconstructed archive after successful installation, subject to the chosen cache policy.

A missing, duplicated, reordered, truncated, or modified part must stop setup before extraction.

### 7.5 Why this is preferable to recompressing or splitting the runtime into separate packages

- It preserves the already-tested archive byte-for-byte.
- It does not change Python package layout or runtime import behavior.
- It does not require the customer to install a third-party archive utility.
- It avoids loading the complete archive into RAM.
- It uses ordinary GitHub Release assets and the existing release hosting workflow.
- It permits independent resume and integrity checks for each part.

The split operation itself is simple; the important engineering work is the manifest contract, reliable part download/resume, ordered reconstruction, and end-to-end checksum verification.

### 7.6 CI implementation

- Remove the current single-file 2 GiB rejection as the final packaging outcome.
- Split the completed CUDA archive into bounded parts.
- Generate a manifest and per-part checksums, retaining the whole-archive checksum.
- Test reconstruction in CI and compare the reconstructed archive's size and SHA-256 with the original.
- Test extraction and imports from the reconstructed archive, not merely from the pre-split source.
- Upload all parts and metadata as workflow artifacts.
- Update release validation and release asset globs to include the parts and manifest.
- Ensure the release job rejects any individual part at or above the configured safe maximum.

The CPU package remains a single ZIP plus checksum while it remains below the configured part-size threshold.

## 8. Release readiness checklist

A Windows release is not ready to distribute until all of the following are true:

- [ ] Root `VERSION` and all mirrored application manifests agree.
- [ ] Git tag equals `v<VERSION>`.
- [ ] Installer payload contains the same `VERSION`.
- [ ] CPU runtime asset is published and verified.
- [ ] CUDA runtime manifest and every part are published and verified, or a single CUDA archive is below the limit.
- [ ] Runtime package SHA-256 checks pass.
- [ ] CI reconstructs and extracts the exact CUDA archive successfully.
- [ ] The release contains the installer and its checksum.
- [ ] A clean Windows installation completes without environment overrides or manual files.
- [ ] The published release is checked for all expected assets before users receive the installer.

## 9. Runtime repair and upgrade safeguards

- `desktop/runtime-contract.json` defines Python, Node and FFmpeg identities for both setup and native validation. Browser identity comes from the packaged Remotion renderer, not the previous installed manifest.
- Embedded Python retains `_pth` isolation and explicitly admits `../../app/current`; setup smoke checks the imported backend belongs to that payload.
- Saved reference templates live under `data/reference_templates`. Before replacing a payload, native setup copies legacy references there, verifies conflicting files and aborts rather than overwriting user data.
- A desktop-lifetime named mutex prevents concurrent shells; the payload installer and PowerShell setup share an installation mutex. Setup waits for the native `GO` handshake before mutating files, then runs in the shell's kill-on-close Job Object.
- Runtime replacements are staged and validated before directory activation, with rollback and interrupted-upgrade recovery. Windows sharing/access failures get a bounded retry, never a destructive workaround.
- Google's Chrome Headless Shell is unsigned. Setup pins its official versioned Google HTTPS archive and executable SHA-256 hashes in `runtime-contract.json`, verifies both before activation, and never substitutes system Chrome. Payload preparation rejects a renderer whose tested browser version differs from the contract.
- Native checks include backend imports, FFprobe and an actual headless-browser launch. Retry setup invokes repair even if executable-version checks previously passed.
- Renderer and composition packages use matching pinned Remotion versions and committed lockfiles. `prepare-payload.ps1` checks package identities and required files.
- `desktop/smoke-test-runtime.ps1` verifies clean CPU setup, a packaged video render using the persistent browser, and a repeat setup without downloads. These checks do not replace CUDA hardware validation or testing the published release download route.

## 10. Implementation status

The coordinated implementation has been committed on `windows-installer-hardening`:

- `desktop/runtime-archive.ps1`: manifest validation, safe part naming, per-part hashing, streaming reconstruction, and whole-archive verification.
- `desktop/build-python-runtime.ps1`: manifest generation, automatic splitting below the 2 GiB platform limit, reconstruction, and validation of the reconstructed archive.
- `desktop/setup-runtime.ps1`: manifest download, strict version/variant checks, per-part download and verification, resumable part caching, streaming reconstruction, and explicit 404 handling.
- `desktop/prepare-payload.ps1`: includes the runtime archive helper in the installed payload.
- `desktop/validate-runtime-assets.ps1`: CI validation of both runtime variants and their reconstructed archives.
- `desktop/tests/RuntimeArchive.Tests.ps1`: Pester coverage for multipart round trips, single-part archives, mismatched versions/variants, corrupted parts, and unsafe filenames.
- `.github/workflows/release-windows.yml`: uploads manifest-based runtime assets and uses a draft-first, verify-before-publish release flow.
- `RELEASING.md`: documents the release contract, branch flow, and required signing secrets.

**Verified v0.2.3 baseline (2026-11-17):**

- Source commit: `9454c5eb485cc75c0ee14a00d11bd405d9a320aa`.
- Windows desktop validation: [run #360](https://github.com/helalxp/clippy/actions/runs/44062955499), passed.
- Full release: [run #5](https://github.com/helalxp/clippy/actions/runs/44066693854), passed. Both CPU and CUDA runtime builds, asset reconstruction/validation, PowerShell contract tests, clean first-run setup, packaged rendering smoke test, Rust tests, draft asset verification, and publication passed.
- Published assets: one NSIS installer and checksum, one CPU ZIP plus manifest/checksums, and a CUDA manifest with two ordered parts and part checksums.
- Manual Windows validation: the user confirmed successful install, first launch and use through the editing workflow. A Whisper model-selection hiccup remains a separate follow-up and is not claimed as fixed here.

The smoke test launches the actual first-run setup in an isolated `LOCALAPPDATA`, confirms runtime activation and application imports, renders a fixture using the packaged Remotion browser, and verifies that a second setup reuses the healthy install without downloads. It is a CPU first-run smoke test; it does not prove CUDA inference on every physical NVIDIA GPU.

For the PowerShell module-path regression, the native Rust launcher removes inherited `PSModulePath` before launching Windows PowerShell 5.1. The smoke-test process helper performs the same isolation and preflights `Get-FileHash` and `ConvertFrom-Json` before setup. Do not replace this process-boundary fix with broad environment resets or a switch to PowerShell 7 without repeating the compatibility tests.

The v0.2.3 implementation passed the documented CI and manual Windows checks. The promotion sequence for this accepted installer baseline is `windows-installer-hardening` → `windows-installer-release` → `main`; record each merge commit and its post-merge validation here when completed.
