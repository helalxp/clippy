import sys
import types

import pytest

from community_highlights.streamlink_capture import (
    ResolvedLiveStream,
    StreamResolutionError,
    resolve_live_stream,
)


class FakeStream:
    def __init__(self):
        self.opened = False

    def open(self):
        self.opened = True
        return "stream-reader"


class FakeSession:
    def __init__(self):
        self.options = {}
        self.requested_url = None
        self.stream = FakeStream()

    def set_option(self, key, value):
        self.options[key] = value

    def streams(self, url):
        self.requested_url = url
        return {"best": self.stream, "720p": self.stream}


def test_resolves_twitch_with_canonical_url_and_retains_session():
    session = FakeSession()
    result = resolve_live_stream(
        "https://user:password@www.twitch.tv/SomeChannel?token=not-forwarded#fragment",
        session_factory=lambda: session,
    )
    assert isinstance(result, ResolvedLiveStream)
    assert session.requested_url == "https://www.twitch.tv/somechannel"
    assert session.options["stream-timeout"] == 30
    assert result.open() == "stream-reader"
    assert session.stream.opened is True


def test_resolves_youtube_video_to_canonical_url():
    session = FakeSession()
    resolve_live_stream(
        "https://www.youtube.com/watch?v=abcdefghijk&list=private-playlist",
        session_factory=lambda: session,
    )
    assert session.requested_url == "https://www.youtube.com/watch?v=abcdefghijk"


def test_rejects_quality_names_outside_supported_contract():
    with pytest.raises(StreamResolutionError, match="supported stream quality"):
        resolve_live_stream(
            "https://twitch.tv/channel",
            quality="best;rm -rf",
            session_factory=FakeSession,
        )


def test_reports_missing_requested_quality():
    with pytest.raises(StreamResolutionError, match="not available"):
        resolve_live_stream(
            "https://twitch.tv/channel",
            quality="1080p",
            session_factory=FakeSession,
        )


def test_reports_empty_provider_stream_list():
    class EmptySession(FakeSession):
        def streams(self, url):
            return {}

    with pytest.raises(StreamResolutionError, match="No playable"):
        resolve_live_stream(
            "https://twitch.tv/channel",
            session_factory=EmptySession,
        )


def test_uses_installed_streamlink_python_api(monkeypatch):
    session = FakeSession()
    fake_module = types.ModuleType("streamlink")
    fake_module.Streamlink = lambda: session
    monkeypatch.setitem(sys.modules, "streamlink", fake_module)

    result = resolve_live_stream("https://twitch.tv/channel")
    assert result.session is session


def test_missing_streamlink_dependency_has_actionable_error(monkeypatch):
    monkeypatch.delitem(sys.modules, "streamlink", raising=False)

    def missing_import(name, *args, **kwargs):
        if name == "streamlink":
            raise ImportError("not installed")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", missing_import)
    with pytest.raises(StreamResolutionError, match="requires the Streamlink"):
        resolve_live_stream("https://twitch.tv/channel")
