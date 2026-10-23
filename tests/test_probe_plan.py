"""Duration-probe proxy ordering: cheapest bandwidth first.

The probe runs on every managed YouTube submission. It read PROXY_URL only
until 21-aug-2026, so it kept paying the per-GB proxy for metadata long after
downloads had moved to the flat-rate static pool — invisibly, because the
PROXY_BYTES counter only sees download bytes.
"""
import pytest

metering = pytest.importorskip("cloud.metering")

plan = metering.plan_probe_proxies

STATICS = ["http://s1", "http://s2", "http://s3"]
PAID = "http://paid"


class TestOrdering:
    def test_full_chain(self):
        assert plan(True, STATICS, PAID) == [None] + STATICS + [PAID]

    def test_paid_is_last_resort(self):
        got = plan(False, STATICS, PAID)
        assert got == STATICS + [PAID]
        assert got.index(PAID) == len(got) - 1

    def test_statics_only_never_reaches_a_paid_proxy(self):
        assert plan(False, STATICS, "") == STATICS

    def test_selfhost_no_proxies_probes_direct(self):
        assert plan(False, [], "") == [None]
        assert plan(True, [], "") == [None]

    def test_no_statics_matches_legacy_paid_only_behavior(self):
        assert plan(False, [], PAID) == [PAID]


class TestDirectFileProbe:
    """yt-dlp's generic extractor reports no duration for a plain mp4 URL; the
    probe must fall back to ffprobe over HTTP instead of 400-ing the job."""

    def test_generic_extractor_falls_back_to_ffprobe(self, monkeypatch):
        import types, sys, security_utils
        monkeypatch.setattr(security_utils, "assert_public_url", lambda u: u)
        class _YDL:
            def __init__(self, opts): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def extract_info(self, url, download=False):
                return {"extractor": "generic", "duration": None}
        monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=_YDL))
        monkeypatch.setattr(metering, "_ffprobe_url_seconds", lambda url, timeout=30: 559.4)
        assert abs(metering.probe_url_minutes("https://cdn.example.com/v.mp4") - 559.4 / 60) < 1e-6

    def test_both_fail_raises(self, monkeypatch):
        import types, sys, security_utils
        monkeypatch.setattr(security_utils, "assert_public_url", lambda u: u)
        class _YDL:
            def __init__(self, opts): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def extract_info(self, url, download=False):
                raise RuntimeError("Unsupported URL")
        monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=_YDL))
        def boom(url, timeout=30): raise RuntimeError("no moov")
        monkeypatch.setattr(metering, "_ffprobe_url_seconds", boom)
        with pytest.raises(ValueError):
            metering.probe_url_minutes("https://cdn.example.com/v.mp4")


class TestStaticsBotCheckedVerdict:
    """When every static answers the bot-check and the paid proxy answers the
    video, the probe leaves a one-shot verdict for the download to skip the
    statics (main.plan_download_attempts skip_statics)."""

    def _fake_ydl(self, monkeypatch, paid):
        import types, sys, security_utils
        monkeypatch.setattr(security_utils, "assert_public_url", lambda u: u)
        class _YDL:
            def __init__(self, opts): self.proxy = opts.get("proxy")
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def extract_info(self_, url, download=False):
                if self_.proxy == paid:
                    return {"extractor": "youtube", "duration": 600}
                raise RuntimeError("ERROR: [youtube] x: Sign in to confirm you're not a bot.")
        monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=_YDL))

    def test_verdict_is_left_once_and_popped(self, monkeypatch):
        monkeypatch.setenv("STATIC_PROXY_URLS", "http://s1,http://s2")
        monkeypatch.setenv("PROXY_URL", "http://paid")
        monkeypatch.delenv("DIRECT_FIRST", raising=False)
        monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
        self._fake_ydl(monkeypatch, "http://paid")
        metering._static_bot_verdicts.clear()
        metering.pop_paid_probe_events()
        url = "https://www.youtube.com/watch?v=eWpDO6w362Q"
        assert metering.probe_url_minutes(url) == 10.0
        assert metering.pop_statics_bot_checked(url) is True
        assert metering.pop_statics_bot_checked(url) is False
        assert metering.pop_paid_probe_events()  # the paid probe is still recorded

    def test_no_verdict_when_a_static_failed_for_another_reason(self, monkeypatch):
        monkeypatch.setenv("STATIC_PROXY_URLS", "http://s1")
        monkeypatch.setenv("PROXY_URL", "http://paid")
        monkeypatch.delenv("DIRECT_FIRST", raising=False)
        monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
        import types, sys, security_utils
        monkeypatch.setattr(security_utils, "assert_public_url", lambda u: u)
        class _YDL:
            def __init__(self, opts): self.proxy = opts.get("proxy")
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def extract_info(self_, url, download=False):
                if self_.proxy == "http://paid":
                    return {"extractor": "youtube", "duration": 600}
                raise RuntimeError("HTTP Error 429: Too Many Requests")
        monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=_YDL))
        metering._static_bot_verdicts.clear()
        url = "https://www.youtube.com/watch?v=abcdefghijk"
        assert metering.probe_url_minutes(url) == 10.0
        assert metering.pop_statics_bot_checked(url) is False
        metering.pop_paid_probe_events()
