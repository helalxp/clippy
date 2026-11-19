"""Contracts for the GitHub Actions release workflow."""

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-windows.yml"


def test_release_signing_job_checks_out_tagged_source_before_running_validator():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    lines = workflow.splitlines()

    try:
        job_start = lines.index("  validate-signing:")
    except ValueError as exc:
        raise AssertionError("Release workflow is missing the validate-signing job.") from exc

    job_end = next(
        (
            index
            for index in range(job_start + 1, len(lines))
            if re.match(r"^  [A-Za-z0-9_-]+:$", lines[index])
        ),
        len(lines),
    )
    job_lines = lines[job_start:job_end]

    required_lines = {
        "checkout_name": "      - name: Check out tagged source",
        "checkout_action": "        uses: actions/checkout@v4",
        "checkout_ref": "          ref: ${{ github.ref }}",
        "validator_name": "      - name: Validate configured updater public key",
        "validator_command": '        run: node desktop/validate-updater-signing-key.mjs "$RUNNER_TEMP/clippy-updater.pub"',
    }
    positions = {}
    for key, expected_line in required_lines.items():
        try:
            positions[key] = job_lines.index(expected_line)
        except ValueError as exc:
            raise AssertionError(
                f"validate-signing must contain the required source-checkout/validator line: {expected_line}"
            ) from exc

    assert positions["checkout_name"] < positions["checkout_action"] < positions["checkout_ref"]
    assert positions["checkout_ref"] < positions["validator_name"] < positions["validator_command"], (
        "The tagged repository must be checked out before the updater-key validator reads files."
    )

def test_release_signing_job_decodes_tauri_signature_before_minisign_verification():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    lines = workflow.splitlines()

    try:
        job_start = lines.index("  validate-signing:")
    except ValueError as exc:
        raise AssertionError("Release workflow is missing the validate-signing job.") from exc

    job_end = next(
        (
            index
            for index in range(job_start + 1, len(lines))
            if re.match(r"^  [A-Za-z0-9_-]+:$", lines[index])
        ),
        len(lines),
    )
    job_lines = lines[job_start:job_end]

    required_lines = {
        "signature_temp_file": '          minisign_signature="$(mktemp "$RUNNER_TEMP/clippy-updater-signature.XXXXXX")"',
        "cleanup": """          trap 'rm -f "$probe" "$probe.sig" "$minisign_signature" "$public_key"' EXIT""",
        "decode": '          base64 --decode "$probe.sig" > "$minisign_signature"',
        "decoded_signature_check": '          test -s "$minisign_signature"',
        "verify_decoded_signature": '          minisign -Vm "$probe" -p "$public_key" -x "$minisign_signature"',
    }
    positions = {}
    for key, expected_line in required_lines.items():
        try:
            positions[key] = job_lines.index(expected_line)
        except ValueError as exc:
            raise AssertionError(
                f"validate-signing must contain the required decoded-signature handling line: {expected_line}"
            ) from exc

    assert positions["signature_temp_file"] < positions["cleanup"]
    assert positions["cleanup"] < positions["decode"] < positions["decoded_signature_check"]
    assert positions["decoded_signature_check"] < positions["verify_decoded_signature"], (
        "Minisign must verify the decoded signature document emitted by Tauri."
    )
    assert '          minisign -Vm "$probe" -p "$public_key" -x "$probe.sig"' not in job_lines, (
        "Do not pass Tauri's outer Base64 .sig representation directly to Minisign."
    )

def test_application_version_is_synchronized_across_all_build_manifests():
    import json

    canonical = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    tauri = json.loads((REPO_ROOT / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    cargo_toml = (REPO_ROOT / "desktop/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    cargo_lock = (REPO_ROOT / "desktop/src-tauri/Cargo.lock").read_text(encoding="utf-8")
    dashboard = json.loads((REPO_ROOT / "dashboard/package.json").read_text(encoding="utf-8"))
    dashboard_lock = json.loads((REPO_ROOT / "dashboard/package-lock.json").read_text(encoding="utf-8"))

    package_section = re.search(r"(?ms)^\[package\]\s*\n(.*?)(?=^\[|\Z)", cargo_toml)
    assert package_section, "Cargo.toml is missing its [package] section."
    cargo_version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', package_section.group(1))
    assert cargo_version, "Cargo.toml is missing its package version."

    cargo_lock_version = re.search(
        r'(?ms)^\[\[package\]\]\s*\nname = "clippy-desktop"\s*\nversion = "([^"]+)"',
        cargo_lock,
    )
    assert cargo_lock_version, "Cargo.lock is missing the clippy-desktop package entry."

    versions = {
        "Tauri": tauri["version"],
        "Cargo.toml": cargo_version.group(1),
        "Cargo.lock": cargo_lock_version.group(1),
        "dashboard package.json": dashboard["version"],
        "dashboard package-lock.json": dashboard_lock["version"],
        "dashboard package-lock root package": dashboard_lock["packages"][""]["version"],
    }
    assert all(value == canonical for value in versions.values()), (
        f"Application version mismatch. VERSION={canonical}; other manifests={versions}"
    )


def test_in_app_updater_remains_on_the_stable_release_channel():
    import json

    config = json.loads((REPO_ROOT / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    endpoints = config["plugins"]["updater"]["endpoints"]
    assert endpoints == [
        "https://github.com/helalxp/clippy/releases/latest/download/latest.json"
    ], "The public updater must continue to consume the latest stable release only."

    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "prerelease: ${{ contains(github.ref_name, '-') }}" in workflow
    assert "make_latest: ${{ !contains(github.ref_name, '-') }}" in workflow
    assert '--draft=false --prerelease' in workflow
    assert '--draft=false --latest' in workflow
