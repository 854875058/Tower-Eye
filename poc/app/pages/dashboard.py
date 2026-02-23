"""Page 1: 架构概览"""
from nicegui import ui
from poc.app.pages.shared import (
    create_layout, page_header, config, resolve_path, db_stats, lance_count,
)


@ui.page('/')
def dashboard_page():
    with create_layout('/'):
        page_header('Tower-Eye 铁塔之眼 · 架构概览', '生产级 RAG + Agent + 多模态检索系统全景')

        # ── 实时数据统计 KPI（彩色渐变卡片） ──
        try:
            _db = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
            stats = db_stats(_db); lc = lance_count()
        except Exception:
            stats = {"assets": 0, "events": 0, "detections": 0, "annotations": 0, "embeddings": 0}; lc = 0

        kpi_items = [
            ('资产总数', f'{stats["assets"]:,}', 'inventory_2', 'blue', 'from-blue-500 to-blue-600'),
            ('告警事件', f'{stats["events"]:,}', 'warning', 'amber', 'from-amber-500 to-orange-500'),
            ('检测记录', f'{stats["detections"]:,}', 'search', 'emerald', 'from-emerald-500 to-teal-500'),
            ('向量索引', f'{lc:,}', 'hub', 'purple', 'from-purple-500 to-violet-500'),
        ]
        with ui.grid(columns=4).classes('w-full gap-5 mb-6'):
            for title, value, icon, color, gradient in kpi_items:
                with ui.element('div').classes(
                    'relative overflow-hidden rounded-2xl bg-white border border-slate-100 shadow-sm hover:shadow-md transition-all'
                ).style('padding:0'):
                    # 顶部渐变色条
                    ui.element('div').classes(f'h-1.5 w-full bg-gradient-to-r {gradient}')
                    with ui.row().classes('items-center justify-between p-5'):
                        with ui.column().classes('gap-0.5'):
                            ui.label(title).classes('text-xs font-medium text-slate-400 uppercase tracking-wide')
                            ui.label(value).classes('text-3xl font-bold text-slate-800')
                        with ui.element('div').classes(
                            f'w-12 h-12 rounded-2xl bg-{color}-50 flex items-center justify-center'
                        ):
                            ui.icon(icon).classes(f'text-{color}-500 text-xl')

        # ── 技术栈卡片（两行） ──
        with ui.grid(columns=5).classes('w-full gap-5 mb-6'):
            tech_cards = [
                ('LangGraph', 'Agent 引擎', '状态机编排 / 自我修正 / 链路追踪', 'psychology', 'blue'),
                ('LanceDB', '统一数据底座', '向量检索 + 结构化存储 / 混合检索 / 动态索引', 'storage', 'purple'),
                ('DuckDB', 'SQL 分析引擎', '进程内嵌入式 / 复杂聚合 / 零部署', 'table_chart', 'slate'),
                ('Qwen3-VL', '多模态模型', 'Embedding + Reranker 二阶段', 'auto_awesome', 'amber'),
                ('YOLOv26x', '目标检测', '双引擎标注 / 18类车辆识别', 'videocam', 'emerald'),
                ('Ray + Daft', '分布式计算', 'GPU Actor / TB级批量管线', 'cloud', 'rose'),
                ('DeepSeek', 'NL2SQL 引擎', '自然语言转SQL / 自我修正', 'chat', 'sky'),
                ('NiceGUI', 'Web 前端', '响应式UI / WebSocket实时', 'web', 'indigo'),
                ('OpenCV', '视频处理', '抽帧 / 卡尔曼跟踪', 'movie', 'teal'),
                ('VLLM', '语义分析', '场景理解 / 描述生成', 'auto_fix_high', 'orange'),
            ]
            for name, role, desc, icon, color in tech_cards:
                with ui.element('div').classes('kpi-card'):
                    with ui.row().classes('items-center gap-3 mb-2'):
                        with ui.element('div').classes(
                            f'w-10 h-10 rounded-xl bg-{color}-50 flex items-center justify-center'
                        ):
                            ui.icon(icon).classes(f'text-{color}-500 text-lg')
                        with ui.column().classes('gap-0'):
                            ui.label(name).classes('text-base font-bold text-slate-800')
                            ui.label(role).classes('text-xs text-slate-400')
                    ui.label(desc).classes('text-xs text-slate-500 leading-relaxed')

        # ── 系统架构图（Mermaid + 自定义主题） ──
        with ui.element('div').classes('kpi-card mb-6 w-full'):
            with ui.row().classes('items-center gap-2 mb-4'):
                ui.icon('account_tree').classes('text-blue-500 text-xl')
                ui.label('系统架构图').classes('font-bold text-lg text-slate-800')
            ui.mermaid('''%%{init: {"theme": "base", "themeVariables": {
                "primaryColor": "#eff6ff", "primaryTextColor": "#1e3a5f",
                "primaryBorderColor": "#93c5fd", "lineColor": "#94a3b8",
                "secondaryColor": "#f0f4ff", "tertiaryColor": "#f8fafc",
                "mainBkg": "#f8fafc", "nodeBorder": "#cbd5e1",
                "clusterBkg": "#f8fafc", "clusterBorder": "#cbd5e1",
                "titleColor": "#334155",
                "fontSize": "15px", "fontFamily": "Inter, sans-serif"
            }}}%%
graph LR
    subgraph UI["前端交互层 · NiceGUI"]
        direction TB
        QA_Page["智能问答"]
        Search_Page["多模态检索"]
        Label_Page["自动标注"]
        Monitor_Page["系统监控"]
    end

    subgraph QA_Flow["智能问答 · LangGraph Agent"]
        direction LR
        NL["自然语言输入"] --> Cache{"SQL缓存池"}
        Cache -->|命中| Exec["DuckDB执行"]
        Cache -->|未命中| NL2SQL["NL2SQL · DeepSeek"] --> SQLGen["SQL生成 · 护栏校验"]
        SQLGen --> Exec
        Exec -->|成功| Fmt["结果格式化"]
        Exec -.->|失败x3| Fix["自我修正"] -.-> SQLGen
    end

    subgraph Search_Flow["多模态检索 · 二阶段"]
        direction LR
        Input["输入分流"]
        Input -->|文本| TxtEnc["文本编码"] --> Hybrid["混合检索"]
        Input -->|图片| ImgEnc["图像编码"] --> VecSearch["向量检索"]
        Input -->|视频| VidProc["视频抽帧"] --> ImgEnc
        Hybrid --> Rerank["Reranker精排"]
        VecSearch --> Rerank
    end

    subgraph Label_Flow["自动标注 · 双引擎"]
        direction LR
        ImgIn["输入"] --> YOLO["YOLOv26x检测"] --> Track["卡尔曼跟踪"] --> Export["标注导出"]
        ImgIn --> VLLM_L["VLLM语义分析"] --> Export
    end

    subgraph Models["AI 模型服务"]
        direction LR
        QwenEmbed["Qwen3-VL Embed :8010"]
        QwenRerank["Qwen3-VL Rerank :8011"]
        DS["DeepSeek Chat"]
        YOLOModel["YOLOv26x"]
        VLLMModel["VLLM API"]
    end

    subgraph Storage["数据存储层 · 一份数据两种查询"]
        direction LR
        LDB[("LanceDB · 统一数据底座")]
        DuckDB[("DuckDB · SQL分析引擎")]
        FS["文件系统"]
        LDB --> DuckDB
    end

    subgraph Pipeline["数据入库 · Ray + Daft"]
        direction LR
        Ingest["数据采集"] --> RayActor["Ray GPU Actor"] --> Embed["批量向量化"] --> Index["索引构建"]
        Ingest --> DaftETL["Daft ETL"] --> Summarize["VLLM摘要"] --> Index
    end

    QA_Page --> QA_Flow
    Search_Page --> Search_Flow
    Label_Page --> Label_Flow
    Monitor_Page -.-> Storage

    QA_Flow --> DS
    QA_Flow --> DuckDB
    Search_Flow --> QwenEmbed
    Search_Flow --> QwenRerank
    Search_Flow --> LDB
    Label_Flow --> YOLOModel
    Label_Flow --> VLLMModel
    Pipeline --> QwenEmbed
    Pipeline --> VLLMModel
    Pipeline --> LDB
    Pipeline --> FS

    style UI fill:#eff6ff,stroke:#3b82f6,stroke-width:2px,color:#1e40af
    style QA_Flow fill:#eef2ff,stroke:#6366f1,stroke-width:2px,color:#3730a3
    style Search_Flow fill:#faf5ff,stroke:#a855f7,stroke-width:2px,color:#6b21a8
    style Label_Flow fill:#fffbeb,stroke:#f59e0b,stroke-width:2px,color:#92400e
    style Models fill:#fdf2f8,stroke:#ec4899,stroke-width:2px,color:#9d174d
    style Storage fill:#ecfdf5,stroke:#10b981,stroke-width:2px,color:#065f46
    style Pipeline fill:#f0f9ff,stroke:#0ea5e9,stroke-width:2px,color:#0c4a6e''').classes('w-full').style(
                'min-height:360px; width:100%;'
            )

        # ── 四大核心能力 ──
        with ui.grid(columns=2).classes('w-full gap-5 mb-6'):
            capabilities = [
                ('智能问答', 'chat', 'blue', 'LangGraph Agent 驱动的对话式数据分析', [
                    'NL2SQL — DeepSeek Chat 自然语言转 DuckDB SQL',
                    'SQL 缓存池 — 相似问题复用历史 SQL 模板，跳过 LLM 调用',
                    'LangGraph 状态机 — 解析->缓存->验证->执行->格式化',
                    '自我修正 — SQL 失败自动分析错误，LLM 重写重试（max 3次）',
                    '安全护栏 — SQL 注入防护 / 表白名单 / 危险操作拦截',
                    '实体提取 — 时间/地区/场景关键词自动识别',
                    '当前时间注入 — 解决 LLM 不知道"现在"的问题',
                    '完整链路追踪 — 每步耗时、SQL、结果可回溯',
                ]),
                ('多模态检索', 'search', 'purple', '图文视频统一入口 · 二阶段检索', [
                    'Qwen3-VL Embedding — 图文跨模态向量编码',
                    '三种输入 — 文本/图片/视频统一检索入口',
                    '视频自动抽帧 — OpenCV 提取中间帧->向量检索',
                    '混合检索 — LanceDB 向量相似度 + 结构化过滤',
                    'Reranker 精排 — Qwen3-VL 二阶段重排序',
                    '统一数据底座 — Lance 表同时支持向量检索和 DuckDB SQL',
                    '多维过滤 — 时间/地点/类型/设备/算法/置信度',
                    '上传即检索 — 图片/视频上传后自动触发',
                ]),
                ('自动标注', 'label', 'amber', '双引擎批量检测与语义分析', [
                    'YOLOv26x — 18 类工程车辆快速目标检测',
                    'VLLM API — 场景理解与描述生成',
                    '卡尔曼多目标跟踪 — 视频轨迹关联 & ID 分配',
                    '标注结果可编辑 / YOLO 格式导出',
                    '视频逐帧标注 & 智能切片',
                ]),
                ('系统监控', 'desktop_windows', 'emerald', '全链路可观测性', [
                    '数据统计仪表盘 — 资产/事件/向量实时计数',
                    '查询历史追踪 — 意图/SQL/耗时/状态',
                    'Tool 注册中心 — 工具列表与调用统计',
                    '性能指标监控 — 响应时间/成功率',
                    '完整执行日志 — Agent 每步可追溯',
                ]),
            ]
            for title, icon, color, subtitle, features in capabilities:
                with ui.element('div').classes('kpi-card'):
                    with ui.row().classes('items-center gap-3 mb-3'):
                        with ui.element('div').classes(
                            f'w-10 h-10 rounded-xl bg-{color}-50 flex items-center justify-center'
                        ):
                            ui.icon(icon).classes(f'text-{color}-500 text-lg')
                        with ui.column().classes('gap-0'):
                            ui.label(title).classes('text-base font-bold text-slate-800')
                            ui.label(subtitle).classes('text-xs text-slate-400')
                    with ui.column().classes('gap-1.5 pl-1'):
                        for feat in features:
                            with ui.row().classes('items-start gap-2'):
                                ui.icon('check_circle').classes(f'text-{color}-400 text-sm mt-0.5 flex-shrink-0')
                                ui.label(feat).classes('text-xs text-slate-600 leading-relaxed')

        # ── 技术亮点 + 性能指标 ──
        with ui.grid(columns='3fr 2fr').classes('w-full gap-5 mb-6'):
            with ui.element('div').classes('kpi-card'):
                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('star').classes('text-amber-500 text-xl')
                    ui.label('技术亮点').classes('font-bold text-lg text-slate-800')
                highlights = [
                    ('统一数据底座', 'LanceDB 一份数据同时支持向量检索和 DuckDB SQL 分析'),
                    ('混合检索', 'LanceDB 向量相似度 + 结构化过滤，一次查询融合两种能力'),
                    ('Agent 自我修正', 'SQL 执行失败自动分析错误，LLM 智能修正并重试'),
                    ('嵌入式引擎', 'DuckDB 进程内 SQL 引擎，零部署零运维，开发生产一致'),
                    ('双引擎标注', 'YOLOv26x 快速检测 + VLLM API 语义验证'),
                    ('分布式调度', 'Ray GPU Actor + Daft TB 级批量管线'),
                    ('安全防护', 'SQL 注入防护 / 表白名单 / 危险操作拦截'),
                ]
                with ui.column().classes('gap-2'):
                    for i, (title, desc) in enumerate(highlights):
                        with ui.row().classes('items-start gap-3'):
                            with ui.element('div').classes(
                                'w-6 h-6 rounded-full bg-blue-50 flex items-center justify-center flex-shrink-0 mt-0.5'
                            ):
                                ui.label(str(i + 1)).classes('text-xs font-bold text-blue-500')
                            with ui.column().classes('gap-0'):
                                ui.label(title).classes('text-sm font-semibold text-slate-700')
                                ui.label(desc).classes('text-xs text-slate-400')

            with ui.element('div').classes('kpi-card'):
                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('speed').classes('text-emerald-500 text-xl')
                    ui.label('性能指标').classes('font-bold text-lg text-slate-800')
                perf_items = [
                    ('向量化速度', '~80 张/秒', 'API 远程推理', 'bolt', 'amber'),
                    ('检索延迟', '< 100ms', 'LanceDB 亚秒级', 'timer', 'blue'),
                    ('问答准确率', '> 95%', 'Agent 自我修正', 'verified', 'emerald'),
                    ('SQL缓存', '< 50ms', '命中时跳过 LLM 调用', 'cached', 'sky'),
                    ('数据规模', '百万级', '可水平扩展', 'database', 'purple'),
                    ('分布式', 'Ray + Daft', 'TB 级批量管线', 'cloud_sync', 'rose'),
                ]
                with ui.column().classes('gap-3'):
                    for label, value, sub, icon, color in perf_items:
                        with ui.row().classes('items-center gap-3'):
                            with ui.element('div').classes(
                                f'w-10 h-10 rounded-xl bg-{color}-50 flex items-center justify-center flex-shrink-0'
                            ):
                                ui.icon(icon).classes(f'text-{color}-500')
                            with ui.column().classes('gap-0 flex-1'):
                                ui.label(label).classes('text-xs text-slate-400')
                                ui.label(value).classes('text-base font-bold text-slate-800')
                            ui.label(sub).classes('text-xs text-slate-400')
