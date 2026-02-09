#!/bin/bash

echo "========================================"
echo "检查服务状态"
echo "========================================"
echo ""

echo "[1] 检查后端日志..."
if [ -f logs/backend.log ]; then
    echo "后端日志内容："
    tail -50 logs/backend.log
else
    echo "后端日志文件不存在"
fi

echo ""
echo "[2] 检查前端日志..."
if [ -f logs/frontend.log ]; then
    echo "前端日志内容："
    tail -50 logs/frontend.log
else
    echo "前端日志文件不存在"
fi

echo ""
echo "[3] 检查端口占用..."
echo "8000 端口："
lsof -i :8000 2>/dev/null || echo "端口 8000 未被占用"
echo ""
echo "3000 端口："
lsof -i :3000 2>/dev/null || echo "端口 3000 未被占用"

echo ""
echo "[4] 检查 Python 和 Node.js..."
python3 --version
node --version
npm --version

echo ""
echo "[5] 检查数据库文件..."
ls -lh poc/data/metadata.db 2>/dev/null || echo "metadata.db 不存在"
ls -lh poc/data/lancedb/ 2>/dev/null || echo "lancedb 目录不存在"

