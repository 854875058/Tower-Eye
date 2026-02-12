#!/bin/bash

echo "========================================"
echo "多模态检索系统 - NiceGUI 应用"
echo "========================================"
echo ""
echo "注意: 新架构已合并前后端为单一 NiceGUI 应用。"
echo "请使用 start_all.sh 或 start_poc.sh 启动。"
echo ""

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "检查 Python 环境..."
python --version 2>/dev/null || python3 --version 2>/dev/null

echo ""
echo "启动 NiceGUI 应用..."
echo "服务地址: http://localhost:8080"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

python poc/app/app_ui.py
