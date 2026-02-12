#!/bin/bash

echo "========================================"
echo "多模态检索系统 - 生产环境部署 (NiceGUI)"
echo "========================================"
echo ""

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then
    echo "警告: 建议使用 sudo 运行此脚本"
fi

# 1. 安装系统依赖
echo "[1/4] 检查系统依赖..."
if command -v apt-get &> /dev/null; then
    echo "检测到 Debian/Ubuntu 系统"
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip nginx
elif command -v yum &> /dev/null; then
    echo "检测到 CentOS/RHEL 系统"
    sudo yum install -y python3 python3-pip nginx
else
    echo "警告: 未识别的系统，请手动安装依赖"
fi

# 2. 安装 Python 依赖
echo ""
echo "[2/4] 安装 Python 依赖..."
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "错误: Python 依赖安装失败"
    exit 1
fi

# 3. 配置 Nginx（反向代理 NiceGUI）
echo ""
echo "[3/4] 配置 Nginx..."
cat > /tmp/multimodal-nginx.conf << 'EOF'
server {
    listen 80;
    server_name _;

    # 反向代理到 NiceGUI
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket 支持（NiceGUI 需要）
    location /ws/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Socket.IO 支持（NiceGUI 需要）
    location /socket.io/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

echo "Nginx 配置文件已生成: /tmp/multimodal-nginx.conf"
echo "请手动复制到 /etc/nginx/sites-available/ 并启用"

# 4. 创建 systemd 服务
echo ""
echo "[4/4] 创建 systemd 服务..."

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
echo "1. 复制 Nginx 配置:"
echo "   sudo cp /tmp/multimodal-nginx.conf /etc/nginx/sites-available/multimodal"
echo "   sudo ln -s /etc/nginx/sites-available/multimodal /etc/nginx/sites-enabled/"
echo "   sudo nginx -t && sudo systemctl reload nginx"
echo ""
echo "2. 启用应用服务:"
echo "   sudo cp /tmp/multimodal-app.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable multimodal-app"
echo "   sudo systemctl start multimodal-app"
echo ""
echo "3. 检查服务状态:"
echo "   sudo systemctl status multimodal-app"
echo "   sudo systemctl status nginx"
echo ""
