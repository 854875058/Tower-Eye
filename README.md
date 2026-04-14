<div align="center">

# Tower-Eye

**基站智能巡检与多模态问答系统**

*Multimodal retrieval and intelligent Q&A engine for telecom tower inspection*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)](https://python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-1C3C3C?logo=langchain)](https://langchain-ai.github.io/langgraph/)
[![NiceGUI](https://img.shields.io/badge/NiceGUI-Web_UI-5B9BD5)](https://nicegui.io/)
[![DuckDB](https://img.shields.io/badge/DuckDB-SQL-FFF000?logo=duckdb)](https://duckdb.org/)
[![LanceDB](https://img.shields.io/badge/LanceDB-Vector-FF6B00)](https://lancedb.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## Overview

传统基站巡检依赖人工逐条查看告警数据，面对海量图片、视频和结构化告警记录，效率极低且容易遗漏关键缺陷。

Tower-Eye 构建了 **NL2SQL 智能问答** + **多模态向量检索** 双通道融合架构。用户用自然语言提问，系统通过 LangGraph Agent 自动将问题转化为 SQL 查询或向量检索，结合 YOLO 目标检测与视觉语言模型的自动标注能力，实现从 **数据入库** → **智能检索** → **自然语言问答** → **缺陷识别** 的全链路闭环。

```
┌─────────────────────────────────────────────────────────────┐
│                   NiceGUI Web Interface                      │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│  智能问答 │ 多模态检索│ 自动标注  │ 数据看板  │   系统监控      │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│          LangGraph Agent (NL2SQL + Vector Search)            │
├─────────────────────────────────────────────────────────────┤
│     DuckDB (SQL)  │  LanceDB (Vector)  │  SQLite (Trace)    │
└─────────────────────────────────────────────────────────────┘
```

## Key Features

### NL2SQL Intelligent Q&A
基于 LangGraph 状态机的智能问答引擎，支持自然语言 → SQL 自动转换、SQL 自校正重试、缓存池毫秒级响应。集成 DeepSeek LLM 实现高精度语义理解。

### Multimodal Hybrid Search
图像/视频向量嵌入（Qwen3-VL / CLIP）与结构化 SQL 查询双通道融合，支持以图搜图、语义检索、混合排序。单次查询同时命中结构化告警数据与非结构化视觉数据。

### Auto-Labeling Pipeline
集成 YOLO 目标检测与视觉语言模型，自动标注巡检图片和视频中的铁塔缺陷、设备异常。支持批量处理与增量标注。

### SQL Cache & Self-Correction
相似问题自动命中 SQL 缓存池，毫秒级返回。首次查询若 SQL 执行失败，Agent 自动分析错误并重写 SQL，最多重试 3 次。

### Real-Time Monitoring
全链路查询追踪，记录每次问答的解析路径、SQL 生成、执行耗时、结果条数。支持 Trace 回放与性能分析。

### Data Pipeline
告警数据自动入库、图片/视频向量化、元数据提取。支持 CSV 批量导入、增量更新、嵌入模型热切换。

## Tech Stack

```
Web UI                            Agent Layer                      Data Layer
─────────────────                 ─────────────────               ─────────────────
NiceGUI (Python Web)              LangGraph (State Machine)       DuckDB (SQL Engine)
Dashboard / Q&A / Search          DeepSeek (NL2SQL LLM)           LanceDB (Vector Store)
Labeling / Monitoring             Tool Registry (Semantic)        SQLite (Metadata/Trace)

Vision & Embedding                Infrastructure
─────────────────                 ─────────────────
Qwen3-VL / CLIP (Embedding)      Ray (Distributed Compute)
YOLO (Object Detection)           Daft (Data Processing)
Vision-Language Models             FAISS (Index)
```

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    NiceGUI Web UI (:8080)                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐  │
│  │ Dashboard│ │   Q&A    │ │  Search  │ │ Labeling │ │Monitor│  │
│  │  看板     │ │  智能问答 │ │ 多模态检索│ │ 自动标注  │ │ 监控   │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬───┘  │
│       └─────────────┴────────────┴─────────────┴───────────┘      │
├──────────────────────────────────────────────────────────────────┤
│                  LangGraph Agent (State Machine)                  │
│  Parse Question → Cache Check → Generate SQL → Validate →        │
│  Execute → Semantic Enhance → Format Answer                       │
│                        ↕ (fallback)                               │
│              Vector Search (Image/Video Retrieval)                 │
├──────────────────────────────────────────────────────────────────┤
│              Security Layer (SQL Injection Prevention)             │
├───────────┬──────────────┬──────────────┬────────────────────────┤
│  DuckDB   │   LanceDB    │   SQLite     │   YOLO + VL Models    │
│  (SQL)    │   (Vector)   │   (Trace)    │   (Auto-Label)        │
└───────────┴──────────────┴──────────────┴────────────────────────┘
```

## Quick Start

```bash
# 1. Clone
git clone https://github.com/854875058/Tower-Eye.git
cd Tower-Eye

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
# Edit poc/config.py or .env: set LLM API key, model paths

# 4. Start
python bin/manage.py start
# Web UI → http://localhost:8080
```

## Project Structure

```
Tower-Eye/
├── poc/
│   ├── app/                         # NiceGUI pages
│   │   ├── app_ui.py                # Main UI entry
│   │   ├── page_dashboard.py        # Dashboard page
│   │   ├── page_qa.py               # Q&A page
│   │   ├── page_search.py           # Search page
│   │   ├── page_labeling.py         # Auto-labeling page
│   │   └── page_monitoring.py       # Monitoring page
│   ├── qa/                          # Agent & NL2SQL
│   │   ├── agent.py                 # LangGraph agent
│   │   ├── nl2sql.py                # NL → SQL conversion
│   │   ├── tools.py                 # Semantic tool registry
│   │   └── trace.py                 # Query tracing
│   ├── search/                      # Vector search
│   │   ├── vector_search.py         # Hybrid retrieval
│   │   ├── duckdb_engine.py         # SQL execution
│   │   └── model_manager.py         # Embedding model management
│   ├── pipeline/                    # Data pipeline
│   │   ├── ingest.py                # Data ingestion
│   │   ├── embed.py                 # Vectorization
│   │   ├── auto_label.py            # YOLO auto-labeling
│   │   └── train.py                 # Model training
│   └── infra/                       # Infrastructure
│       ├── ray_init.py              # Ray cluster
│       └── metrics.py               # Performance metrics
├── bin/
│   ├── manage.py                    # Service management
│   └── deploy.sh                    # Deployment script
├── data/                            # Runtime data
│   ├── index/                       # FAISS index
│   ├── embeddings/                  # Vector cache
│   └── structured/                  # CSV alert data
└── requirements.txt
```

## API / Usage

| Module | Entry | Description |
|--------|-------|-------------|
| Web UI | `python bin/manage.py start` | 启动 NiceGUI 全功能界面 |
| Q&A | 页面输入自然语言 | 自动转 SQL 查询告警数据 |
| Search | 上传图片或输入文本 | 跨模态向量检索 |
| Labeling | 选择图片批次 | YOLO + VL 自动标注 |
| Pipeline | `python -m poc.pipeline.ingest` | 批量数据入库 |
| Monitor | 页面查看 | 查询追踪与性能分析 |

## License

MIT
