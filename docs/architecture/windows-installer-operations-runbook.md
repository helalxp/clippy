# Windows installer operations and troubleshooting

**Applies to:** Clippy native Windows installer, first-run runtime setup, and GitHub Release delivery.  
**Verified baseline:** v0.2.3, 2026-11-17.

## Fast entry points

- [Current Windows release](https://github.com/helalxp/clippy/releases/tag/v0.2.3)
- [Release workflow](https://github.com/helalxp/clippy/actions/runs/44066693854)
- [Windows desktop validation](https://github.com/helalxp/clippy/actions/runs/44062955499)
- [Desktop guide](../../desktop/README.md)
- [Release procedure](../../RELEASING.md)
- [First-run setup contract](../../desktop/FIRST_RUN_SETUP_CONTRACT.md)
- [Runtime asset contract](windows-release-versioning-and-runtime-asset-contract.md)

## Branches and promotion

`main` is the single authoritative branch. The former hardening and release integration branches completed the v0.2.3 installer migration and are not ongoing development lanes.

For subsequent work, create a short-lived feature/fix branch from the latest `main`, open a pull request back to `main`, and run the checks relevant to the changed subsystem on the exact PR head. Installer/runtime changes require Windows desktop validation and packaged setup/render checks. Keep Whisper model-selection changes isolated from installer lifecycle work.

The previous Whisper/runtime PR #13 was closed without merging. Its `windows-installer-module-path-fix` head is not an accepted implementation. The next model-selection investigation must start from current `main` with a new, narrowly scoped branch and regression tests; do not reuse or cherry-pick the superseded patch series by default. Model weights remain outside the core installer runtime package and are managed separately.
## Completed v0.2.3 promotion

The verified v0.2.3 installer is now part of `main`.

- [PR #14](https://github.com/helalxp/clippy/pull/14) merged `windows-installer-hardening` into `windows-installer-release` at `b2086ea27b9237c0a85d0638a24952336b77fcc7`.
- [PR #3](https://github.com/helalxp/clippy/pull/3) merged `windows-installer-release` into `main` at `e238e92c599c7f34357d2093db0b95dae102a7e4`.
- [Windows validation run #368](https://github.com/helalxp/clippy/actions/runs/44086793620) passed all Windows validation jobs on integration head `6873f5dcc101f8af804481d2434cdf05900e95a5`, including CPU and CUDA runtime packages and the NSIS installer build.
- [General PR CI](https://github.com/helalxp/clippy/actions/runs/44086795898) passed backend tests and frontend build on that same head.
- [Main CI after merge](https://github.com/helalxp/clippy/actions/runs/44090057236) passed on merge commit `e238e92c599c7f34357d2093db0b95dae102a7e4`.
- The follow-up repository-audit refresh at `0062eaf12e8d2ff0e22c67cd9cfa8f4d64ad1a49` was documentation-only and [main CI passed](https://github.com/helalxp/clippy/actions/runs/44090278204).

The `v0.2.3` release tag was not moved during either merge. The manually observed
Whisper model-selection hiccup remains separate and unresolved; do not change
the validated installer/runtime code to address it without a focused diagnosis
and its own regression test.

## What the release smoke test proves

`desktop/smoke-test-runtime.ps1` is an end-to-end integration gate, not just a syntax or unit test. It:

1. Verifies the app payload and CPU runtime archive against their SHA-256 sidecars and checks the runtime manifest/version/variant.
2. Extracts the exact application ZIP produced for the installer into an isolated temporary per-user app-data root.
3. Launches the actual packaged `setup-runtime.ps1` with Windows PowerShell 5.1 and a local CPU runtime archive override.
4. Checks that the managed Python, Node.js, FFmpeg, Remotion browser, and runtime manifest were installed and marked healthy.
5. Imports the packaged backend using the managed interpreter and runs lightweight executable checks.
6. Creates a video fixture and runs the packaged Remotion render path with the persistent headless browser.
7. Runs setup a second time without the local Python archive and confirms the healthy install is reused without downloads.

The release workflow also validates both CPU and CUDA runtime packages and runs the Rust tests. The hosted smoke test intentionally forces the CPU path; it is not a physical-GPU CUDA inference test.

## Resolved incident: Get-FileHash missing in first-run setup

### Symptom

The release smoke test failed after extracting the packaged payload and launching first-run setup:

```text
The term 'Get-FileHash' is not recognized as the name of a cmdlet
...
setup-runtime.ps1:330
```

The same failure recurred on a second release attempt. Runtime archive builds, payload construction, and Pester contract tests had passed, but first-run setup stopped before installing the managed runtimes.

### Root cause

The smoke-test host was PowerShell 7 (`pwsh.exe`) and it launched the product's intentional Windows PowerShell 5.1 child process (`powershell.exe`). The child inherited the parent's `PSModulePath`, which can point at PowerShell 7 module directories. The Windows PowerShell 5.1 child could then fail to auto-load its own compatible shared modules, making standard commands such as `Get-FileHash` unavailable.

This is a process-environment compatibility issue, not a broken SHA-256 implementation, Python runtime archive, CUDA package, or missing release asset.

### Permanent fix

- In `desktop/src-tauri/src/lib.rs`, the native launcher uses `.env_remove("PSModulePath")` for the Windows PowerShell 5.1 process. With that variable absent, Windows PowerShell reconstructs its own compatible module search path.
- In `desktop/smoke-test-runtime.ps1`, the helper removes the inherited variable around each `Start-Process powershell.exe` launch and restores the parent value afterward.
- Before expensive setup, the smoke test launches a small PowerShell 5.1 probe that checks `PSEdition`, version, `PSModulePath`, and command providers for `Get-FileHash` and `ConvertFrom-Json`. A failure reports the probe output immediately.

Do not "fix" this by changing the product to PowerShell 7, removing all environment variables, or replacing each hash call independently. Those options either change the supported runtime host or hide the underlying process boundary problem.

### Regression checks when changing this code

1. Confirm `desktop/src-tauri/src/lib.rs` still removes `PSModulePath` before spawning `powershell.exe`.
2. Confirm smoke-test setup and second-run launches both use the sanitized helper.
3. Confirm the probe checks Windows PowerShell Desktop edition and major version 5, and resolves `Get-FileHash` and `ConvertFrom-Json`.
4. Run `windows-desktop-validation.yml`.
5. Run the tag-based release workflow on a candidate release commit and inspect the smoke-test output. Do not publish until every release step passes.

## Resolved incident: bgutil YouTube provider timeout

**Symptom:** yt-dlp initialization fails while the bgutil script plugin runs
`generate_once.js --version`; on Windows the upstream plugin's fixed 15-second
check can expire during Node cold start.

**Permanent desktop fix:** the managed Python runtime retains the shared and
HTTP bgutil plugin modules but excludes `getpot_bgutil_script.py`. The native
supervisor starts the pinned bgutil HTTP server as a supervised child, verifies
its `/ping` response/version, and passes `BGUTIL_BASE_URL` only after the
health check succeeds. The packaged HTTP plugin is also gated on an explicit
`base_url` argument, so when Clippy starts in degraded mode it does not fall
back to the upstream default port `4416` or talk to an unrelated local process.
If the optional server cannot start, Clippy still starts without the PO-token
provider rather than blocking unrelated features.

**Security constraint:** upstream bgutil 1.3.2 listens on wildcard interfaces.
The payload builder replaces that listener with an IPv4 `127.0.0.1` binding
and fails closed if the expected source block changes. Keep the compiled
payload assertion and clean-install server smoke test. Never package this
unauthenticated endpoint on `0.0.0.0` or `::`.

The provider log is
`%LOCALAPPDATA%\\Clippy\\logs\\bgutil-provider.log`. Re-run Windows desktop
validation and the clean first-run smoke test after changing the package,
listener patch, or supervisor lifecycle.

## Where to find logs

The primary per-user setup log is:

```text
%LOCALAPPDATA%\Clippy\logs\runtime-setup.log
```

Collect that file together with any native desktop logs in the same directory. Record the application version, Windows version, machine architecture, GPU and driver details when relevant, and the failing setup stage.

Do not delete `%LOCALAPPDATA%\Clippy` to clear an error. It contains user settings, uploads, generated videos, caches, and model weights. Investigate the specific failed component and preserve user data.

## Release asset contract

For version `X.Y.Z`, setup downloads only from:

```text
https://github.com/helalxp/clippy/releases/download/vX.Y.Z/
```

Required assets follow these names:

- `clippy-python-cpu.manifest.json` and its listed CPU archive asset(s).
- `clippy-python-cuda.manifest.json` and its listed CUDA part asset(s).
- The matching `*.parts.sha256` metadata files.
- The NSIS installer and its `*.sha256` sidecar.

The manifest is authoritative for the original archive name, size, whole-archive SHA-256, ordered part names, part sizes and part hashes. Each part must be verified before concatenation; the reconstructed archive must be verified before extraction. A missing asset is a release publication issue and should be reported as an explicit HTTP 404, not hidden by retries.

## Safe release recovery

- A failed tag workflow is not a successful release. Inspect the first failed step and its full job log before changing code.
- If the run fails before the draft is published, correct the source and rerun the validation ladder. Only deliberately retarget an unpublished tag when reusing the same version is justified.
- Never force-move a published tag. Use a new version for a correction to a published release.
- A draft release must contain every expected asset with the exact locally built size before it is made public.
- After publication, verify the release page, installer checksum, CPU/CUDA manifests, and every listed part.
- Keep CI proof and a short real-machine test record with the release documentation.

## v0.2.3 verified record

The v0.2.3 release workflow and Windows validation workflow both passed on commit
`9454c5eb485cc75c0ee14a00d11bd405d9a320aa`. The release includes 10 assets.
The installer was manually installed and exercised through the editing
workflow. A Whisper model-selection hiccup remains a separate follow-up and
must not be marked fixed by this installer milestone.
