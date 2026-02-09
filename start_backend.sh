#!/bin/bash

echo "========================================"
echo "启动多模态检索系统 - 后端服务"
echo "========================================"
echo ""

cd backend

echo "[1/2] 检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 Python3，请先安装 Python 3.8+"
    exit 1
fi

python3 --version

echo ""
echo "[2/2] 启动 FastAPI 服务..."
echo "服务地址: http://localhost:8000"
echo "API 文档: http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

python3 main.py
