#!/bin/bash

echo "========================================"
echo "多模态检索系统 - 停止服务"
echo "========================================"
echo ""

# 检查是否使用了 tmux 或 screen
if tmux has-session -t multimodal-backend 2>/dev/null; then
    echo "停止后端服务 (tmux)..."
    tmux kill-session -t multimodal-backend
    echo "✓ 后端服务已停止"
elif screen -list | grep -q "multimodal-backend"; then
    echo "停止后端服务 (screen)..."
    screen -S multimodal-backend -X quit
    echo "✓ 后端服务已停止"
elif [ -f "logs/backend.pid" ]; then
    echo "停止后端服务..."
    BACKEND_PID=$(cat logs/backend.pid)
    if ps -p $BACKEND_PID > /dev/null 2>&1; then
        kill $BACKEND_PID
        echo "✓ 后端服务已停止 (PID: $BACKEND_PID)"
    else
        echo "后端服务未运行"
    fi
    rm -f logs/backend.pid
else
    echo "未找到后端服务"
fi

echo ""

# 停止前端
if tmux has-session -t multimodal-frontend 2>/dev/null; then
    echo "停止前端应用 (tmux)..."
    tmux kill-session -t multimodal-frontend
    echo "✓ 前端应用已停止"
elif screen -list | grep -q "multimodal-frontend"; then
    echo "停止前端应用 (screen)..."
    screen -S multimodal-frontend -X quit
    echo "✓ 前端应用已停止"
elif [ -f "logs/frontend.pid" ]; then
    echo "停止前端应用..."
    FRONTEND_PID=$(cat logs/frontend.pid)
    if ps -p $FRONTEND_PID > /dev/null 2>&1; then
        kill $FRONTEND_PID
        echo "✓ 前端应用已停止 (PID: $FRONTEND_PID)"
    else
        echo "前端应用未运行"
    fi
    rm -f logs/frontend.pid
else
    echo "未找到前端应用"
fi

echo ""
echo "所有服务已停止"
echo ""
