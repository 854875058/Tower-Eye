#!/bin/bash

echo "========================================"
echo "多模态检索系统 - 生产环境部署"
echo "========================================"
echo ""

# 1. 安装 Python 依赖
echo "[1/2] 安装 Python 依赖..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "错误: Python 依赖安装失败"
    exit 1
fi

# 2. 创建 systemd 服务
echo ""
echo "[2/2] 创建 systemd 服务..."

cat > /tmp/multimodal-app.service << EOF
[Unit]
Description=Multimodal Search NiceGUI App
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(which python) poc/app/app_ui.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "服务配置已生成: /tmp/multimodal-app.service"

echo ""
echo "========================================"
echo "部署准备完成！"
echo "========================================"
echo ""
echo "后续步骤："
echo "1. 启用服务:"
echo "   sudo cp /tmp/multimodal-app.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable multimodal-app"
echo "   sudo systemctl start multimodal-app"
echo ""
echo "2. 检查服务状态:"
echo "   sudo systemctl status multimodal-app"
echo ""
echo "或者直接用脚本启动:"
echo "   bash start.sh"
echo ""
