#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_PORT=${APP_PORT:-8080}

echo "========================================"
echo "多模态检索系统 - 状态检查"
echo "========================================"
echo ""

# [1] 进程状态
echo "[1] 进程状态"
PID_FILE="$ROOT/logs/app.pid"
if [[ -f "$PID_FILE" ]]; then
    PID="$(tr -d '\n' <"$PID_FILE")"
    if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null; then
        echo "  ✓ 运行中 (PID: $PID)"
    else
        echo "  ✗ PID 文件存在但进程不在运行"
    fi
else
    echo "  ✗ 未找到 PID 文件"
fi
ps aux 2>/dev/null | grep "app_ui.py" | grep -v grep || true

# [2] 端口 & 连通性
echo ""
echo "[2] 端口 & 连通性"
if command -v lsof &>/dev/null; then
    lsof -i :"$APP_PORT" 2>/dev/null || echo "  端口 $APP_PORT 未被占用"
fi
if command -v curl &>/dev/null; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$APP_PORT" 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" ]]; then
        echo "  ✓ http://localhost:$APP_PORT 响应正常 (HTTP $HTTP_CODE)"
    else
        echo "  ✗ http://localhost:$APP_PORT 无响应 (HTTP $HTTP_CODE)"
    fi
fi

# [3] Python 环境
echo ""
echo "[3] Python 环境"
echo "  Python: $(python --version 2>&1 || echo '未找到')"
echo "  nicegui: $(python -c 'import nicegui; print(nicegui.__version__)' 2>/dev/null || echo '未安装')"
echo "  lancedb: $(python -c 'import lancedb; print(lancedb.__version__)' 2>/dev/null || echo '未安装')"

# [4] 数据文件
echo ""
echo "[4] 数据文件"
ls -lh "$ROOT/poc/data/metadata.db" 2>/dev/null || echo "  metadata.db 不存在"
ls -d "$ROOT/poc/data/lancedb/" 2>/dev/null && echo "  lancedb 目录存在" || echo "  lancedb 目录不存在"

# [5] 最近日志
echo ""
echo "[5] 最近日志 (最后 20 行)"
LOG_FILE="$ROOT/logs/app.log"
if [[ -f "$LOG_FILE" ]]; then
    tail -20 "$LOG_FILE"
else
    echo "  日志文件不存在"
fi
echo ""
