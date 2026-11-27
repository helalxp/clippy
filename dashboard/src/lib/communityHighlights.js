const TWITCH_CHANNEL = /^[A-Za-z0-9_]{1,25}$/;

// Candidate approval enters the same BYOK generation endpoint as normal uploads.
// Keep the Gemini header optional for managed and local-LLM configurations.
export function communityHighlightsGeminiHeaders(apiKey) {
  return typeof apiKey === "string" && apiKey
    ? { "X-Gemini-Key": apiKey }
    : {};
}
const YOUTUBE_VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
const RESERVED_TWITCH_PATHS = new Set([
  "directory", "downloads", "jobs", "p", "settings", "turbo", "wallet",
]);

// Mirrors the backend URL shapes so the UI can gate actions for the correct
// provider before sending a request. The backend parser remains authoritative.
export function parseCommunityHighlightsStreamUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;

  let url;
  try {
    url = new URL(value.trim());
  } catch {
    return null;
  }

  if (!["http:", "https:"].includes(url.protocol)) return null;

  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  const parts = url.pathname.split("/").filter(Boolean);

  if (host === "twitch.tv" || host === "m.twitch.tv") {
    if (parts.length !== 1 || !TWITCH_CHANNEL.test(parts[0])) return null;
    if (RESERVED_TWITCH_PATHS.has(parts[0].toLowerCase())) return null;
    return { provider: "twitch", streamId: parts[0].toLowerCase() };
  }

  if (host === "youtube.com" || host === "m.youtube.com" || host === "youtu.be") {
    let videoId = null;
    if (host === "youtu.be") {
      videoId = parts.length === 1 ? parts[0] : null;
    } else if (parts[0] === "watch") {
      videoId = url.searchParams.get("v");
    } else if (["live", "shorts", "embed"].includes(parts[0]) && parts.length === 2) {
      videoId = parts[1];
    }

    if (!videoId || !YOUTUBE_VIDEO_ID.test(videoId)) return null;
    return { provider: "youtube", streamId: videoId };
  }

  return null;
}
export function isCommunityHighlightsProviderConnected(streamReference, providers) {
  if (!streamReference || !providers || typeof providers !== "object") return false;
  return providers[streamReference.provider]?.connected === true;
}

/**
 * A session can remain in durable state after its worker is gone. Keep the
 * same terminal-state policy across workflow matching and background polling.
 */
export const COMMUNITY_HIGHLIGHTS_TERMINAL_SESSION_STATES = new Set([
  "stopped",
  "ended",
  "error",
  "interrupted",
]);

export function isCommunityHighlightsSessionActive(session) {
  return Boolean(
    session
    && !COMMUNITY_HIGHLIGHTS_TERMINAL_SESSION_STATES.has(session.status)
  );
}

export function isCommunityHighlightsWorkflowActive(chatSession, captureSession) {
  return chatSession?.status === "connected" && captureSession?.status === "recording";
}

export function shouldContinueCommunityHighlightsStatusPolling(hasActiveWork, statusLoadFailed) {
  return Boolean(hasActiveWork || statusLoadFailed);
}


export function isCommunityHighlightsBufferReady(capture, preSeconds) {
  if (!capture || capture.status !== "recording" || capture.latest_segment_age_seconds == null) return false;
  const segmentSeconds = Number(capture.segment_seconds);
  const bufferedSeconds = Number(capture.buffered_seconds);
  const latestAge = Number(capture.latest_segment_age_seconds);
  const requiredSeconds = Math.max(0, Number(preSeconds) || 0) + segmentSeconds;
  const maxLatestAge = Math.max(10, segmentSeconds * 3);

  return Number.isFinite(segmentSeconds)
    && segmentSeconds > 0
    && Number.isFinite(bufferedSeconds)
    && bufferedSeconds >= requiredSeconds
    && Number.isFinite(latestAge)
    && latestAge >= 0
    && latestAge <= maxLatestAge;
}
