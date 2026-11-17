// Exercise the packaged composition with the persistent browser, without an
// API server, credentials, a model download, or externally hosted video.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { pathToFileURL } from 'node:url';

const [app, browserExecutable, fixture, output] = process.argv.slice(2);
if (!app || !browserExecutable || !fixture || !output) {
  throw new Error('Usage: smoke-render.mjs APP BROWSER VIDEO OUTPUT');
}
const rendererPath = path.join(app, 'render-service/node_modules/@remotion/renderer/dist/index.js');
const bundlerPath = path.join(app, 'render-service/node_modules/@remotion/bundler/dist/index.js');
const { bundle } = await import(pathToFileURL(bundlerPath).href);
const { selectComposition, renderMedia } = await import(pathToFileURL(rendererPath).href);
const video = fs.readFileSync(fixture);
const server = http.createServer((req, res) => {
  res.setHeader('Content-Type', 'video/mp4');
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Accept-Ranges', 'bytes');
  const match = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range ?? '');
  const start = match ? Number(match[1]) : 0;
  const end = match && match[2] ? Math.min(Number(match[2]), video.length - 1) : video.length - 1;
  if (start > end || start >= video.length) { res.writeHead(416); res.end(); return; }
  if (match) { res.statusCode = 206; res.setHeader('Content-Range', `bytes ${start}-${end}/${video.length}`); }
  res.setHeader('Content-Length', end - start + 1);
  res.end(req.method === 'HEAD' ? undefined : video.subarray(start, end + 1));
});
await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
let serveUrl;
try {
  serveUrl = await bundle({ entryPoint: path.join(app, 'remotion/src/index.ts') });
  const inputProps = {
    videoUrl: `http://127.0.0.1:${server.address().port}/fixture.mp4`,
    durationInFrames: 12, fps: 12, width: 180, height: 320,
    subtitles: null, hook: null, effects: null,
  };
  const composition = await selectComposition({ serveUrl, id: 'ShortVideo', inputProps, browserExecutable });
  await renderMedia({ composition, serveUrl, inputProps, browserExecutable, outputLocation: output, codec: 'h264', concurrency: 1 });
  if (fs.statSync(output).size === 0) throw new Error('Rendered video is empty');
  console.log('Packaged composition rendered successfully with the persistent browser.');
} finally {
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
  if (serveUrl) fs.rmSync(serveUrl, { recursive: true, force: true });
}
