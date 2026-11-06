@echo off
cd /d D:\openshorts\render-service
set PORT=13100
set HOST=127.0.0.1
node_modules\.bin\tsx src\server.ts