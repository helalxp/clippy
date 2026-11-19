"""Secure storage for Community Highlights provider credentials.

The desktop app must use Windows Credential Manager. This module deliberately
fails closed elsewhere and refuses keyring's fallback backends.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Mapping


SERVICE_NAME = "Clippy Community Highlights"
SUPPORTED_PROVIDERS = frozenset({"twitch", "youtube"})


class CredentialStoreError(RuntimeError):
    """Raised when secure provider credential storage is unavailable."""


class WindowsCredentialStore:
    """Store provider token bundles in the current Windows user's Credential Manager."""

    def __init__(self, *, keyring_module: Any | None = None, platform_name: str | None = None):
        current_platform = platform_name if platform_name is not None else sys.platform
        if current_platform != "win32":
            raise CredentialStoreError(
                "Community Highlights credentials require Windows Credential Manager."
            )

        try:
            if keyring_module is None:
                # Instantiate the Windows Vault backend explicitly. Do not let
                # a user keyringrc.cfg redirect provider tokens to another store.
                from keyring.backends.Windows import WinVaultKeyring

                backend = WinVaultKeyring()
            else:
                backend = keyring_module.get_keyring()
            backend_type = type(backend)
            is_windows_vault = (
                backend_type.__name__ == "WinVaultKeyring"
                and backend_type.__module__ == "keyring.backends.Windows"
                and getattr(backend, "priority", 0) > 0
            )
        except Exception:
            is_windows_vault = False
            backend = None

        if not is_windows_vault:
            raise CredentialStoreError(
                "Clippy could not initialize Windows Credential Manager. "
                "Credentials will not be stored using a fallback."
            )
        self._backend = backend

    @staticmethod
    def _validate_provider(provider: str) -> str:
        if provider not in SUPPORTED_PROVIDERS:
            raise CredentialStoreError("Unsupported Community Highlights provider.")
        return provider

    @staticmethod
    def _encode_bundle(bundle: Mapping[str, Any]) -> str:
        if not isinstance(bundle, Mapping) or not bundle:
            raise CredentialStoreError("The provider credential bundle is invalid.")
        try:
            return json.dumps(dict(bundle), ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            raise CredentialStoreError("The provider credential bundle is invalid.") from None

    def save(self, provider: str, bundle: Mapping[str, Any]) -> None:
        provider = self._validate_provider(provider)
        encoded = self._encode_bundle(bundle)
        try:
            self._backend.set_password(SERVICE_NAME, provider, encoded)
        except Exception:
            # Never echo keyring exceptions: backend errors may contain target
            # metadata, and token values must never enter application logs.
            raise CredentialStoreError(
                "Windows Credential Manager could not save the provider credentials."
            ) from None

    def load(self, provider: str) -> dict[str, Any] | None:
        provider = self._validate_provider(provider)
        try:
            encoded = self._backend.get_password(SERVICE_NAME, provider)
        except Exception:
            raise CredentialStoreError(
                "Windows Credential Manager could not read the provider credentials."
            ) from None
        if encoded is None:
            return None
        try:
            bundle = json.loads(encoded)
        except (TypeError, ValueError):
            raise CredentialStoreError(
                "The saved provider credentials are invalid. Disconnect and sign in again."
            ) from None
        if not isinstance(bundle, dict) or not bundle:
            raise CredentialStoreError(
                "The saved provider credentials are invalid. Disconnect and sign in again."
            )
        return bundle

    def delete(self, provider: str) -> None:
        provider = self._validate_provider(provider)
        try:
            self._backend.delete_password(SERVICE_NAME, provider)
        except Exception as error:
            # Deleting an absent credential is idempotent. Other failures remain
            # visible, but the underlying exception is intentionally redacted.
            error_type = type(error)
            if error_type.__name__ == "PasswordDeleteError":
                return
            raise CredentialStoreError(
                "Windows Credential Manager could not remove the provider credentials."
            ) from None
