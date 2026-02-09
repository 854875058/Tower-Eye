#!/bin/bash

echo "========================================"
echo "启动多模态检索系统 - 前端应用"
echo "========================================"
echo ""

cd frontend

echo "[1/3] 检查 Node.js 环境..."
if ! command -v node &> /dev/null; then
    echo "错误: 未找到 Node.js，请先安装 Node.js 16+"
    exit 1
fi

node --version
npm --version

echo ""
echo "[2/3] 检查依赖..."
if [ ! -d "node_modules" ]; then
    echo "首次运行，正在安装依赖..."
    npm install
    if [ $? -ne 0 ]; then
        echo "错误: 依赖安装失败"
        exit 1
    fi
else
    echo "依赖已安装"
fi

echo ""
echo "[3/3] 启动开发服务器..."
echo "应用地址: http://localhost:3000"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

npm start
