# Tower-Eye

`Tower-Eye` 是一套基于 `poc/` 目录运行的多模态检索与智能问答系统，主界面为 NiceGUI，核心链路包括：

- 结构化告警数据入库
- 图像和视频向量化写入 LanceDB
- DuckDB 统一查询分析
- LangGraph Agent 驱动的 NL2SQL 与问答
- 多模态检索、自动标注、监控与追踪

## 当前状态

- 主系统入口：`poc/app/app_ui.py`
- 推荐启动方式：`python bin/manage.py start`
- 推荐配置文件：`poc/config/poc.yaml`
- 示例配置：`poc/config/poc.yaml.example`

旧的 `backend/` 和 `frontend/` 演示壳已经从仓库移除，仓库当前只维护 `poc/` 这条主链路。

## 目录结构

```text
Tower-Eye/
├── poc/
│   ├── app/                # NiceGUI 界面
│   ├── pipeline/           # 入库、向量化、标注、训练流程
│   ├── qa/                 # Agent / NL2SQL / trace / tools
│   ├── search/             # 向量检索、DuckDB、模型管理
│   ├── infra/              # Ray、HTTP、metrics
│   ├── schema/             # SQLite schema
│   └── config/             # 配置模板
├── bin/                    # 启停、部署、运维脚本
├── docs/                   # 项目文档
├── tests/                  # 测试与评估脚本
├── data/
│   ├── warning_img/        # 告警图片数据
│   ├── warning_file/       # 告警视频数据
│   ├── metadata.db         # 元数据数据库
│   └── lancedb/            # 向量库与结构化查询底座
└── requirements.txt
```

## 技术栈

- Web UI: NiceGUI
- Agent: LangGraph
- LLM: DeepSeek
- Embedding / Reranker: Qwen3-VL 或本地 CLIP
- Vector Store: LanceDB
- SQL Engine: DuckDB
- Metadata / Trace: SQLite
- Vision: YOLO / VL 分析
- Infra: Ray, Daft

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 准备配置文件

```bash
copy poc\config\poc.yaml.example poc\config\poc.yaml
```

至少检查这些配置项：

- `search.qwen_api_url`
- `search.reranker_api_url`
- `llm.api_key` 或 `llm.api_key_env`
- `gaode.api_key`

## 常用命令

### 启动主界面

```bash
python bin/manage.py start
```

或：

```bash
python -m poc.app.app_ui
```

默认访问地址：

```text
http://localhost:8080
```

### 数据入库

```bash
python -m poc.pipeline.ingest --config poc/config/poc.yaml
```

### 图像向量化

```bash
python -m poc.pipeline.embed --config poc/config/poc.yaml
```

### 可选流程

```bash
python -m poc.pipeline.vl_analyze --config poc/config/poc.yaml
python -m poc.pipeline.label_auto --config poc/config/poc.yaml
python -m poc.pipeline.dataset_build --config poc/config/poc.yaml
python -m poc.pipeline.train_yolov8 --config poc/config/poc.yaml
```

### Agent 查询

```bash
python -m poc.qa.agent_query --question "最近7天车辆闯入告警有多少条"
```

## 运行建议

- 如果没有 `poc/config/poc.yaml`，部分页面与测试会直接失败
- 如果外部 Qwen3-VL / Reranker 服务不可用，检索能力会降级或失败
- 如果未配置 DeepSeek Key，NL2SQL 会回退到规则模式或相关能力不可用
- Windows 环境优先使用 `python bin/manage.py start|stop|restart|status`；该入口会先 bootstrap 本地 `Ray`，再让 NiceGUI 以 connect-only 模式接入
- `ray.address: auto` 表示“连接由 `manage.py` 或外部进程准备好的 Ray 地址”；如果你直接运行 `python -m poc.app.app_ui`，请先保证已有可连接的 Ray 集群，或显式把 `ray.address` 设为 `local`
- 本地 bootstrap 地址会写入 `logs/ray_bootstrap.json`，应用启动时优先读取该地址，避免再次自启一套 Ray
- 如果启动日志反复出现 `127.0.0.1:6379` / `global_state_accessor.cc:505`，优先执行 `ray stop` 和 `python bin/manage.py stop`，再重新启动应用
- 如果命令行查询想启用 `sql_cache` / `trace`，请使用 `python -m poc.qa.agent_query --enable-trace ...`

## 相关文档

- 架构说明：`ARCHITECTURE.md`
- NiceGUI 部署：`DEPLOY_GUIDE.md`
- Qwen 集成：`QWEN_INTEGRATION.md`

## License

MIT
