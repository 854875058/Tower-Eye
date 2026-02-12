#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/logs/app.pid"

echo "========================================"
echo "多模态检索系统 - 停止"
echo "========================================"
echo ""

STOPPED=false

# 1. 通过 PID 文件停止
if [[ -f "$PID_FILE" ]]; then
    PID="$(tr -d '\n' <"$PID_FILE")"
    if [[ "$PID" =~ ^[0-9]+$ ]]; then
        if kill -0 "$PID" 2>/dev/null; then
            echo "发送 SIGTERM 到 PID=$PID..."
            kill "$PID" 2>/dev/null || true
            sleep 2
            # 还没死就强杀
            if kill -0 "$PID" 2>/dev/null; then
                echo "进程仍在运行，强制结束..."
                kill -9 "$PID" 2>/dev/null || true
            fi
            STOPPED=true
            echo "✓ 已停止 (PID: $PID)"
        else
            echo "PID $PID 对应的进程不存在"
        fi
    fi
    rm -f "$PID_FILE"
fi

# 2. 兜底：按进程名查杀
pkill -f "python poc/app/app_ui.py" 2>/dev/null && { echo "✓ 已清理 app_ui.py 残留进程"; STOPPED=true; } || true
pkill -f "python poc/app/app_v2.py" 2>/dev/null && echo "✓ 已清理 app_v2.py 残留进程" || true

# 3. 清理旧架构残留 PID
for pidfile in "$ROOT/poc_app.pid" "$ROOT/logs/backend.pid" "$ROOT/logs/frontend.pid"; do
    if [[ -f "$pidfile" ]]; then
        OLD_PID="$(tr -d '\n' <"$pidfile")"
        if [[ "$OLD_PID" =~ ^[0-9]+$ ]] && kill -0 "$OLD_PID" 2>/dev/null; then
            kill "$OLD_PID" 2>/dev/null || true
            echo "✓ 已停止旧服务 (PID: $OLD_PID, $pidfile)"
        fi
        rm -f "$pidfile"
    fi
done

if ! $STOPPED; then
    echo "没有发现运行中的服务"
fi

echo ""
echo "停止完成。"
echo ""
