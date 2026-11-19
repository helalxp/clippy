# Clippy v1 Third-Party Licence and Distribution Inventory

> **Status:** Phase 1 preliminary inventory; not a legal opinion or a release approval.  
> **Inspected source baseline:** `61edcd5027e3f4e05c8019896e25af0e1cfa19f3` (`v0.3.1`).  
> **Last inspected:** 2026-11-19.

## 1. Purpose

Clippy is intended to ship as a Windows desktop application, including a managed runtime, renderer, browser, media tools, AI dependencies, and downloadable model weights. The legal review must therefore cover the exact components and binaries conveyed to customers, not merely the root repository licence.

This inventory separates:
- **Source licences** for code retained in the repository.
- **Binary/runtime licences** for executables and native libraries shipped or downloaded by Clippy.
- **Model licences** for weights bundled with the installer or downloaded later.
- **Font and asset licences** for embedded media/resources.
- **Provenance and source availability** for each redistributed component.

A package name, upstream project licence badge, or a successful build does not establish distribution compliance. Before release, generate an SBOM and retain the exact component versions, hashes, source references, licence texts and corresponding-source obligations for the actual packaged artifact.

## 2. Root project and inherited source

### 2.1 Root MIT code

The root `LICENSE` is MIT and carries the 2024 OpenShorts copyright notice. The `NOTICE` file identifies the core application as MIT-licensed.

The core MIT notice must remain and the Clippy distribution must retain applicable upstream attribution/copyright notices. Product rebranding does not erase the upstream copyright or MIT notice requirement.

### 2.2 Separate `cloud/` licence

The root `NOTICE` explicitly excludes the `cloud/` tree from the root MIT licence. `cloud/LICENSE` is the OpenShorts Commercial License, not an MIT licence.

That commercial licence allows personal/internal business use and prohibits (without a separate written agreement) offering the cloud code or derivative as a hosted/managed/paid service, selling it, or redistributing it as part of another product or service for consideration.

The current native desktop payload preparation copies root Python modules, `requirements.txt`, selected assets/directories, renderer and Remotion files. It does not copy the `cloud/` directory or `requirements-billing.txt`. The native supervisor does not set `BILLING_ENABLED`; the backend imports the cloud package only when that flag is active.

**Required treatment:** keep `cloud/` out of the Clippy v1 desktop payload and separate its local backend callers before deleting cloud code from the repository. Do not infer that repository removal retires an external service, customer account, database, object store or legal retention obligation. See the separate hosted-service retirement preflight.

## 3. Critical or high-priority licence decisions

| Component | Current source/runtime use | Licence evidence | Priority | Required decision/action |
|---|---|---|---|---|
| Ultralytics YOLO `8.4.46` | In-process import in `main.py`; constructs a YOLO model and uses person detection as a fallback in the reframing path. The default weight reference is `yolov8n.pt`. | The exact upstream `v8.4.46` `LICENSE` file is GNU AGPLv3. Ultralytics' current licensing guidance says use of YOLO code/models requires either releasing the entire project under AGPL-3.0 or obtaining an Ultralytics Enterprise licence for proprietary/customer-facing commercial products. | **CRITICAL — release blocker** | Choose one: (a) obtain written Enterprise licensing covering Clippy's desktop distribution and the model use; (b) deliberately relicense the complete distributed project under AGPLv3 after a full compatibility review; or (c) replace the Ultralytics code and model with a commercially compatible person-detection solution, preserving and validating the fallback behavior. Do not simply remove the detector: it is part of current reframing behavior. |
| FFmpeg Gyan Windows essentials static build | `desktop/setup-runtime.ps1` downloads `ffmpeg-release-essentials.zip` and a checksum sidecar from the Gyan builds host. | Gyan states its Windows static builds are GPLv3. The essentials build includes GPL libraries such as libx264 and libx265. FFmpeg's legal guidance explains that GPL-enabled builds are subject to GPL rather than the default LGPL-only configuration. | **HIGH — compliance and reproducibility blocker** | Pin the exact FFmpeg release, source commit, build configuration, archive URL and SHA-256. Retain the exact GPL licence and required corresponding-source/build-provenance information for the binary conveyed. Obtain legal review of the separate-executable distribution boundary; do not claim that FFmpeg automatically relicenses Clippy's Python code. |
| bgutil PO-token provider `1.3.2` | Python plugin is pinned in `requirements.txt`; `desktop/prepare-payload.ps1` also clones its server repository at tag `1.3.2`, builds it and copies its build output, production `node_modules` and `package.json` into the app payload. | PyPI identifies release `1.3.2` as GPLv3. The exact repository tag's `LICENSE` is also GNU GPLv3. | **HIGH — source/notice gap** | Pin the immutable upstream commit as well as the tag. Determine the full corresponding source for both the Python plugin and Node server payload. Preserve the GPLv3 licence and make corresponding source available as required. The current payload script does not explicitly copy the upstream licence or Node server source before removing the clone. Obtain legal review of how the separately packaged components interact with the rest of the product. |
| NVIDIA CUDA runtime libraries | The CUDA runtime is delivered inside the Windows Python runtime built from the PyTorch CUDA 12.8 wheel index. The build script explicitly checks for `cublas64_12.dll`, `cudnn64_9.dll`, and `cudart64_12.dll` under `torch\\lib`. | CUDA Toolkit EULA Attachment A governs which CUDA files may be redistributed. cuDNN has a separate NVIDIA SDK licence and its own distributable runtime-file provisions. | **HIGH — exact binary inventory required** | Inventory every NVIDIA DLL and package in the actual CUDA runtime archive. Match each component to the applicable CUDA/cuDNN version, redistributable list, EULA, notices and any distribution conditions. Do not infer that the CUDA EULA automatically covers cuDNN or every transitive DLL. Keep CPU and CUDA SBOMs distinct. |

### 3.1 Ultralytics model-cache location is also a data-integrity issue

The current source loads `YOLO(os.environ.get("YOLO_MODEL_PATH", "yolov8n.pt"))`. The pinned Ultralytics code defaults on Windows to a user roaming-profile configuration directory unless `YOLO_CONFIG_DIR` is supplied. The Tauri supervisor currently sets neither `YOLO_CONFIG_DIR` nor `YOLO_MODEL_PATH`.

Consequently the YOLO configuration/weight cache can live outside Clippy's managed `data/models` directory and outside the existing data-folder relocation contract.

Do not migrate or redirect this cache until the Ultralytics licensing decision is resolved. If YOLO remains, Phase 2/5 must:
- Inventory the current actual config and weight paths.
- Set an explicit Clippy-managed model/config directory.
- Migrate existing weights safely without discarding a user-downloaded file or creating unnecessary duplicate downloads.
- Preserve the current person-detection fallback and add regression coverage.

## 4. Rendering, browser, and runtime components

| Component | Current pinned/current use | Licence/provenance status | Action |
|---|---|---|---|
| Remotion packages | Renderer and Remotion source packages are pinned to `4.0.447`; the dashboard references `^4.0.447`. | The upstream `v4.0.447` tag contains a `LICENSE.md` with a free licence for individuals and organisations/teams up to three people, and a company licence outside that eligibility. The current Remotion online FAQ explains eligibility and automation in more detail; it must not be confused with a different package version's licence text. | Confirm who owns/operates Clippy and the total applicable headcount. If above the free-tier limit, obtain the required company licence. If the exact embedded desktop distribution use is unclear, get written confirmation from Remotion. Keep the exact v4.0.447 licence in the compliance bundle. |
| Chrome for Testing headless shell | `chrome-headless-shell-win64.zip` for version `144.0.7559.20` is downloaded from Google's Chrome for Testing storage endpoint; archive and executable hashes are recorded in `desktop/runtime-contract.json`. | The Chrome for Testing availability repository's Apache-2.0 licence applies to its repository work; it must not be assumed to be the complete licence for the browser binary. Chrome for Testing documents the headless-shell artifact separately. The actual downloaded archive must be inspected for its Chromium licence and third-party notices. | Preserve the exact browser archive and executable hashes. Inspect the exact archive contents and include its browser licence and all bundled third-party notices in Clippy's distribution notices. Do not use the availability-repository Apache licence as a substitute for the binary's component notices. |
| FFmpeg/FFprobe | Gyan essentials static build (see Section 3). | GPLv3 per Gyan's build page; exact runtime version is not currently pinned by the app. | Pin source/build/hash and include corresponding compliance materials. |
| CPython | Embedded CPython `3.12.10` runtime, built from the official embeddable archive; the build script pins its archive SHA-256. | Python Software Foundation licence and archive notices must accompany the redistributable runtime. | Include the Python licence and third-party notices associated with the exact embedded runtime. Verify the actual runtime archive contents. |
| Node.js | Private managed Node.js `22.23.3` runtime, downloaded from the official Node distribution and checked against its official `SHASUMS256.txt`. | Node.js licence and bundled third-party notices must accompany the runtime. | Include the Node.js licence/third-party notices for the exact version and archive. |
| Microsoft Visual C++ Redistributable | Setup downloads the x64 VC++ redistributable from Microsoft when the required runtime is missing. | Microsoft redistributable terms and the official signed binary apply. This is a separate first-run prerequisite, not a Clippy-authored runtime library. | Retain the Microsoft distribution terms/link and validate the download/signature/integrity path. Do not repackage or modify the redistributable. |

### 4.1 FFmpeg reproducibility finding

The runtime contract currently identifies only the provider family `gyan-release-essentials`. Setup downloads the moving `ffmpeg-release-essentials.zip` URL and then downloads the matching checksum sidecar from the same moving location.

The Gyan builds page currently lists release 9.0.2 and a corresponding FFmpeg source commit, but this does **not** prove every existing Clippy installation contains that exact binary: setup/repair uses the moving URL. The runtime contract must eventually record the exact FFmpeg version, archive hash, source commit/build settings and licence bundle. The download must resolve to that immutable artifact for a given Clippy runtime contract.

Gyan's page also notes that its static builds are GPLv3, and the essentials build includes x264/x265. FFmpeg's upstream legal page explains the distinction between the default LGPL framework and builds configured with GPL parts.

## 5. Python packages and model weights

This is a source-level first pass, not a complete transitive dependency report.

| Dependency/artifact | Version/source currently visible | Licence/provenance finding | Notes |
|---|---|---|---|
| `torch` / `torchvision` | `2.11.0` / `0.26.0`; CPU or CUDA 12.8 wheel index | PyTorch uses a BSD-style licence with third-party components; CUDA builds additionally include NVIDIA runtime libraries and their separate terms. | Generate separate CPU and CUDA SBOMs and capture the exact wheel/component set from the final runtime artifacts. |
| `mediapipe` | `0.10.14` | Apache-2.0 upstream project licence. | Include Apache licence and required notices for the exact distribution and bundled dependencies. |
| `faster-whisper` | `1.2.1` | MIT upstream licence. | Transitive CTranslate2, PyAV and native dependencies still need SBOM coverage. |
| PyAV | `18.1.0` pinned to preserve the currently validated faster-whisper decode API | Must be included in the Python SBOM with its own licence and binary provenance. | The version pin is also an API compatibility constraint; do not loosen without decoder regression tests. |
| `transnetv2-pytorch` | `1.0.5` | MIT upstream project licence. | Include exact source and model/weight provenance. |
| `yt-dlp[default]` | PyPI dependency | yt-dlp project is Unlicense. | Clippy installs the Python package from PyPI; do not substitute a different standalone executable distribution without reviewing its licence and contents. |
| Whisper model catalog | Systran faster-whisper models; Large-v3 Turbo conversion from `mobiuslabsgmbh` | The inspected repositories declare MIT. These weights are downloaded by the in-app model manager and are not bundled in the core installer. | Record repository, immutable revision/commit, file hashes and licence per supported catalog entry. Validate model file provenance before activation; do not silently change the selected model. |
| Ultralytics `yolov8n.pt` | Default weight reference resolved by Ultralytics when YOLO is first instantiated | Ultralytics states that YOLO trained models are AGPL by default unless covered by a commercial licence. | Covered by the critical decision in Section 3; not approved for commercial redistribution/use by this inventory alone. |

The full Python requirements also include scene detection, Google GenAI, image/media, FastAPI and support libraries. Every direct and transitive wheel in the final CPU and CUDA runtime must be included in the machine-generated SBOM and notices, not inferred from this shortlist.

## 6. Fonts and visual assets

| Asset | Current repository path | Licence evidence | Required packaging |
|---|---|---|---|
| Montserrat | `fonts/Montserrat-ExtraBold.ttf` | SIL Open Font Licence 1.1; `fonts/Montserrat-OFL.txt` already exists. | Keep its copyright notice and full OFL text in the packaged notices. |
| Anton | `fonts/Anton-Regular.ttf` | Google Fonts metadata identifies OFL; upstream `ofl/anton/OFL.txt` contains the SIL OFL 1.1 text and copyright attribution for the Anton Project Authors. | Add the exact licence/copyright notice to the third-party notice bundle. The current tracked `fonts/` directory did not contain an Anton-specific OFL file at the inspected baseline. |
| Noto Serif | `fonts/NotoSerif-Bold.ttf` | Google Fonts metadata identifies OFL; upstream `ofl/notoserif/OFL.txt` contains the SIL OFL 1.1 text and Noto Project Authors attribution. | Add the exact licence/copyright notice to the third-party notice bundle. The current tracked `fonts/` directory did not contain a Noto Serif OFL file at the inspected baseline. |

The SIL OFL permits fonts to be embedded and redistributed with software when the licence and copyright notice are included. It does not permit selling the font software by itself; modified fonts also have reserved-name restrictions.

Do not remove the fonts simply because their licence files are missing from the current directory. The source licences have now been identified; the required action is to bundle each licence correctly.

## 7. SBOM and corresponding-source deliverables

Before a commercial release, produce and retain the following for the exact release candidate and published artifact:

1. **SBOMs:** machine-generated inventories for the application payload, CPU runtime, CUDA runtime, renderer/Remotion dependencies, Rust/Tauri, browser, FFmpeg and external redistributables. Include direct and transitive package names, versions, package identifiers, source URLs, hashes, and licence expressions.
2. **Third-party notices:** a human-readable `THIRD_PARTY_NOTICES` bundle included with the installed application and accessible to users. Include MIT, Apache-2.0, BSD-family, OFL, Python, Node, browser, CUDA/cuDNN and other required notice texts.
3. **GPL source packages:** preserve the exact corresponding source and build inputs required for the FFmpeg and bgutil versions actually conveyed. Record where users can obtain that source; include any required build scripts/configuration and licence text. Confirm with counsel which separation/distribution obligations apply to the actual package arrangement.
4. **Model provenance:** record the exact catalog repository/revision/file hashes and licence for each model the user can download. Model selection must remain explicit and deterministic.
5. **Binary provenance:** record the official source/download URL, publisher, exact version, architecture, SHA-256, signing/publisher validation (where available), licence, and bundled third-party component notices for every redistributable executable/runtime.
6. **Release traceability:** associate the SBOM, notices, source archives and build provenance with the exact Git commit, Clippy version, runtime contract, release tag and installer hash.

### Components that still require artifact-level inspection

The following cannot be certified from `requirements.txt` or a package name alone:
- Exact Python wheel/transitive component set and metadata for the generated CPU and CUDA runtime archives.
- Every NVIDIA DLL copied into the CUDA runtime, its package source, exact CUDA/cuDNN version, and whether it is included in the applicable redistribution list.
- The actual Chrome Headless Shell archive's included license and third-party notice files.
- Every production npm package from both renderer and Remotion lockfiles.
- Every Rust crate and any bundled native library.
- The exact Gyan FFmpeg binary and linked-library build configuration actually present on installed machines.
- The source and licence for any assets in addition to the fonts listed above.

## 8. Evidence links

The following upstream sources were checked during this Phase 1 inventory:

- [Ultralytics licensing guidance](https://www.ultralytics.com/license) and [Ultralytics terms, YOLO model licence clause](https://www.ultralytics.com/legal/terms-of-service).
- [Ultralytics source licence at v8.4.46](https://github.com/ultralytics/ultralytics/blob/v8.4.46/LICENSE).
- [Remotion source licence at v4.0.447](https://github.com/remotion-dev/remotion/blob/v4.0.447/LICENSE.md) and [Remotion licence FAQ](https://www.remotion.dev/docs/license/faq).
- [Gyan FFmpeg Windows builds and libraries](https://www.gyan.dev/ffmpeg/builds/) and [FFmpeg legal considerations](https://www.ffmpeg.org/legal.html).
- [FFmpeg 9.0.2 source release](https://ffmpeg.org/download.html). The current Gyan page identifies a release source commit; Clippy's moving download URL is not yet pinned to that commit.
- [bgutil PyPI 1.3.2 licence/provenance](https://pypi.org/project/bgutil-ytdlp-pot-provider/1.3.2/) and [bgutil upstream GPL licence](https://github.com/Brainicism/bgutil-ytdlp-pot-provider/blob/1.3.2/LICENSE).
- [NVIDIA CUDA 12.8 EULA](https://docs.nvidia.com/cuda/archive/12.8.0/eula/index.html) and [CUDA redistribution FAQ](https://developer.nvidia.com/cuda/faq).
- [NVIDIA cuDNN SDK licence](https://docs.nvidia.com/cudnn/reference/eula/) and [cuDNN Windows package/manifest documentation](https://docs.nvidia.com/deeplearning/cudnn/installation/windows.html).
- [Chrome Headless Shell documentation](https://developer.chrome.com/docs/automation-and-testing/headless-chrome-shell) and [Chrome for Testing availability repository](https://github.com/GoogleChromeLabs/chrome-for-testing).
- [Anton OFL source](https://github.com/google/fonts/blob/main/ofl/anton/OFL.txt) and [Noto Serif OFL source](https://github.com/google/fonts/blob/main/ofl/notoserif/OFL.txt).
- [Montserrat OFL project](https://github.com/JulietaUla/Montserrat).

## 9. Decisions needed before Phase 1 can close

1. **Ultralytics:** should Clippy obtain an Enterprise licence for the existing YOLO detector, or should the team replace the Ultralytics code/model with a commercially compatible person-detection alternative? Treating the whole product as AGPL is a third legal route but requires an explicit project-wide licensing decision, not a dependency-level switch.
2. **Remotion operator eligibility:** is the entity/team that owns and distributes Clippy an individual, a non-profit, or a for-profit organisation with three or fewer people, or does it exceed that threshold? The pinned v4.0.447 licence text and current official FAQ both make the applicable organisation/headcount relevant. If the embedded product arrangement is ambiguous, obtain written confirmation from Remotion.
3. **Hosted OpenShorts retirement:** does any hosted OpenShorts service still operate with external users/accounts/subscriptions, OAuth grants, databases, or S3/R2 objects, or is the cloud code only present in this public repository with no live external data? See the hosted-service retirement preflight before removing infrastructure.

**Phase 1 status:** preliminary source and licence inventory complete; distribution clearance is not complete. Do not ship a new commercial build or remove the affected components until the above decisions and artifact-level inspections are resolved.
