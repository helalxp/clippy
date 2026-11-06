$ErrorActionPreference = "Stop"
cd D:\openshorts\render-service
$env:PORT = "13100"
$env:HOST = "127.0.0.1"
& .\node_modules\.bin\tsx .\src\server.ts