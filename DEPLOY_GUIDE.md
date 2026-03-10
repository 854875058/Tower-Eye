# 快速部署指南 - 10.132.19.82

## 📋 部署清单

### 已配置
- ✅ 高德地图 API Key: 5a4ded47a2c36b9158075d2518428785
- ✅ 服务器 IP: 10.132.19.82
- ✅ 后端 API 地址: http://10.132.19.82:8000
- ✅ 前端访问地址: http://10.132.19.82:3000（开发）或 http://10.132.19.82（生产）

### 不需要
- ❌ 域名（暂不需要）
- ❌ SSL 证书（暂不需要）

---

## 🚀 部署步骤

### 方式一：开发环境快速部署（推荐先用这个测试）

#### 1. 连接到服务器
```bash
ssh user@10.132.19.82
```

#### 2. 安装必要软件
```bash
# 更新系统
sudo apt-get update

# 安装 Python3、Node.js、Git
sudo apt-get install -y python3 python3-pip nodejs npm git

# 验证安装
python3 --version
node --version
npm --version
```

#### 3. 克隆代码
```bash
# 克隆你的代码仓库
cd ~
git clone <your-repo-url> multimodal-search
cd multimodal-search
```

#### 4. 安装依赖
```bash
# 安装完整依赖（推荐，包含所有功能）
pip3 install -r requirements.txt

# 或仅安装后端最小依赖（仅 API 服务）
pip3 install -r backend/requirements.txt
```

#### 5. 安装前端依赖
```bash
cd frontend
npm install
cd ..
```

#### 6. 启动服务
```bash
# 使用统一运维脚本启动
python3 bin/manage.py start

# 或使用部署脚本准备生产环境
bash bin/deploy.sh
```

#### 7. 访问应用
- 前端: http://10.132.19.82:3000
- 后端 API: http://10.132.19.82:8000
- API 文档: http://10.132.19.82:8000/docs

---

### 方式二：生产环境部署（正式使用）

#### 1. 安装 Nginx
```bash
sudo apt-get install -y nginx
```

#### 2. 构建前端
```bash
cd frontend
npm run build
cd ..
```

#### 3. 配置 Nginx
创建配置文件：
```bash
sudo nano /etc/nginx/sites-available/multimodal
```

内容：
```nginx
server {
    listen 80;
    server_name 10.132.19.82;

    # 前端静态文件
    location / {
        root /home/your-user/multimodal-search/frontend/build;
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "public, max-age=3600";
    }

    # 后端 API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }
}
```

启用配置：
```bash
sudo ln -s /etc/nginx/sites-available/multimodal /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### 4. 配置后端服务
创建 systemd 服务：
```bash
sudo nano /etc/systemd/system/multimodal-backend.service
```

内容（**注意修改路径和用户名**）：
```ini
[Unit]
Description=Multimodal Search Backend API
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/home/your-user/multimodal-search/backend
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable multimodal-backend
sudo systemctl start multimodal-backend
sudo systemctl status multimodal-backend
```

#### 5. 配置防火墙
```bash
# 允许 HTTP
sudo ufw allow 80/tcp

# 允许后端端口（如果需要直接访问）
sudo ufw allow 8000/tcp

# 允许前端端口（开发环境）
sudo ufw allow 3000/tcp

# 启用防火墙
sudo ufw enable
```

#### 6. 访问应用
- 生产环境: http://10.132.19.82

---

## 🔧 常用管理命令

### 开发环境

```bash
# 启动服务
python3 bin/manage.py start

# 停止服务
python3 bin/manage.py stop

# 重启服务
python3 bin/manage.py restart

# 查看状态
python3 bin/manage.py status

# 查看日志
tail -f logs/app.log
```

### 生产环境

```bash
# 查看后端服务状态
sudo systemctl status multimodal-backend

# 重启后端服务
sudo systemctl restart multimodal-backend

# 查看后端日志
sudo journalctl -u multimodal-backend -f

# 重启 Nginx
sudo systemctl restart nginx

# 查看 Nginx 日志
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

---

## ⚠️ 常见问题

### 1. 端口被占用
```bash
# 查看端口占用
sudo lsof -i :8000
sudo lsof -i :3000

# 杀死进程
sudo kill -9 <PID>
```

### 2. 权限问题
```bash
# 给脚本添加执行权限
chmod +x *.sh

# 修改文件所有者
sudo chown -R $USER:$USER ~/multimodal-search
```

### 3. 依赖安装失败
```bash
# Python 依赖（完整版）
pip3 install --upgrade pip
pip3 install -r requirements.txt --no-cache-dir

# Python 依赖（后端最小版）
pip3 install -r backend/requirements.txt --no-cache-dir

# Node.js 依赖
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### 4. 前端无法连接后端
检查 API 地址配置：
```bash
# 查看配置
cat frontend/src/services/api.js | grep baseURL

# 应该显示: baseURL: process.env.REACT_APP_API_URL || 'http://10.132.19.82:8000'
```

### 5. 地图不显示
检查高德地图 API Key：
```bash
cat frontend/public/index.html | grep amap

# 应该显示: key=5a4ded47a2c36b9158075d2518428785
```

---

## 📊 部署检查清单

部署完成后，请检查以下项目：

- [ ] 后端服务正常运行（访问 http://10.132.19.82:8000/api/health）
- [ ] 前端页面可以访问（http://10.132.19.82:3000 或 http://10.132.19.82）
- [ ] 地图可以正常显示
- [ ] 检索功能正常
- [ ] 数据大屏图表正常显示
- [ ] 防火墙规则已配置
- [ ] 服务自动启动已配置（生产环境）

---

## 🎯 下一步操作

### 立即要做的：
1. **连接到服务器** `ssh user@10.132.19.82`
2. **安装依赖** Python3、Node.js、Git
3. **克隆代码** 从你的 Git 仓库
4. **启动服务** 使用 `./start_all.sh`
5. **测试访问** http://10.132.19.82:3000

### 测试通过后：
1. **构建生产版本** `npm run build`
2. **配置 Nginx** 反向代理
3. **配置 systemd** 服务自动启动
4. **配置防火墙** 安全规则

---

## 📞 需要帮助？

如果遇到问题，请提供以下信息：
- 错误日志（`tail -f logs/backend.log`）
- 服务状态（`sudo systemctl status multimodal-backend`）
- 浏览器控制台错误（F12 查看）
