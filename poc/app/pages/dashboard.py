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
                ('LanceDB', '向量数据库', '混合检索 / 动态索引 / 亚秒响应', 'storage', 'purple'),
                ('Qwen3-VL', '多模态模型', 'Embedding + Reranker 二阶段', 'auto_awesome', 'amber'),
                ('YOLOv26x', '目标检测', '双引擎标注 / 18类车辆识别', 'videocam', 'emerald'),
                ('Ray + Daft', '分布式计算', 'GPU Actor / TB级批量管线', 'cloud', 'rose'),
                ('DeepSeek', 'NL2SQL 引擎', '自然语言转SQL / 自我修正', 'chat', 'sky'),
                ('SQLite', '结构化存储', '事件/资产/告警元数据', 'table_chart', 'slate'),
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
                "fontSize": "13px", "fontFamily": "Inter, sans-serif"
            }}}%%
graph LR
    subgraph UI["前端交互层 · NiceGUI"]
        direction TB
        QA_Page["智能问答<br/>自然语言提问"]
        Search_Page["多模态检索<br/>文本/图片/视频"]
        Label_Page["自动标注<br/>图片/视频批量"]
        Monitor_Page["系统监控<br/>全链路追踪"]
    end

    subgraph QA_Flow["智能问答 · LangGraph Agent"]
        direction TB
        NL["自然语言输入"]
        NL2SQL["NL2SQL 意图解析<br/>DeepSeek Chat"]
        TimeArea["时间/地区/场景<br/>实体自动提取"]
        SQLGen["SQL 生成<br/>注入当前时间"]
        Guard["安全护栏<br/>表白名单/注入防护"]
        Exec["SQL 执行"]
        Fix["自我修正<br/>LLM 分析错误重写"]
        Fmt["结果格式化<br/>表格/图表/摘要"]
        NL --> NL2SQL --> TimeArea --> SQLGen --> Guard --> Exec
        Exec -->|成功| Fmt
        Exec -.->|失败 max 3次| Fix -.-> SQLGen
    end

    subgraph Search_Flow["多模态检索 · 二阶段"]
        direction TB
        Input["输入分流"]
        TxtEnc["文本向量编码<br/>Qwen3-VL Embed"]
        ImgEnc["图像向量编码<br/>Qwen3-VL Embed"]
        VidProc["视频抽帧<br/>OpenCV 中间帧"]
        Filter["结构化预过滤<br/>SQLite 条件筛选"]
        VecSearch["向量检索<br/>LanceDB ANN"]
        Hybrid["混合检索<br/>向量+关键词加权"]
        PostFilter["后置过滤<br/>asset_id 交集"]
        Rerank["Reranker 精排<br/>Qwen3-VL Rerank"]
        Input -->|文本| TxtEnc --> Hybrid
        Input -->|图片| ImgEnc --> VecSearch
        Input -->|视频| VidProc --> ImgEnc
        Input -->|筛选条件| Filter --> PostFilter
        Hybrid --> PostFilter --> Rerank
        VecSearch --> PostFilter
    end

    subgraph Label_Flow["自动标注 · 双引擎"]
        direction TB
        ImgIn["图片/视频输入"]
        YOLO["YOLOv26x 检测<br/>18类工程车辆"]
        Track["卡尔曼跟踪<br/>多目标轨迹关联"]
        VLLM["VLLM 语义分析<br/>场景理解/描述"]
        Export["标注导出<br/>YOLO格式/可编辑"]
        ImgIn --> YOLO --> Track --> Export
        ImgIn --> VLLM --> Export
    end

    subgraph Models["AI 模型服务"]
        direction TB
        QwenEmbed["Qwen3-VL Embedding<br/>:8010 图文跨模态"]
        QwenRerank["Qwen3-VL Reranker<br/>:8011 精排重排序"]
        DS["DeepSeek Chat<br/>NL2SQL/自我修正"]
        YOLOModel["YOLOv26x<br/>目标检测"]
        VLLMModel["VLLM API<br/>语义分析"]
    end

    subgraph Storage["数据存储层"]
        direction TB
        LDB[("LanceDB<br/>向量索引")]
        SQLiteDB[("SQLite<br/>结构化数据")]
        FS["文件系统<br/>图片/视频/告警"]
    end

    subgraph Pipeline["数据入库管线 · Ray + Daft"]
        direction TB
        Ingest["数据采集<br/>告警/资产/图片"]
        RayActor["Ray GPU Actor<br/>分布式调度"]
        DaftETL["Daft ETL<br/>TB级批量处理"]
        Embed["批量向量化<br/>Qwen3-VL Embed"]
        Summarize["图像理解<br/>VLLM 摘要生成"]
        Index["索引构建<br/>LanceDB 入库"]
        Ingest --> RayActor
        Ingest --> DaftETL
        RayActor --> Embed --> Index
        DaftETL --> Summarize --> Index
    end

    QA_Page --> QA_Flow
    Search_Page --> Search_Flow
    Label_Page --> Label_Flow
    Monitor_Page -.-> Storage

    QA_Flow --> DS
    QA_Flow --> SQLiteDB
    Search_Flow --> QwenEmbed
    Search_Flow --> QwenRerank
    Search_Flow --> LDB
    Search_Flow --> SQLiteDB
    Label_Flow --> YOLOModel
    Label_Flow --> VLLMModel
    Pipeline --> QwenEmbed
    Pipeline --> VLLMModel
    Pipeline --> LDB
    Pipeline --> SQLiteDB
    Pipeline --> FS
    LDB --> FS

    style UI fill:#eff6ff,stroke:#3b82f6,stroke-width:2px,color:#1e40af
    style QA_Flow fill:#eef2ff,stroke:#6366f1,stroke-width:2px,color:#3730a3
    style Search_Flow fill:#faf5ff,stroke:#a855f7,stroke-width:2px,color:#6b21a8
    style Label_Flow fill:#fffbeb,stroke:#f59e0b,stroke-width:2px,color:#92400e
    style Models fill:#fdf2f8,stroke:#ec4899,stroke-width:2px,color:#9d174d
    style Storage fill:#ecfdf5,stroke:#10b981,stroke-width:2px,color:#065f46
    style Pipeline fill:#f0f9ff,stroke:#0ea5e9,stroke-width:2px,color:#0c4a6e''').classes('w-full').style(
                'min-height:420px; width:100%;'
            )

        # ── 四大核心能力 ──
        with ui.grid(columns=2).classes('w-full gap-5 mb-6'):
            capabilities = [
                ('智能问答', 'chat', 'blue', 'LangGraph Agent 驱动的对话式数据分析', [
                    'NL2SQL — DeepSeek Chat 自然语言转 SQL',
                    'LangGraph 状态机 — 解析→验证→执行→格式化',
                    '自我修正 — SQL 失败自动分析错误，LLM 重写重试（max 3次）',
                    '安全护栏 — SQL 注入防护 / 表白名单 / 危险操作拦截',
                    '实体提取 — 时间/地区/场景关键词自动识别',
                    '当前时间注入 — 解决 LLM 不知道"现在"的问题',
                    '完整链路追踪 — 每步耗时、SQL、结果可回溯',
                ]),
                ('多模态检索', 'search', 'purple', '图文视频统一入口 · 二阶段检索', [
                    'Qwen3-VL Embedding — 图文跨模态向量编码',
                    '三种输入 — 文本/图片/视频统一检索入口',
                    '视频自动抽帧 — OpenCV 提取中间帧→向量检索',
                    '混合检索 — 向量相似度 + 关键词匹配，权重可调',
                    'Reranker 精排 — Qwen3-VL 二阶段重排序',
                    '结构化预过滤 — SQLite 条件筛选→向量子集检索',
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
                    ('二阶段检索', 'Qwen3-VL Embedding 向量召回 + Reranker 精排重排序'),
                    ('混合检索', '向量相似度 + 关键词匹配，权重可调节'),
                    ('Agent 自我修正', 'SQL 执行失败自动分析错误，LLM 智能修正并重试'),
                    ('双引擎标注', 'YOLOv26x 快速检测 + VLLM API 语义验证'),
                    ('分布式调度', 'Ray GPU Actor + Daft TB 级批量管线'),
                    ('跨平台运维', '统一 Python 脚本，自动适配 Linux/Windows'),
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
