# Native Windows renderer contract

The renderer can run directly on Windows without Docker. The desktop process
supervisor must start it with the same media directory used by FastAPI.

Required environment:

```powershell
$env:PORT = "13100"
$env:HOST = "127.0.0.1"
$env:OUTPUT_DIR = "$env:LOCALAPPDATA\Clippy\output"
$env:RENDER_SERVICE_URL = "http://127.0.0.1:13100"
$env:REMOTION_BUNDLE_PATH = "<installed-clippy-root>\remotion"
$env:RENDERER_PUBLIC_URL = "http://127.0.0.1:13100"
```

`OUTPUT_DIR` is a shared-data contract: Python and Node must point to the exact
same directory. Do not point the renderer at a separate copy. The renderer
serves that directory under `/output`; backend video URLs such as
`/videos/<job-id>/<filename>` are translated to the local renderer URL so
Remotion's Chromium process can read the source file.

The native default bind address is `127.0.0.1`, preventing LAN exposure.
Docker Compose explicitly overrides this to `0.0.0.0` for service-to-service
networking. `RENDERER_PUBLIC_URL` is the address Chromium uses to fetch media,
not the address the desktop UI should expose.

Run the lightweight path/configuration tests with:

```powershell
cd render-service
npm ci
npm run test:unit
npm run build
```

The full `npm test` also initializes the Remotion bundle and Chromium, so it is
an integration test and requires the complete renderer runtime.
