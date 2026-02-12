#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "重启服务..."
bash "$ROOT/bin/stop.sh"
sleep 1
bash "$ROOT/bin/start.sh"
