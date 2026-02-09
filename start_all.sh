#!/bin/bash

echo "========================================"
echo "多模态检索系统 - 一键启动"
echo "========================================"
echo ""

# 创建日志目录
mkdir -p logs

# 停止旧服务
echo "[0/3] 停止旧服务..."
pkill -f "python3 main.py" 2>/dev/null
pkill -f "npm start" 2>/dev/null
sleep 2

# 启动后端
echo ""
echo "[1/3] 启动后端服务..."
cd backend
nohup python3 main.py > ../logs/backend.log 2>&1 &
BACKEND_PID=$!
cd ..

# 保存 PID
echo $BACKEND_PID > logs/backend.pid
echo "✓ 后端服务已启动 (PID: $BACKEND_PID)"

# 等待后端启动
echo "等待后端服务启动..."
sleep 5

# 检查后端是否成功启动
if ps -p $BACKEND_PID > /dev/null; then
    echo "✓ 后端服务运行正常"

    # 测试后端 API
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "✓ 后端 API 响应正常"
    else
        echo "⚠ 后端 API 暂未响应，可能还在初始化..."
    fi
else
    echo "✗ 后端服务启动失败！"
    echo "查看日志: tail -f logs/backend.log"
    exit 1
fi

# 启动前端
echo ""
echo "[2/3] 启动前端应用..."
cd frontend
nohup npm start > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..

# 保存 PID
echo $FRONTEND_PID > logs/frontend.pid
echo "✓ 前端应用已启动 (PID: $FRONTEND_PID)"

echo ""
echo "[3/3] 等待前端编译..."
echo "这可能需要 30-60 秒，请耐心等待..."

# 等待前端编译完成（检查日志中是否出现 "Compiled successfully"）
for i in {1..60}; do
    if grep -q "Compiled successfully" logs/frontend.log 2>/dev/null; then
        echo "✓ 前端编译成功！"
        break
    fi
    if grep -q "Failed to compile" logs/frontend.log 2>/dev/null; then
        echo "✗ 前端编译失败！"
        echo "查看日志: tail -f logs/frontend.log"
        break
    fi
    sleep 1
    if [ $((i % 10)) -eq 0 ]; then
        echo "  等待中... ($i/60 秒)"
    fi
done

echo ""
echo "========================================"
echo "服务启动完成！"
echo "========================================"
echo ""
echo "访问地址："
echo "  前端应用: http://10.132.19.82:3000"
echo "  后端 API: http://10.132.19.82:8000"
echo "  API 文档: http://10.132.19.82:8000/docs"
echo ""
echo "管理服务："
echo "  查看后端日志: tail -f logs/backend.log"
echo "  查看前端日志: tail -f logs/frontend.log"
echo "  停止服务: bash stop_all.sh"
echo "  查看进程: ps aux | grep -E 'python3 main.py|npm start'"
echo ""
echo "后端 PID: $BACKEND_PID"
echo "前端 PID: $FRONTEND_PID"
echo ""
