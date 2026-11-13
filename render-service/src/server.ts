import express from "express";
import { isAuthorizedToken } from "./auth.js";
import { v4 as uuidv4 } from "uuid";
import { z } from "zod";
import { initBundle } from "./bundle.js";
import { executeRender } from "./render-worker.js";
import { ensureOutputDirectory, resolveListenHost, resolveOutputDirectory, resolveRendererPublicUrl, resolveRendererVideoUrl } from "./paths.js";

// --- Render status types ---

export type RenderStatus = "queued" | "rendering" | "done" | "error";

export interface RenderJob {
  renderId: string;
  jobId: string;
  clipIndex: number;
  status: RenderStatus;
  progress: number;
  outputUrl?: string;
  error?: string;
}

// In-memory render job map
export const renderJobs = new Map<string, RenderJob>();

// --- Request validation schema ---

const renderRequestSchema = z.object({
  jobId: z.string().regex(/^[A-Za-z0-9_-]{1,128}$/),
  clipIndex: z.number().int().min(0),
  props: z.object({
    videoUrl: z.string(),
    durationInFrames: z.number().int().positive(),
    fps: z.number().positive(),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    subtitles: z.any().nullable().optional(),
    hook: z.any().nullable().optional(),
    effects: z.any().nullable().optional(),
  }),
});

// --- Express app ---

const app = express();
const DESKTOP_API_TOKEN = process.env.CLIPPY_API_TOKEN?.trim() || "";
// Desktop mode requires a per-launch secret for renderer APIs and media.
// Self-host deployments without a token retain their existing network boundary.
app.use((req, res, next) => {
  if (!DESKTOP_API_TOKEN || req.path === "/health") return next();
  const supplied = req.path.startsWith("/output/")
    ? String(req.query.token || "")
    : req.header("X-Clippy-Token") || "";
  if (!isAuthorizedToken(supplied, DESKTOP_API_TOKEN)) {
    return res.status(401).json({ error: "This local renderer requires its active desktop session token." });
  }
  next();
});
app.use(express.json({ limit: "10mb" }));

const PORT = Number.parseInt(process.env.PORT || "13100", 10);
if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) {
  throw new Error(`Invalid renderer PORT: ${process.env.PORT}`);
}
const HOST = resolveListenHost();
const OUTPUT_DIR = resolveOutputDirectory();
const RENDERER_PUBLIC_URL = resolveRendererPublicUrl(PORT, HOST);
ensureOutputDirectory(OUTPUT_DIR);
console.log(`[render-service] Shared output directory: ${OUTPUT_DIR}`);
console.log(`[render-service] Public media URL: ${RENDERER_PUBLIC_URL}/output/`);

// Remotion's browser process fetches media from this service. OUTPUT_DIR must
// be the same physical directory configured for the FastAPI backend.
app.use(
  "/output",
  express.static(OUTPUT_DIR, {
    dotfiles: "deny",
    fallthrough: false,
    index: false,
    redirect: false,
    setHeaders(res) {
      res.setHeader("Cache-Control", "no-store");
      res.setHeader("X-Content-Type-Options", "nosniff");
    },
  }),
);

// Health check
app.get("/health", (_req, res) => {
  res.json({ ok: true });
});

// Submit a render job
app.post("/render", (req, res) => {
  const parsed = renderRequestSchema.safeParse(req.body);

  if (!parsed.success) {
    res.status(400).json({
      error: "Invalid request body",
      details: parsed.error.issues,
    });
    return;
  }

  const { jobId, clipIndex, props } = parsed.data;

  // Convert backend /videos URLs to this service's shared-media endpoint.
  // Validate before creating a job so a bad path cannot leave an orphan queued job.
  let resolvedVideoUrl: string;
  try {
    resolvedVideoUrl = resolveRendererVideoUrl(props.videoUrl, RENDERER_PUBLIC_URL, DESKTOP_API_TOKEN);
  } catch (error) {
    res.status(400).json({
      error: error instanceof Error ? error.message : "Invalid video URL",
    });
    return;
  }
  if (resolvedVideoUrl !== props.videoUrl) {
    console.log(`[render] Resolved video URL: ${props.videoUrl} -> ${resolvedVideoUrl}`);
  }

  const renderId = uuidv4();
  const job: RenderJob = {
    renderId,
    jobId,
    clipIndex,
    status: "queued",
    progress: 0,
  };
  renderJobs.set(renderId, job);
  console.log(
    `[render] Queued render ${renderId} for job=${jobId} clip=${clipIndex}`
  );

  // Fire and forget - render runs in background
  executeRender({
    renderId,
    jobId,
    clipIndex,
    props: {
      videoUrl: resolvedVideoUrl,
      durationInFrames: props.durationInFrames,
      fps: props.fps,
      width: props.width,
      height: props.height,
      subtitles: props.subtitles ?? null,
      hook: props.hook ?? null,
      effects: props.effects ?? null,
    },
  }).catch((err) => {
    console.error(`[render] Unhandled error for ${renderId}:`, err);
    const existingJob = renderJobs.get(renderId);
    if (existingJob) {
      existingJob.status = "error";
      existingJob.error =
        err instanceof Error ? err.message : "Unknown error";
    }
  });

  res.status(202).json({ renderId, status: "queued" });
});

// Get render status
app.get("/render/:renderId", (req, res) => {
  const { renderId } = req.params;
  const job = renderJobs.get(renderId);

  if (!job) {
    res.status(404).json({ error: "Render not found" });
    return;
  }

  const response: Record<string, unknown> = {
    renderId: job.renderId,
    status: job.status,
  };

  if (job.progress !== undefined) {
    response.progress = job.progress;
  }
  if (job.outputUrl) {
    response.outputUrl = job.outputUrl;
  }
  if (job.error) {
    response.error = job.error;
  }

  res.json(response);
});

// --- Start server ---

async function main() {
  console.log("[render-service] Initializing Remotion bundle...");
  await initBundle();
  console.log("[render-service] Bundle ready.");

  const server = app.listen(PORT, HOST, () => {
    console.log(`[render-service] Listening on http://${HOST}:${PORT}`);
  });

  const shutdown = (signal: string) => {
    console.log(`[render-service] Received ${signal}; closing HTTP server`);
    server.close((error) => {
      if (error) {
        console.error("[render-service] Error while closing HTTP server:", error);
        process.exitCode = 1;
      }
    });
  };
  process.once("SIGINT", () => shutdown("SIGINT"));
  process.once("SIGTERM", () => shutdown("SIGTERM"));
}

main().catch((err) => {
  console.error("[render-service] Fatal error during startup:", err);
  process.exit(1);
});
