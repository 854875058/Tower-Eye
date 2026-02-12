#!/bin/bash

echo "========================================"
echo "多模态检索系统 - 停止服务"
echo "========================================"
echo ""

# 停止 NiceGUI 应用（新架构）
if [ -f "logs/app.pid" ]; then
    echo "停止 NiceGUI 应用..."
    APP_PID=$(cat logs/app.pid)
    if ps -p $APP_PID > /dev/null 2>&1; then
        kill $APP_PID
        echo "✓ 应用已停止 (PID: $APP_PID)"
    else
        echo "应用未运行"
    fi
    rm -f logs/app.pid
else
    echo "未找到 logs/app.pid"
fi

# 兜底：按进程名查杀
echo ""
echo "检查残留进程..."
pkill -f "python poc/app/app_ui.py" 2>/dev/null && echo "✓ 已清理 app_ui.py 残留进程" || true
pkill -f "python poc/app/app_v2.py" 2>/dev/null && echo "✓ 已清理 app_v2.py 残留进程" || true

# 兼容旧架构的 PID 文件
for pidfile in logs/backend.pid logs/frontend.pid; do
    if [ -f "$pidfile" ]; then
        PID=$(cat "$pidfile")
        if ps -p $PID > /dev/null 2>&1; then
            kill $PID 2>/dev/null
            echo "✓ 已停止旧服务 (PID: $PID, from $pidfile)"
        fi
        rm -f "$pidfile"
    fi
done

echo ""
echo "所有服务已停止"
echo ""
