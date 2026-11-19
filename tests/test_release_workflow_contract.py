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
        "checkout_ref": "          ref: \${{ github.ref }}",
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
