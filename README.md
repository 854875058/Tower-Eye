# 铁塔之眼 — 多模态智能数据底座

基于 **RAG + LangGraph Agent** 架构的铁塔监控多模态检索与智能问答平台。融合结构化告警数据与非结构化图像/视频，提供自然语言问答、多模态向量检索、自动标注与模型训练的端到端解决方案。

## 功能概览

- **智能问答 (NL2SQL)**：自然语言提问 → DeepSeek LLM 生成 SQL → 自动执行并返回结果，支持自我修正（最多 3 次重试）
- **双路融合检索**：SQL 结构化查询 + 向量语义检索同时执行，结果合并排序，附带"您可能还感兴趣"推荐
- **多模态向量搜索**：支持文本、图片、视频作为查询输入，Qwen3-VL Embedding + 可选 Reranker 二阶段精排
- **混合检索策略**：70% 向量相似度 + 30% 关键词匹配（jieba 分词），DuckDB 预过滤加速
- **自动标注与训练**：YOLO 检测 + VL 模型场景描述 → 数据集构建 → YOLOv8 训练
- **安全护栏**：SQL 注入防护、表白名单、参数清理、危险操作拦截
- **全链路追踪**：每次查询的完整执行链路、耗时、错误信息均记录到 SQLite + JSONL

## 架构

```
用户层        NiceGUI Web UI (:8080) / React + Ant Design (:3000) / FastAPI (:8000)
                                    │
Agent 层      LangGraph 状态机 (解析 → 缓存 → 生成SQL → 验证 → 执行 → 语义增强 → 格式化)
                                    │
语义层        NL2SQL (DeepSeek) / 向量检索 (Qwen3-VL / CLIP) / Reranker
                                    │
安全层        SQL注入防护 / 白名单 / 参数清理
                                    │
数据层        LanceDB (向量+结构化) / DuckDB (SQL引擎) / SQLite (元数据+追踪)
```

详细架构文档见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 技术栈

| 层级 | 技术 |
|------|------|
| Web UI (主) | NiceGUI |
| Web UI (辅) | React 18 + Ant Design 5 + ECharts + 高德地图 |
| 后端 API | FastAPI + Uvicorn |
| Agent 编排 | LangGraph 状态机 |
| NL2SQL | DeepSeek (`deepseek-chat`) |
| Embedding | Qwen3-VL (远程服务) / CLIP (本地) |
| Reranker | Qwen3-VL Reranker |
| 向量数据库 | LanceDB |
| SQL 引擎 | DuckDB (内存，读取 LanceDB Arrow 数据) |
| 元数据存储 | SQLite |
| 目标检测 | YOLOv8x (Ultralytics) |
| VL 分析 | Qwen3-VL-8B-Instruct (VLLM) |
| 分布式计算 | Ray (GPU Actor) |
| 批处理 | Daft |
| 地图服务 | 高德地图 API |

## 项目结构

```
├── poc/                        # 核心应用
│   ├── app/                    # NiceGUI Web 界面
│   │   ├── app_ui.py           # 入口 (端口 8080)
│   │   └── pages/              # 页面: 仪表盘/问答/检索/标注/监控
│   ├── qa/                     # 智能问答引擎
│   │   ├── agent.py            # LangGraph 状态机
│   │   ├── nl2sql.py           # 意图分类 + SQL 生成
│   │   ├── guardrails.py       # SQL 安全护栏
│   │   └── trace.py            # 查询追踪与 SQL 缓存
│   ├── search/                 # 检索模块
│   │   ├── query.py            # 混合检索 (向量+关键词)
│   │   ├── model_manager.py    # 模型管理 (CLIP/Qwen)
│   │   ├── qwen_embedding.py   # Qwen3-VL Embedding 客户端
│   │   ├── qwen_reranker.py    # Qwen3-VL Reranker 客户端
│   │   └── duckdb_engine.py    # DuckDB SQL 引擎
│   ├── pipeline/               # 数据处理流水线
│   │   ├── ingest.py           # 数据入库
│   │   ├── embed.py            # 图像向量化 → LanceDB
│   │   ├── vl_analyze.py       # VL 场景描述
│   │   ├── auto_label_engine.py# 自动标注 (YOLO+VL)
│   │   ├── dataset_build.py    # 训练数据集构建
│   │   └── train_yolov8.py     # YOLOv8 训练
│   ├── infra/                  # 基础设施 (Ray 初始化/Actor)
│   ├── config/poc.yaml         # 中心配置文件
│   └── schema/metadata.sql     # SQLite 表结构
├── backend/                    # FastAPI REST API (辅助接口)
├── frontend/                   # React 前端 (辅助界面)
├── warning_img/                # 告警图片数据
├── warning_file/               # 告警视频数据
└── requirements.txt            # Python 依赖
```

## 快速开始

### 环境要求

- Python 3.8+
- CUDA GPU (推荐，CPU 也可运行)
- Qwen3-VL Embedding/Reranker 服务 (可选，可退回 CLIP 本地模型)
- DeepSeek API Key (智能问答功能)

### 安装

```bash
# 克隆仓库
git clone <repo-url>
cd 多模态检索-铁塔

# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 配置

编辑 `poc/config/poc.yaml`：

```yaml
# Embedding 模型选择: "qwen" (远程服务) 或 "clip" (本地)
search:
  embedding_model: "qwen"
  qwen_api_url: "http://<your-server>:8010"

# DeepSeek LLM (智能问答)
llm:
  api_key: "<your-deepseek-api-key>"

# 高德地图 (地理查询)
gaode:
  api_key: "<your-gaode-api-key>"
```

### 数据处理流水线

```bash
# 1. 数据入库 — 导入告警图片/视频/结构化数据到 SQLite
python -m poc.pipeline.ingest --config poc/config/poc.yaml

# 2. 图像向量化 — 生成 Embedding 写入 LanceDB
python -m poc.pipeline.embed --config poc/config/poc.yaml

# 3. (可选) VL 场景描述 — 为图片生成文字描述
python -m poc.pipeline.vl_analyze --config poc/config/poc.yaml

# 4. (可选) 自动标注 — YOLO 检测 + VL 分析
python -m poc.pipeline.label_auto --config poc/config/poc.yaml
```

### 启动应用

```bash
# 主界面 — NiceGUI (推荐)
python -m poc.app.app_ui
# 访问 http://localhost:8080

# (可选) FastAPI 后端
cd backend && uvicorn main:app --port 8000

# (可选) React 前端
cd frontend && npm install && npm start
# 访问 http://localhost:3000
```

## 使用示例

### 智能问答

在 `/qa` 页面输入自然语言问题：

- "最近 7 天车辆闯入告警有多少条？"
- "按街道统计各类告警数量"
- "查询最近 20 条烟火告警"
- "滨南东路附近有哪些监控设备？"

系统自动完成：意图识别 → SQL 生成/向量检索 → 执行 → 语义增强 → 格式化回答。

### 多模态检索

在 `/search` 页面：

- 输入文字描述搜索相似图片（如"夜间烟火"）
- 上传图片以图搜图
- 结合高级筛选（事件类型、时间范围、设备、地点等）缩小范围

## License

MIT
