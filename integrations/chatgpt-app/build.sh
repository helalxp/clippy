#!/usr/bin/env sh
# Builds the ChatGPT plugin ZIP for platform.openai.com/plugins.
# Usage: integrations/chatgpt-app/build.sh  → integrations/chatgpt-app/dist/openshorts-chatgpt-<version>.zip
set -eu
cd "$(dirname "$0")"
version=$(python3 -c "import json;print(json.load(open('plugin/plugin.json'))['version'])")
mkdir -p dist
out="dist/openshorts-chatgpt-${version}.zip"
rm -f "$out"
(cd plugin && zip -qrX "../$out" plugin.json mcp.json skills assets -x '*.DS_Store')
echo "$out"
unzip -l "$out"
