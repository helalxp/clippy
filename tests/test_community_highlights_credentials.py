import pytest

from community_highlights.credentials import (
    SERVICE_NAME,
    CredentialStoreError,
    WindowsCredentialStore,
)


class WinVaultKeyring:
    __module__ = "keyring.backends.Windows"
    priority = 5

    def __init__(self):
        self.values = {}

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        del self.values[(service, username)]


class FakeKeyring:
    def __init__(self, backend=None):
        self.backend = backend or WinVaultKeyring()

    def get_keyring(self):
        return self.backend

    def set_password(self, *args):
        self.backend.set_password(*args)

    def get_password(self, *args):
        return self.backend.get_password(*args)

    def delete_password(self, *args):
        self.backend.delete_password(*args)


def test_windows_credential_store_round_trips_provider_credentials():
    keyring = FakeKeyring()
    store = WindowsCredentialStore(keyring_module=keyring, platform_name="win32")
    bundle = {"access_token": "test-access", "refresh_token": "test-refresh"}

    store.save("twitch", bundle)

    assert store.load("twitch") == bundle
    assert keyring.backend.values[ (SERVICE_NAME, "twitch") ]


def test_provider_credentials_are_stored_under_separate_targets():
    keyring = FakeKeyring()
    store = WindowsCredentialStore(keyring_module=keyring, platform_name="win32")
    store.save("twitch", {"access_token": "twitch-token"})
    store.save("youtube", {"access_token": "youtube-token"})

    assert store.load("twitch") == {"access_token": "twitch-token"}
    assert store.load("youtube") == {"access_token": "youtube-token"}


def test_store_refuses_non_windows_platforms():
    with pytest.raises(CredentialStoreError, match="require Windows Credential Manager"):
        WindowsCredentialStore(keyring_module=FakeKeyring(), platform_name="linux")


def test_store_fails_closed_when_keyring_selects_a_non_windows_backend():
    class PlaintextKeyring:
        __module__ = "keyring.backends.fail"
        priority = 1

    with pytest.raises(CredentialStoreError, match="will not be stored using a fallback"):
        WindowsCredentialStore(
            keyring_module=FakeKeyring(PlaintextKeyring()),
            platform_name="win32",
        )


def test_store_rejects_unknown_provider_and_invalid_bundle():
    store = WindowsCredentialStore(keyring_module=FakeKeyring(), platform_name="win32")

    with pytest.raises(CredentialStoreError, match="Unsupported"):
        store.save("google", {"access_token": "token"})
    with pytest.raises(CredentialStoreError, match="bundle is invalid"):
        store.save("twitch", {})


def test_store_rejects_malformed_saved_json():
    keyring = FakeKeyring()
    store = WindowsCredentialStore(keyring_module=keyring, platform_name="win32")
    keyring.set_password(SERVICE_NAME, "twitch", "{not-json")

    with pytest.raises(CredentialStoreError, match="saved provider credentials are invalid"):
        store.load("twitch")
