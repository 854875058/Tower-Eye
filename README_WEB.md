# 多模态检索系统 - 生产级 Web 应用

统一的多维数据底座，支持多模态、空间、时序的联合检索。

## 🎯 核心功能

### 1. 智能检索
- ✅ 多模态检索（文本 + 图像）
- ✅ 事件类型过滤
- ✅ 时间范围查询
- ✅ 地理位置检索（经纬度 + 半径）
- ✅ 混合检索（向量 + 关键词）

### 2. 地图展示
- ✅ 空间分布可视化
- ✅ 高德地图集成
- ✅ 标记点聚合
- ✅ 区域统计
- ✅ 交互式详情展示

### 3. 数据大屏
- ✅ 实时统计概览
- ✅ 事件类型分布（饼图）
- ✅ 区域分布 TOP 10（柱状图）
- ✅ 告警趋势分析（折线图）
- ✅ 核心指标卡片

## 🏗️ 技术架构

### 前端
- **框架**: React 18
- **UI 库**: Ant Design 5 + Ant Design Pro
- **路由**: React Router 6
- **图表**: ECharts
- **地图**: 高德地图 API
- **HTTP**: Axios

### 后端
- **框架**: FastAPI
- **向量检索**: LanceDB
- **数据库**: SQLite
- **模型**: CLIP (Sentence Transformers)
- **服务器**: Uvicorn

## 📦 项目结构

```
多模态检索-铁塔/
├── frontend/                 # 前端项目
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── pages/           # 页面组件
│   │   │   ├── SearchPage.js      # 智能检索页
│   │   │   ├── MapPage.js         # 地图展示页
│   │   │   └── DashboardPage.js   # 数据大屏页
│   │   ├── services/        # API 服务
│   │   │   └── api.js
│   │   ├── App.js           # 主应用
│   │   └── index.js         # 入口文件
│   └── package.json
├── backend/                 # 后端 API
│   ├── main.py             # FastAPI 应用
│   └── requirements.txt
└── poc/                     # 现有检索逻辑（保留）
```

## 🚀 快速开始

### 方式一：一键启动（推荐）

```bash
# 使用统一运维脚本启动
python3 bin/manage.py start

# 停止服务
python3 bin/manage.py stop

# 查看状态
python3 bin/manage.py status
```

### 方式二：生产环境部署

**使用部署脚本：**
```bash
# 准备生产环境配置
bash bin/deploy.sh

# 按照提示完成 systemd 服务配置
```

**手动启动：**
```bash
# 确保配置文件存在
cp poc/config/poc.yaml.example poc/config/poc.yaml

# 安装依赖
pip3 install -r requirements.txt

# 启动应用
python3 poc/app/app_ui.py
```

### 3. 访问应用

打开浏览器访问: http://localhost:3000

### 4. 服务管理

**使用统一运维脚本：**
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

## 📝 API 接口文档

### 健康检查
```
GET /api/health
```

### 多维度检索
```
POST /api/search
Body: {
  "text": "烟火",
  "event_type": "烟火告警",
  "start_time": "2025-01-01 00:00:00",
  "end_time": "2025-12-31 23:59:59",
  "lat": 39.9,
  "lon": 116.4,
  "radius_km": 5.0,
  "top_k": 20
}
```

### 统计概览
```
GET /api/statistics/overview?start_time=xxx&end_time=xxx
```

### 地图统计
```
GET /api/statistics/map?start_time=xxx&end_time=xxx&event_type=xxx
```

### 事件详情
```
GET /api/events/{event_id}
```

### 媒体文件
```
GET /api/media/{asset_id}
```

## 🎨 页面展示

### 1. 智能检索页
- 多条件组合查询
- 结果卡片展示
- 图片预览
- 相似度评分

### 2. 地图展示页
- 空间分布可视化
- 标记点交互
- 区域统计列表
- 事件类型分布

### 3. 数据大屏页
- 核心指标展示
- 多维度图表
- 趋势分析
- 实时刷新

## 🔧 配置说明

### 高德地图 API Key

编辑 `frontend/public/index.html`，替换 `YOUR_AMAP_KEY`：

```html
<script type="text/javascript" src="https://webapi.amap.com/maps?v=2.0&key=YOUR_AMAP_KEY"></script>
```

申请地址: https://lbs.amap.com/

### 后端 API 地址

编辑 `frontend/src/services/api.js`，修改 `baseURL`：

```javascript
const api = axios.create({
  baseURL: 'http://localhost:8000',  // 修改为实际后端地址
  timeout: 30000,
});
```

## 📊 数据说明

### 当前数据规模
- 总事件数: 804 条
- 地理分布: 福建省、河南省、北京市、天津市等
- 事件类型: 车辆闯入监控告警
- 时间范围: 2025-11-18 至 2026-01-16

### 数据结构
- **assets**: 媒体资产（图片、视频）
- **events**: 告警事件（类型、时间、位置）
- **embeddings**: 向量嵌入（用于检索）

## 🔄 与现有系统的关系

- **保留**: 现有的 `poc/` 目录和 Streamlit 应用
- **新增**: `frontend/` 和 `backend/` 目录
- **共享**: 使用相同的数据库和检索逻辑
- **独立**: 前后端分离，可独立部署

## 🚢 生产部署

### 方式一：自动化部署（推荐）

```bash
# 运行部署脚本（会自动安装依赖、配置服务）
bash bin/deploy.sh

# 按照脚本提示完成后续配置
```

### 方式二：手动部署

#### 1. 安装系统依赖

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip nodejs npm nginx
```

**CentOS/RHEL:**
```bash
sudo yum install -y python3 python3-pip nodejs npm nginx
```

#### 2. 安装项目依赖

```bash
# 后端依赖
cd backend
pip3 install -r requirements.txt
cd ..

# 前端依赖
cd frontend
npm install
cd ..
```

#### 3. 构建前端

```bash
cd frontend
npm run build
cd ..
```

#### 4. 配置 Nginx

创建 Nginx 配置文件 `/etc/nginx/sites-available/multimodal`:

```nginx
server {
    listen 80;
    server_name your-domain.com;  # 修改为你的域名或 IP

    # 前端静态文件
    location / {
        root /var/www/multimodal-search/frontend/build;
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "public, max-age=3600";
    }

    # 后端 API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # 媒体文件（如果需要）
    location /media/ {
        alias /path/to/your/media/files/;
        add_header Cache-Control "public, max-age=86400";
    }
}
```

启用配置：
```bash
sudo ln -s /etc/nginx/sites-available/multimodal /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 5. 部署前端文件

```bash
sudo mkdir -p /var/www/multimodal-search/frontend
sudo cp -r frontend/build /var/www/multimodal-search/frontend/
sudo chown -R www-data:www-data /var/www/multimodal-search
```

#### 6. 配置后端服务（systemd）

创建服务文件 `/etc/systemd/system/multimodal-backend.service`:

```ini
[Unit]
Description=Multimodal Search Backend API
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/your/project/backend
Environment="PATH=/usr/bin:/usr/local/bin"
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/multimodal-backend.log
StandardError=append:/var/log/multimodal-backend-error.log

[Install]
WantedBy=multi-user.target
```

启用并启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable multimodal-backend
sudo systemctl start multimodal-backend
sudo systemctl status multimodal-backend
```

#### 7. 使用 Gunicorn（生产环境推荐）

安装 Gunicorn:
```bash
pip3 install gunicorn
```

修改 systemd 服务的 ExecStart:
```ini
ExecStart=/usr/local/bin/gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000
```

#### 8. 配置防火墙

```bash
# 允许 HTTP 和 HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

#### 9. 配置 HTTPS（可选但推荐）

使用 Let's Encrypt:
```bash
sudo apt-get install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 服务管理命令

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

### 性能优化建议

1. **启用 Gzip 压缩**（Nginx）:
```nginx
gzip on;
gzip_vary on;
gzip_min_length 1024;
gzip_types text/plain text/css text/xml text/javascript application/javascript application/json;
```

2. **配置缓存**:
```nginx
location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

3. **增加 Worker 进程**:
```bash
# 根据 CPU 核心数调整 Gunicorn workers
gunicorn main:app -w $(nproc) -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000
```

4. **配置日志轮转**:
```bash
sudo nano /etc/logrotate.d/multimodal
```

内容：
```
/var/log/multimodal-*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 your-user your-user
}
```

## 🎯 下一步计划

### 短期（1-2周）
- [ ] 添加用户认证
- [ ] 优化大规模数据性能
- [ ] 添加更多图表类型
- [ ] 支持视频预览

### 中期（1个月）
- [ ] 升级到 Qwen3-VL 模型
- [ ] 添加时间轴页面
- [ ] 支持批量导出
- [ ] 添加告警推送

### 长期（3个月）
- [ ] 支持实时流数据
- [ ] 添加 AI 问答功能
- [ ] 多租户支持
- [ ] 移动端适配

## 📞 技术支持

如有问题，请联系开发团队。

## 📄 许可证

内部项目，仅供授权使用。
