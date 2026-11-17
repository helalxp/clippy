import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));

/** Resolve the shared media directory used by both FastAPI and this service. */
export function resolveOutputDirectory(
  configured = process.env.OUTPUT_DIR,
  cwd = process.cwd(),
): string {
  const candidate = configured?.trim()
    ? configured
    : path.resolve(cwd, "..", "output");
  return path.resolve(cwd, candidate);
}

/** Resolve the Remotion source tree without relying on Node 20-only import.meta.dirname. */
export function resolveRemotionRoot(
  configured = process.env.REMOTION_BUNDLE_PATH,
): string {
  return path.resolve(configured?.trim() || path.resolve(MODULE_DIR, "../../remotion"));
}

export function resolveListenHost(value = process.env.HOST || process.env.RENDER_HOST): string {
  // Local desktop installs should not expose the render API to the LAN.
  // Docker deployments explicitly set HOST=0.0.0.0 in compose.
  return value?.trim() || "127.0.0.1";
}

export function resolveRendererPublicUrl(
  port: number,
  host = resolveListenHost(),
  configured = process.env.RENDERER_PUBLIC_URL,
): string {
  if (configured?.trim()) return configured.trim().replace(/\/$/, "");
  const browserHost = host === "0.0.0.0" || host === "::" ? "127.0.0.1" : host;
  return `http://${browserHost}:${port}`;
}

function safePathSegments(rawPath: string): string[] | null {
  const segments = rawPath.split("/").filter(Boolean);
  if (segments.length < 2) return null;
  const decoded: string[] = [];
  for (const segment of segments) {
    let value: string;
    try {
      value = decodeURIComponent(segment);
    } catch {
      return null;
    }
    if (!value || value === "." || value === ".." || /[\\/\0]/.test(value)) {
      return null;
    }
    decoded.push(value);
  }
  return decoded;
}

/**
 * Remotion runs in its own Node process and must fetch source media over HTTP.
 * The backend's /videos/<job>/<file> route maps to the same shared OUTPUT_DIR.
 */
export function resolveRendererVideoUrl(
  input: string,
  publicUrl: string,
  accessToken?: string,
): string {
  let parsed: URL;
  try {
    parsed = new URL(input, "http://clippy.local");
  } catch {
    return input;
  }

  const match = parsed.pathname.match(/^\/(?:videos|output)\/(.+)$/);
  if (!match) return input;
  const segments = safePathSegments(match[1]);
  if (!segments) throw new Error("Invalid video path supplied to renderer");

  const target = new URL(`/output/${segments.map(encodeURIComponent).join("/")}`, `${publicUrl}/`);
  target.search = parsed.search;
  // Remotion Chromium fetches source media directly; scope its URL to this launch.
  if (accessToken) target.searchParams.set("token", accessToken);
  return target.toString();
}

/** Create and validate the shared output directory before accepting render jobs. */
export function ensureOutputDirectory(directory: string): void {
  fs.mkdirSync(directory, { recursive: true });
  const stat = fs.statSync(directory);
  if (!stat.isDirectory()) {
    throw new Error(`OUTPUT_DIR is not a directory: ${directory}`);
  }
  fs.accessSync(directory, fs.constants.R_OK | fs.constants.W_OK);
}

/** Resolve a job output folder while preventing job IDs from escaping OUTPUT_DIR. */
export function resolveJobOutputDirectory(outputDir: string, jobId: string): string {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(jobId)) {
    throw new Error("Invalid render job ID");
  }
  const resolved = path.resolve(outputDir, jobId);
  const relative = path.relative(outputDir, resolved);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("Render job output path is outside OUTPUT_DIR");
  }
  return resolved;
}
