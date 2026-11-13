import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import {
  resolveListenHost,
  resolveOutputDirectory,
  resolveRendererPublicUrl,
  resolveRendererVideoUrl,
  resolveJobOutputDirectory,
} from "./paths.js";

test("native renderer defaults to loopback only", () => {
  assert.equal(resolveListenHost(undefined), "127.0.0.1");
});

test("Docker can explicitly bind renderer to all interfaces", () => {
  assert.equal(resolveListenHost("0.0.0.0"), "0.0.0.0");
  assert.equal(resolveRendererPublicUrl(3100, "0.0.0.0"), "http://127.0.0.1:3100");
});

test("output directory resolves absolute and relative paths", () => {
  const absolute = path.resolve("clippy-data", "output");
  assert.equal(resolveOutputDirectory(absolute), absolute);
  const cwd = path.resolve("clippy", "render-service");
  assert.equal(resolveOutputDirectory("media", cwd), path.resolve(cwd, "media"));
});

test("backend video URLs are routed through the shared output directory", () => {
  assert.equal(
    resolveRendererVideoUrl("http://127.0.0.1:8000/videos/job-1/clip one.mp4?download=1", "http://127.0.0.1:3100"),
    "http://127.0.0.1:3100/output/job-1/clip%20one.mp4?download=1",
  );
});

test("relative video URLs are also supported", () => {
  assert.equal(
    resolveRendererVideoUrl("/videos/job_2/clip.mp4", "http://127.0.0.1:3100"),
    "http://127.0.0.1:3100/output/job_2/clip.mp4",
  );
});

test("external media URLs are left unchanged", () => {
  assert.equal(
    resolveRendererVideoUrl("https://cdn.example.test/clip.mp4", "http://127.0.0.1:3100"),
    "https://cdn.example.test/clip.mp4",
  );
});

test("encoded traversal is rejected", () => {
  assert.throws(
    () => resolveRendererVideoUrl("/videos/job/%2e%2e/secrets.mp4", "http://127.0.0.1:3100"),
    /Invalid video path/,
  );
});

test("job output directory rejects path traversal", () => {
  assert.throws(() => resolveJobOutputDirectory("C:\\Clippy\\output", "..\\outside"), /Invalid render job ID/);
});


test("desktop renderer media URLs carry the per-launch token", () => {
  const url = new URL(resolveRendererVideoUrl(
    "/videos/job_2/clip.mp4",
    "http://127.0.0.1:3100",
    "session-secret",
  ));
  assert.equal(url.pathname, "/output/job_2/clip.mp4");
  assert.equal(url.searchParams.get("token"), "session-secret");
});
