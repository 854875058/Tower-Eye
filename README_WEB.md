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

### 1. 后端启动

```bash
# 进入后端目录
cd backend

# 安装依赖（如果还没安装）
pip install -r requirements.txt

# 启动 FastAPI 服务
python main.py

# 服务将运行在 http://localhost:8000
# API 文档: http://localhost:8000/docs
```

### 2. 前端启动

```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm start

# 应用将运行在 http://localhost:3000
```

### 3. 访问应用

打开浏览器访问: http://localhost:3000

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

### 前端部署

```bash
cd frontend
npm run build

# 将 build/ 目录部署到 Nginx 或其他静态服务器
```

### 后端部署

```bash
cd backend

# 使用 Gunicorn + Uvicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
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
