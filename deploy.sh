#!/bin/bash

echo "========================================"
echo "多模态检索系统 - 生产环境部署"
echo "========================================"
echo ""

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then
    echo "警告: 建议使用 sudo 运行此脚本"
fi

# 1. 安装系统依赖
echo "[1/6] 检查系统依赖..."
if command -v apt-get &> /dev/null; then
    echo "检测到 Debian/Ubuntu 系统"
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip nodejs npm nginx
elif command -v yum &> /dev/null; then
    echo "检测到 CentOS/RHEL 系统"
    sudo yum install -y python3 python3-pip nodejs npm nginx
else
    echo "警告: 未识别的系统，请手动安装依赖"
fi

# 2. 安装后端依赖
echo ""
echo "[2/6] 安装后端依赖..."
cd backend
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "错误: 后端依赖安装失败"
    exit 1
fi
cd ..

# 3. 安装前端依赖
echo ""
echo "[3/6] 安装前端依赖..."
cd frontend
npm install
if [ $? -ne 0 ]; then
    echo "错误: 前端依赖安装失败"
    exit 1
fi

# 4. 构建前端
echo ""
echo "[4/6] 构建前端生产版本..."
npm run build
if [ $? -ne 0 ]; then
    echo "错误: 前端构建失败"
    exit 1
fi
cd ..

# 5. 配置 Nginx
echo ""
echo "[5/6] 配置 Nginx..."
cat > /tmp/multimodal-nginx.conf << 'EOF'
server {
    listen 80;
    server_name _;

    # 前端静态文件
    location / {
        root /var/www/multimodal-search/frontend/build;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket 支持（如果需要）
    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

echo "Nginx 配置文件已生成: /tmp/multimodal-nginx.conf"
echo "请手动复制到 /etc/nginx/sites-available/ 并启用"

# 6. 创建 systemd 服务
echo ""
echo "[6/6] 创建 systemd 服务..."

# 后端服务
cat > /tmp/multimodal-backend.service << EOF
[Unit]
Description=Multimodal Search Backend API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)/backend
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "后端服务配置已生成: /tmp/multimodal-backend.service"
echo "请手动复制到 /etc/systemd/system/ 并启用"

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
echo "2. 复制前端文件:"
echo "   sudo mkdir -p /var/www/multimodal-search"
echo "   sudo cp -r frontend/build /var/www/multimodal-search/frontend/"
echo ""
echo "3. 启用后端服务:"
echo "   sudo cp /tmp/multimodal-backend.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable multimodal-backend"
echo "   sudo systemctl start multimodal-backend"
echo ""
echo "4. 检查服务状态:"
echo "   sudo systemctl status multimodal-backend"
echo "   sudo systemctl status nginx"
echo ""
