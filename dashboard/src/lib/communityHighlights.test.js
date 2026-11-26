import assert from "node:assert/strict";
import test from "node:test";

import {
  communityHighlightsGeminiHeaders,
  isCommunityHighlightsProviderConnected,
  isCommunityHighlightsSessionActive,
  parseCommunityHighlightsStreamUrl,
} from "./communityHighlights.js";

test("parses Twitch channel URLs and normalizes provider identity", () => {
  assert.deepEqual(
    parseCommunityHighlightsStreamUrl("https://www.twitch.tv/Some_Channel"),
    { provider: "twitch", streamId: "some_channel" },
  );
  assert.deepEqual(
    parseCommunityHighlightsStreamUrl("https://m.twitch.tv/Some_Channel"),
    { provider: "twitch", streamId: "some_channel" },
  );
});

test("parses supported YouTube live, watch, shorts, embed, and short URLs", () => {
  for (const url of [
    "https://www.youtube.com/live/abcdefghijk",
    "https://youtube.com/watch?v=abcdefghijk",
    "https://m.youtube.com/shorts/abcdefghijk",
    "https://youtube.com/embed/abcdefghijk",
    "https://youtu.be/abcdefghijk",
  ]) {
    assert.deepEqual(
      parseCommunityHighlightsStreamUrl(url),
      { provider: "youtube", streamId: "abcdefghijk" },
      url,
    );
  }
});

test("rejects unsupported or malformed stream URLs", () => {
  for (const url of [
    "",
    "not a URL",
    "file:///C:/video.mp4",
    "https://example.com/live",
    "https://www.twitch.tv/directory",
    "https://www.twitch.tv/channel/extra",
    "https://www.youtube.com/playlist?list=abcdefghijk",
    "https://www.youtube.com/watch?v=short",
  ]) {
    assert.equal(parseCommunityHighlightsStreamUrl(url), null, url);
  }
});

test("requires the provider matching the entered stream URL to be connected", () => {
  const twitch = parseCommunityHighlightsStreamUrl("https://www.twitch.tv/my_channel");
  const youtube = parseCommunityHighlightsStreamUrl("https://youtu.be/abcdefghijk");

  assert.equal(isCommunityHighlightsProviderConnected(twitch, null), false);
  assert.equal(isCommunityHighlightsProviderConnected(twitch, undefined), false);
  assert.equal(isCommunityHighlightsProviderConnected(null, { twitch: { connected: true } }), false);
  assert.equal(
    isCommunityHighlightsProviderConnected(twitch, { youtube: { connected: true } }),
    false,
  );
  assert.equal(
    isCommunityHighlightsProviderConnected(twitch, { twitch: { connected: true } }),
    true,
  );
  assert.equal(
    isCommunityHighlightsProviderConnected(youtube, { youtube: { connected: true } }),
    true,
  );
});

test("builds the Gemini BYOK header for candidate generation when a key is saved", () => {
  assert.deepEqual(communityHighlightsGeminiHeaders("AIza-test-key"), {
    "X-Gemini-Key": "AIza-test-key",
  });
  assert.deepEqual(communityHighlightsGeminiHeaders(""), {});
  assert.deepEqual(communityHighlightsGeminiHeaders(undefined), {});
});


test("treats interrupted and other terminal sessions as inactive", () => {
  for (const status of ["stopped", "ended", "error", "interrupted"]) {
    assert.equal(isCommunityHighlightsSessionActive({ status }), false, status);
  }

  for (const status of ["starting", "connecting", "connected", "reconnecting", "recording", "stopping"]) {
    assert.equal(isCommunityHighlightsSessionActive({ status }), true, status);
  }

  assert.equal(isCommunityHighlightsSessionActive(null), false);
  assert.equal(isCommunityHighlightsSessionActive(undefined), false);
});
