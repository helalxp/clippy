import assert from "node:assert/strict";
import test from "node:test";

import { parseCommunityHighlightsStreamUrl } from "./communityHighlights.js";

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
