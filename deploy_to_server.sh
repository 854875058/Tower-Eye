#!/bin/bash

# 一键部署到服务器 10.132.19.82
# 使用方法: ./deploy_to_server.sh

SERVER_IP="10.132.19.82"
SERVER_USER="your-user"  # 请修改为实际的用户名
SERVER_PATH="/home/$SERVER_USER/multimodal-search"

echo "========================================"
echo "部署到服务器: $SERVER_IP"
echo "========================================"
echo ""

# 检查是否配置了 SSH
echo "[1/5] 检查 SSH 连接..."
if ! ssh -o ConnectTimeout=5 $SERVER_USER@$SERVER_IP "echo 'SSH 连接成功'" 2>/dev/null; then
    echo "错误: 无法连接到服务器 $SERVER_IP"
    echo "请确保："
    echo "  1. 服务器 IP 正确"
    echo "  2. 用户名正确（修改脚本中的 SERVER_USER）"
    echo "  3. 已配置 SSH 密钥或可以输入密码"
    exit 1
fi

# 同步代码到服务器
echo ""
echo "[2/5] 同步代码到服务器..."
rsync -avz --exclude 'node_modules' \
           --exclude '.git' \
           --exclude 'logs' \
           --exclude '__pycache__' \
           --exclude '*.pyc' \
           --exclude 'frontend/build' \
           ./ $SERVER_USER@$SERVER_IP:$SERVER_PATH/

if [ $? -ne 0 ]; then
    echo "错误: 代码同步失败"
    exit 1
fi

# 在服务器上安装依赖
echo ""
echo "[3/5] 安装后端依赖..."
ssh $SERVER_USER@$SERVER_IP "cd $SERVER_PATH/backend && pip3 install -r requirements.txt"

echo ""
echo "[4/5] 安装前端依赖..."
ssh $SERVER_USER@$SERVER_IP "cd $SERVER_PATH/frontend && npm install"

# 启动服务
echo ""
echo "[5/5] 启动服务..."
ssh $SERVER_USER@$SERVER_IP "cd $SERVER_PATH && chmod +x *.sh && ./start_all.sh"

echo ""
echo "========================================"
echo "部署完成！"
echo "========================================"
echo ""
echo "访问地址："
echo "  前端: http://$SERVER_IP:3000"
echo "  后端: http://$SERVER_IP:8000"
echo "  API 文档: http://$SERVER_IP:8000/docs"
echo ""
echo "管理服务："
echo "  查看服务: ssh $SERVER_USER@$SERVER_IP 'cd $SERVER_PATH && tmux ls'"
echo "  停止服务: ssh $SERVER_USER@$SERVER_IP 'cd $SERVER_PATH && ./stop_all.sh'"
echo ""
