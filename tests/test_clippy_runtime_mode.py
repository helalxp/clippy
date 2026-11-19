"""Regression tests for the local-only desktop process boundary."""
import ast
from pathlib import Path

from clippy_runtime_mode import (
    HOSTED_ENV_DENYLIST,
    billing_enabled,
    configure_desktop_environment,
)


def test_desktop_mode_forces_billing_off_and_removes_hosted_configuration():
    env = {
        "CLIPPY_DESKTOP_MODE": "1",
        "BILLING_ENABLED": "true",
        "AWS_ACCESS_KEY_ID": "aws-key",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "AWS_REGION": "eu-west-3",
        "AWS_S3_BUCKET": "hosted-bucket",
        "STRIPE_SECRET_KEY": "stripe-secret",
        "DATABASE_URL": "postgres://hosted",
        "R2_ACCESS_KEY_ID": "r2-key",
        "R2_SECRET_ACCESS_KEY": "r2-secret",
        "GOOGLE_CLIENT_SECRET": "oauth-secret",
        "GEMINI_API_KEY": "user-provider-key",
        "CLIPPY_DATA_DIR": "C:/Users/test/Clippy/data",
    }

    configure_desktop_environment(env)

    assert env["BILLING_ENABLED"] == "0"
    assert billing_enabled(env) is False
    for name in HOSTED_ENV_DENYLIST:
        assert name not in env
    assert env["GEMINI_API_KEY"] == "user-provider-key"
    assert env["CLIPPY_DATA_DIR"] == "C:/Users/test/Clippy/data"


def test_desktop_mode_cannot_be_overridden_by_stale_billing_flag():
    env = {"CLIPPY_DESKTOP_MODE": "true", "BILLING_ENABLED": "yes"}
    assert billing_enabled(env) is False


def test_non_desktop_mode_preserves_existing_hosted_mode_semantics():
    env = {
        "BILLING_ENABLED": "true",
        "DATABASE_URL": "postgres://hosted",
    }

    configure_desktop_environment(env)

    assert billing_enabled(env) is True
    assert env["DATABASE_URL"] == "postgres://hosted"


def test_app_does_not_import_or_invoke_the_implicit_job_artifact_uploader():
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "s3_uploader"
        for alias in node.names
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "upload_job_artifacts" not in imported
    assert "upload_job_artifacts" not in called
