# In-App Updater Feature Implementation Plan

**Status:** Proposed implementation plan  
**Target branch:** `feature/in-app-updater-plan`  
**Base branch:** `main`  
**Base commit:** `30e7686de84612446562799376e8e2c4649864ac`  
**Current application baseline:** Clippy `0.3.0`  
**Scope:** Windows x64 desktop application updates, with a deliberately separate follow-up for component-level runtime updates.

---

## 1. Executive decision

Implement the first in-app updater with the official **Tauri 2 updater plugin** and Clippy's existing GitHub Releases distribution.

The first milestone will update the installed Clippy application through a signed NSIS installer update. It will not attempt binary-delta patching or independently update Python, PyTorch/CUDA, Node, FFmpeg, Remotion, or browser components.

A second milestone will introduce a signed component manifest and independently versioned component packages. That work must build on the current runtime setup and health-check contracts rather than being mixed into the first updater release.

**Important correction to keep the design precise:** Tauri 2's current updater artifact format for a Windows NSIS build with `bundle.createUpdaterArtifacts: true` produces the NSIS installer and its `.sig` signature file. The `"v1Compatible"` mode produces a ZIP wrapper. Clippy is a Tauri 2 application, so the plan is to use the current v2 artifact mode, not assume a ZIP updater payload.

## 2. Repository baseline verified for this plan

The plan was prepared against the GitHub `main` branch at `30e7686de84612446562799376e8e2c4649864ac`.

Verified repository facts:

- `desktop/src-tauri/tauri.conf.json` declares Tauri configuration schema 2, application version `0.3.0`, NSIS as the only bundle target, and embeds `resources/app-payload.zip` plus its SHA-256 sidecar.
- `desktop/src-tauri/Cargo.toml` uses Tauri 2 and currently has no `tauri-plugin-updater` dependency.
- The inspected Tauri configuration has no updater public key, endpoint, or `createUpdaterArtifacts` setting.
- The inspected Rust dependency list has no updater plugin.
- The current Windows release workflow is tag-triggered (`v*`), builds and validates the application payload and CPU/CUDA Python runtime assets, builds the NSIS installer, generates its SHA-256 sidecar, and publishes a draft before verifying and publishing it.
- The release workflow currently treats Windows Authenticode signing as optional when neither certificate secret is configured. Authenticode signing and Tauri updater signing are separate mechanisms.
- `desktop/INSTALLER_UPDATE_ARCHITECTURE.md` already specifies two update layers: a Tauri desktop/application update and a future signed component updater.
- `desktop/setup-runtime.ps1` uses `%LOCALAPPDATA%\\Clippy`, a runtime contract, a runtime manifest, separate runtime/data/download locations, installation mutexes, and integrity checks. The Remotion browser is explicitly stored outside the replaceable `app/current` payload.
- The current bootstrap validation reads the runtime manifest and validates installed runtime executables, app/runtime contract consistency, backend dependencies, and the persistent browser.

These facts provide a strong starting point, but they do **not** by themselves prove that every runtime package is reused after every application update. That must be verified against the complete setup/reconciliation path and through an actual Windows upgrade test before we claim it.

## 3. Goals

1. Let a user check for, review, download, and install a Clippy update without manually visiting GitHub Releases.
2. Keep update packages cryptographically authenticated before installation.
3. Preserve the existing Windows NSIS installation model.
4. Preserve user data, settings, generated videos, downloads, models, logs, and configured external storage.
5. Avoid downloading or reinstalling unchanged managed runtimes during an ordinary application update.
6. Make update state visible: checking, available, downloading, ready to install, installing/restarting, up to date, deferred, and failed.
7. Make the release workflow fail clearly when a production updater artifact cannot be signed or verified.
8. Keep the implementation testable and recoverable, with no silent success claims.

## 4. Non-goals for the first milestone

- No binary-delta patch format.
- No custom updater service or mandatory hosted backend.
- No independent Python/PyTorch/CUDA/Node/FFmpeg/Remotion/browser component update engine.
- No automatic forced installation while a render or other critical job is active.
- No removal or replacement of the existing installer/runtime bootstrap system.
- No change to video processing, clip generation, rendering, or output formats.
- No automatic update of model weights.
- No Linux or macOS updater support unless those platforms become supported release targets.

## 5. Target user experience

Add an **Settings → Updates** section with:

- Installed version.
- Last checked time.
- A **Check for updates** action.
- Available version and release notes.
- Download size when the release metadata can provide a reliable value.
- Download progress and actionable error messages.
- **Install and restart** when the update is downloaded and verified.
- **Remind me later** / defer behavior.
- A setting for automatic update checks, enabled by default only if it can be implemented without interrupting active work.

A small, non-blocking update indicator may appear elsewhere in the application. Do not make a blocking modal the only way to discover or manage updates.

The frontend should use the official Tauri updater API through the installed plugin package. It must not independently trust a release URL or bypass Tauri signature validation.

## 6. Proposed architecture

### 6.1 Update discovery and trust

- Use Tauri 2's official `tauri-plugin-updater` crate and matching frontend package.
- Configure a static GitHub Releases endpoint for the public repository, using the documented `latest.json` format.
- Embed the generated Tauri updater public key in `tauri.conf.json`.
- Keep the private signing key outside the repository and outside source-controlled files.
- Store the private key and optional password as protected GitHub Actions secrets for release builds.
- Keep the existing installer SHA-256 sidecar as an additional distribution/integrity aid. It is not a substitute for Tauri's updater signature.
- Keep Windows Authenticode signing separate. Do not treat an Authenticode certificate as the Tauri updater key.

Tauri requires signed updater artifacts. The production updater must fail closed if signing material is missing, the signature file is absent, or the published manifest does not match the generated artifact.

### 6.2 Update installation

- Use the official plugin's check, download, progress, install, and relaunch flow.
- Configure the Windows installer mode deliberately. Start with the documented passive mode unless testing shows it conflicts with Clippy's per-user install or process lifecycle.
- Respect Tauri's signed-update verification.
- Prevent two Clippy instances or an updater and runtime repair/setup operation from modifying the same installation simultaneously.
- Do not terminate an active render or destructive operation without an explicit safe policy. If Clippy has active jobs, defer installation and explain why.
- Ensure backend/renderer child processes shut down cleanly before the installer replaces application files.
- Keep the previous/manual installer route documented as recovery if an update cannot complete.

### 6.3 Runtime and user-data preservation

The updater must not treat the entire `%LOCALAPPDATA%\\Clippy` directory as disposable.

Before implementation, trace the exact setup path after a new application payload is activated. In particular, verify how `runtime-manifest.json`, runtime contract hashes, Python variant selection, Node, FFmpeg, browser version/hash, configured data storage, and repair behavior interact.

Required behavior:

- Unchanged valid runtime components are reused.
- A changed or invalid component is repaired only when the runtime contract requires it.
- The browser remains in its persistent location and is not downloaded again when its version and hash are still valid.
- Models, uploads, generated outputs, reference templates, settings, and external data directories remain untouched.
- If an application release requires a runtime change, show the additional download/repair requirement before proceeding where feasible.

Do not claim that all runtime packages are preserved until a Windows upgrade test demonstrates it.

## 7. Implementation phases

### Phase 0 — Close design and release prerequisites

1. Trace the complete startup, update, installer, and runtime setup lifecycles.
2. Identify the exact files and processes that are replaced by the NSIS updater.
3. Confirm whether the existing setup script reuses each unchanged runtime component or downloads/rebuilds it.
4. Inspect the current Tauri capabilities file and Rust plugin registration point.
5. Inspect dashboard routing/settings conventions and existing notification/progress components.
6. Confirm the release workflow can safely create and publish the Tauri manifest and signature assets.
7. Generate the updater signing key locally using the Tauri CLI, with a strong password.
8. Back up the private key and password in the owner's secure password manager/offline recovery location.
9. Add only the private key and password to GitHub Actions secrets. Never commit, upload as an ordinary release asset, or print the private key in logs.
10. Add the public key to the application configuration only after the key has been generated and securely backed up.

**Exit criteria:** The update lifecycle is mapped, the key is safely backed up, and the owner has confirmed that CI secrets are configured.

### Phase 1 — Native Tauri updater integration

Likely files to change (confirm exact paths during implementation):

- `desktop/src-tauri/Cargo.toml`
- `desktop/src-tauri/Cargo.lock`
- `desktop/src-tauri/tauri.conf.json`
- `desktop/src-tauri/src/lib.rs` (or the actual plugin registration entry point)
- `desktop/src-tauri/capabilities/default.json`
- `dashboard/package.json`
- `dashboard/package-lock.json`

Tasks:

1. Add a compatible Tauri 2 updater plugin version, matching the repository's Tauri dependency family.
2. Register the plugin in the Rust application builder.
3. Add the matching JavaScript package.
4. Grant only the updater permissions required by the frontend.
5. Configure `createUpdaterArtifacts: true`, the real public key, and the HTTPS GitHub Releases endpoint.
6. Configure Windows install mode explicitly.
7. Keep the configuration free of test-only insecure HTTP options.
8. Add focused Rust/frontend tests for registration, permission, and update-state handling where the current architecture permits.

**Exit criteria:** A signed local/CI build produces the expected Windows updater artifacts, and an installed test build can query a valid test manifest.

### Phase 2 — Release pipeline and manifest publication

Update `.github/workflows/release-windows.yml` to:

1. Provide the Tauri private signing key and optional password to the build process through GitHub Actions secrets.
2. Build the normal NSIS installer and updater artifacts.
3. Require the expected `.sig` output; fail if missing or empty.
4. Generate or publish a valid Tauri static update manifest containing:
   - semantic version;
   - release notes;
   - RFC 3339 publication date;
   - `windows-x86_64` platform entry;
   - signed artifact URL;
   - exact signature contents.
5. Upload the installer, updater signature, manifest, existing SHA-256 sidecar, and runtime assets to the draft release.
6. Verify the draft release contains every expected asset and that asset sizes match the locally built outputs.
7. Validate the manifest structure, version, URL, and signature before publishing the release.
8. Publish only after all checks pass.

The existing optional Authenticode behavior remains independent. The Tauri updater signing path is mandatory for releases intended to be discoverable by the in-app updater.

**Important release sequencing:** Do not repoint the public `latest.json` endpoint to a release until its installer, signature, and manifest have all been uploaded and verified.

**Exit criteria:** A draft release can be built and validated without publication; a deliberately missing signing secret causes a clear failure; a valid signed release publishes a usable manifest.

### Phase 3 — Frontend update experience

Add an update service/hook and a Settings → Updates view using existing frontend conventions.

Tasks:

1. Query the installed version from the desktop runtime.
2. Check for updates manually and, if enabled, periodically with a conservative interval.
3. Present available version and release notes.
4. Show download progress and meaningful errors.
5. Allow the user to defer installation.
6. Install only after explicit user confirmation.
7. Coordinate restart and explain that the application will close.
8. Handle offline, no-update, malformed manifest, signature rejection, download interruption, and installation errors.
9. Avoid repeated prompts for an update the user has deferred.
10. Keep the interface usable if the updater is unavailable in a development/browser-only environment.

**Exit criteria:** The update view covers all normal and failure states, and the user can complete a test update without opening a browser or terminal.

### Phase 4 — Lifecycle safety and recovery

1. Determine how the desktop process owns and stops backend/renderer child processes.
2. Block or defer update installation while a render, export, download, or runtime setup/repair operation is in a critical section.
3. Reuse or extend existing installation mutex behavior rather than creating competing lock names without a clear ownership model.
4. Ensure a failed update leaves a diagnosable log and a supported manual recovery route.
5. Confirm the next launch detects incomplete runtime setup and can resume or repair safely.
6. Confirm updater installation does not delete user data or the previous known-good application payload prematurely.

**Exit criteria:** Interrupted, deferred, failed, and retried updates have deterministic behavior.

### Phase 5 — End-to-end Windows validation

Test on clean Windows 10/11 x64 VMs or equivalent isolated machines:

- Fresh installation of the updater-enabled release.
- Upgrade from the currently published `0.3.0` installation.
- Upgrade when CPU runtime is installed.
- Upgrade when CUDA runtime is installed.
- Update when the Remotion browser is already installed.
- Update with a custom external data directory.
- Update with generated videos, models, uploads, settings, and reference templates present.
- No-update response.
- Offline check.
- Interrupted download and retry.
- Invalid signature.
- Missing signature.
- Invalid/malformed manifest.
- Downgrade or same-version manifest.
- Disk-full / permission failure.
- Active render or runtime setup while an update is requested.
- Restart after successful install.
- Runtime setup after update, proving unchanged components are reused.
- Application startup, backend health, renderer/browser launch, and representative render after update.

Capture installed component versions, hashes, download sizes, and logs before and after. Compare them to prove that unchanged components were not downloaded again.

**Exit criteria:** All required upgrade and preservation tests pass on Windows, and the release workflow has verified artifacts before publication.

## 8. Milestone 2 — Signed component-level updater (separate feature/PR)

Do not include this in the first Tauri updater implementation.

Build a separate signed component manifest with independent component identities and versions for:

- application payload/backend source;
- frontend assets;
- Python runtime/dependency set;
- CPU or CUDA PyTorch runtime set;
- Node runtime;
- renderer/Remotion dependencies;
- FFmpeg;
- Remotion browser.

Each component entry should carry a schema/version, compatibility constraints, archive URL, compressed size, installed size where measurable, SHA-256, and publisher signature metadata.

The component updater should:

1. Authenticate the manifest before trusting URLs or versions.
2. Compare installed component identities and hashes.
3. Download only missing or changed components.
4. Support resumable downloads.
5. Verify archives before extraction.
6. Reject path traversal, symlinks/reparse points where unsupported, unexpected files, and archive expansion abuse.
7. Extract into new versioned directories.
8. Run component health checks and representative smoke tests.
9. Switch the active component set atomically only after validation.
10. Keep the previous known-good set for rollback.
11. Preserve user data and model directories.
12. Recover from interruption, power loss, disk-full, and failed activation.
13. Report total download size before applying the update.

The current runtime directory layout is not yet the full immutable versioned layout described in the architecture document. Designing and migrating that layout requires its own audit and tests.

Do not implement binary deltas initially. Independently downloadable, signed component archives with a full-package fallback are simpler to validate and recover.

## 9. Security requirements

- Tauri updater signature verification is mandatory.
- Private signing key and password never enter Git, source artifacts, release assets, or logs.
- Public key is embedded in the shipped application configuration.
- HTTPS only for production update endpoints.
- Manifest and signature must correspond to the exact release artifact and version.
- No frontend-controlled arbitrary installer URL.
- No unsigned fallback or bypass.
- Existing SHA-256 verification remains in place for runtime assets.
- Release workflow uses least-privilege GitHub token permissions.
- Do not log secrets or sensitive local paths.
- Keep an owner-controlled, tested backup of the updater signing key. Losing the private key prevents signing future updates trusted by existing installations.

## 10. Risks and decisions to resolve before coding

| Risk / question | Required resolution |
|---|---|
| Existing v0.3.0 users have no updater plugin/public key | They must manually install the first updater-enabled release once |
| Tauri updater replaces the NSIS-installed application bundle | Verify exact install behavior with Clippy's per-user install and child-process lifecycle |
| Application payload is embedded in the installer | First updater downloads the full installer, not a binary delta |
| Runtime reuse is contract-driven | Prove setup script reuse with real upgrade tests |
| Signing key loss | Secure backup and recovery test before enabling production updates |
| Missing CI signing secret | Production updater build must fail closed |
| Active jobs during update | Defer installation until safe |
| GitHub release draft/manifest publication ordering | Verify assets and manifest before making the release latest |
| Runtime changes may be required by an app release | Show and validate those requirements; keep component updater out of milestone 1 |
| Existing release workflow builds CPU and CUDA assets | Preserve current validation/publication behavior while adding updater assets |

## 11. Definition of done for milestone 1

Milestone 1 is complete only when:

- [ ] A signed updater-enabled Windows release is published.
- [ ] A clean installation can discover a newer release.
- [ ] An existing v0.3.0 installation can be upgraded in-app after the one-time manual bootstrap release.
- [ ] Update download and installation progress are visible.
- [ ] Invalid signatures/manifests are rejected.
- [ ] Missing CI signing secrets prevent a production updater release.
- [ ] User data, settings, outputs, models, and configured storage survive.
- [ ] Existing valid runtime components are reused, demonstrated by logs and before/after hashes.
- [ ] Backend, renderer, browser, and representative video rendering work after the update.
- [ ] Failure and recovery behavior is tested.
- [ ] Documentation describes the update behavior and manual recovery path.
- [ ] No claim of delta updates or independent component updates is made until milestone 2 exists.

## 12. Working method

- Work only on `feature/in-app-updater-plan` for this feature.
- Keep this plan updated as implementation decisions change.
- Inspect before editing; do not patch blindly.
- Make focused commits with explanatory messages.
- Run relevant Rust, frontend, PowerShell/Pester, release-contract, and Windows integration tests.
- Do not publish a production release until signing, upgrade, runtime reuse, and data-preservation gates pass.
- Report evidence, remaining risks, and exact next steps after each implementation phase.

## 13. References

Repository documents and implementation:

- `desktop/INSTALLER_UPDATE_ARCHITECTURE.md`
- `desktop/src-tauri/tauri.conf.json`
- `desktop/src-tauri/Cargo.toml`
- `desktop/src-tauri/src/bootstrap.rs`
- `desktop/src-tauri/src/installation.rs`
- `desktop/setup-runtime.ps1`
- `.github/workflows/release-windows.yml`

Official Tauri documentation:

- [Tauri 2 Updater plugin](https://v2.tauri.app/plugin/updater/)
- [Tauri updater source documentation](https://github.com/tauri-apps/tauri-docs/blob/v2/src/content/docs/plugin/updater.mdx)

