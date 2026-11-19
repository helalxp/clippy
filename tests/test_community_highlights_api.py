from community_highlights.api import connection_status
from community_highlights.credentials import CredentialStoreError


class FakeCredentialStore:
    def __init__(self, bundles=None):
        self.bundles = bundles or {}

    def load(self, provider):
        return self.bundles.get(provider)


def test_connection_status_reports_unavailable_storage_without_credentials():
    def unavailable_store():
        raise CredentialStoreError("storage unavailable")

    result = connection_status(unavailable_store)

    assert result["credential_storage_available"] is False
    assert set(result["providers"]) == {"twitch", "youtube"}
    for provider in result["providers"].values():
        assert provider["connected"] is False
        assert provider["authorization_available"] is False
        assert provider["status"] == "storage_unavailable"
        assert not any("token" in key or "secret" in key for key in provider)


def test_connection_status_reports_saved_credentials_without_exposing_them():
    store = FakeCredentialStore({
        "twitch": {"access_token": "never-return-this"},
    })

    result = connection_status(lambda: store)

    assert result["credential_storage_available"] is True
    assert result["providers"]["twitch"]["connected"] is True
    assert result["providers"]["twitch"]["status"] == "credentials_saved"
    assert result["providers"]["youtube"]["connected"] is False
    assert "never-return-this" not in repr(result)
    assert "access_token" not in repr(result)
