#!/usr/bin/env pwsh
# Render service runner
& 'D:\openshorts\render-service\node_modules\.bin\tsx' 'D:\openshorts\render-service\src\server.ts' 2>&1 | Write-Host