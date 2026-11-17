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

```text
windows-installer-hardening -> windows-installer-release -> main
```

The hardening branch is where installer/runtime changes are developed and validated. The release branch is the integration point. Main receives the accepted integration state. Use pull requests for both merges and rerun the Windows validation workflow after merging into the release branch. A tag must come from the accepted, validated release commit.

Do not include unrelated Whisper/model-selection changes in an installer promotion unless they have their own review and tests. Model weights are outside the installer runtime package and are downloaded/selected separately.

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
