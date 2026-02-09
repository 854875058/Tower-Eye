#!/bin/bash

echo "========================================"
echo "多模态检索系统 - 一键启动"
echo "========================================"
echo ""
echo "正在启动后端和前端服务..."
echo ""

# 检查是否安装了 tmux 或 screen
if command -v tmux &> /dev/null; then
    SESSION_MANAGER="tmux"
elif command -v screen &> /dev/null; then
    SESSION_MANAGER="screen"
else
    SESSION_MANAGER="background"
fi

# 启动后端
echo "[1/2] 启动后端服务..."
if [ "$SESSION_MANAGER" = "tmux" ]; then
    tmux new-session -d -s multimodal-backend "cd backend && python3 main.py"
    echo "✓ 后端服务已在 tmux 会话 'multimodal-backend' 中启动"
elif [ "$SESSION_MANAGER" = "screen" ]; then
    screen -dmS multimodal-backend bash -c "cd backend && python3 main.py"
    echo "✓ 后端服务已在 screen 会话 'multimodal-backend' 中启动"
else
    cd backend && python3 main.py > ../logs/backend.log 2>&1 &
    BACKEND_PID=$!
    echo "✓ 后端服务已启动 (PID: $BACKEND_PID)"
    cd ..
fi

# 等待后端启动
echo "等待后端服务启动..."
sleep 3

# 启动前端
echo ""
echo "[2/2] 启动前端应用..."
if [ "$SESSION_MANAGER" = "tmux" ]; then
    tmux new-session -d -s multimodal-frontend "cd frontend && npm start"
    echo "✓ 前端应用已在 tmux 会话 'multimodal-frontend' 中启动"
elif [ "$SESSION_MANAGER" = "screen" ]; then
    screen -dmS multimodal-frontend bash -c "cd frontend && npm start"
    echo "✓ 前端应用已在 screen 会话 'multimodal-frontend' 中启动"
else
    cd frontend && npm start > ../logs/frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo "✓ 前端应用已启动 (PID: $FRONTEND_PID)"
    cd ..
fi

echo ""
echo "========================================"
echo "服务启动完成！"
echo "========================================"
echo ""
echo "后端服务: http://localhost:8000"
echo "API 文档: http://localhost:8000/docs"
echo "前端应用: http://localhost:3000"
echo ""

if [ "$SESSION_MANAGER" = "tmux" ]; then
    echo "管理服务："
    echo "  查看后端: tmux attach -t multimodal-backend"
    echo "  查看前端: tmux attach -t multimodal-frontend"
    echo "  停止后端: tmux kill-session -t multimodal-backend"
    echo "  停止前端: tmux kill-session -t multimodal-frontend"
elif [ "$SESSION_MANAGER" = "screen" ]; then
    echo "管理服务："
    echo "  查看后端: screen -r multimodal-backend"
    echo "  查看前端: screen -r multimodal-frontend"
    echo "  停止后端: screen -S multimodal-backend -X quit"
    echo "  停止前端: screen -S multimodal-frontend -X quit"
else
    echo "管理服务："
    echo "  查看日志: tail -f logs/backend.log 或 logs/frontend.log"
    echo "  停止服务: ./stop_all.sh"

    # 保存 PID 到文件
    mkdir -p logs
    echo $BACKEND_PID > logs/backend.pid
    echo $FRONTEND_PID > logs/frontend.pid
fi

echo ""
