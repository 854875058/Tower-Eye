"""Page 1: 架构概览"""
from nicegui import ui
from poc.app.pages.shared import (
    create_layout, page_header, config, resolve_path, db_stats, lance_count,
)


@ui.page('/')
def dashboard_page():
    with create_layout('/'):
        page_header('架构概览', '生产级 RAG + Agent + 多模态检索系统全景')

        # ── 实时数据统计 KPI ──
        try:
            _db = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
            stats = db_stats(_db); lc = lance_count()
        except Exception:
            stats = {"assets": 0, "events": 0, "detections": 0, "annotations": 0, "embeddings": 0}; lc = 0

        kpi_items = [
            ('资产总数', f'{stats["assets"]:,}', 'inventory_2', 'blue'),
            ('告警事件', f'{stats["events"]:,}', 'warning', 'amber'),
            ('检测记录', f'{stats["detections"]:,}', 'search', 'emerald'),
            ('向量索引', f'{lc:,}', 'hub', 'purple'),
        ]
        with ui.grid(columns=4).classes('w-full gap-5 mb-6'):
            for title, value, icon, color in kpi_items:
                with ui.element('div').classes('kpi-card'):
                    with ui.row().classes('items-center justify-between'):
                        with ui.column().classes('gap-0.5'):
                            ui.label(title).classes('text-xs font-medium text-slate-400 uppercase tracking-wide')
                            ui.label(value).classes('text-3xl font-bold text-slate-800')
                        with ui.element('div').classes(
                            f'w-14 h-14 rounded-2xl bg-{color}-50 flex items-center justify-center'
                        ):
                            ui.icon(icon).classes(f'text-{color}-500 text-2xl')

        # ── 技术栈卡片 ──
        with ui.grid(columns=5).classes('w-full gap-5 mb-6'):
            tech_cards = [
                ('LangGraph', 'Agent 引擎', '状态机编排 / 自我修正 / 链路追踪', 'psychology', 'blue'),
                ('LanceDB', '向量数据库', '混合检索 / 动态索引 / 亚秒响应', 'storage', 'purple'),
                ('Qwen3-VL', '多模态模型', 'Embedding + Reranker 二阶段', 'auto_awesome', 'amber'),
                ('YOLOv26x', '目标检测', '双引擎标注 / 18类车辆识别', 'videocam', 'emerald'),
                ('Ray + Daft', '分布式计算', 'GPU Actor / TB级批量管线', 'cloud', 'rose'),
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

        # ── 系统架构图（大图，详细） ──
        with ui.element('div').classes('kpi-card mb-6'):
            with ui.row().classes('items-center gap-2 mb-4'):
                ui.icon('account_tree').classes('text-blue-500 text-xl')
                ui.label('系统架构图').classes('font-bold text-lg text-slate-800')
            ui.mermaid('''graph LR
    subgraph UI["前端交互层"]
        direction TB
        NUI["NiceGUI Web UI"]
        QA_Page["智能问答"]
        Search_Page["多模态检索"]
        Label_Page["自动标注"]
        Monitor_Page["系统监控"]
        NUI --- QA_Page
        NUI --- Search_Page
        NUI --- Label_Page
        NUI --- Monitor_Page
    end

    subgraph Agent_Layer["Agent 编排层"]
        direction TB
        Parse["问题解析 NL2SQL"]
        Validate["SQL 验证 安全护栏"]
        Execute["SQL 执行"]
        Format["结果格式化"]
        Fix["自我修正 LLM重写"]
        Parse --> Validate --> Execute --> Format
        Execute -.->|失败| Fix -.->|重试| Validate
    end

    subgraph Search_Layer["检索引擎层"]
        direction TB
        Text_Enc["文本编码"]
        Img_Enc["图像编码"]
        Video_Enc["视频抽帧"]
        Hybrid["混合检索"]
        Rerank["Reranker精排"]
        Text_Enc --> Hybrid
        Img_Enc --> Hybrid
        Video_Enc --> Img_Enc
        Hybrid --> Rerank
    end

    subgraph Model_Layer["AI 模型层"]
        direction TB
        Qwen_Embed["Qwen3-VL Embedding :8010"]
        Qwen_Rerank["Qwen3-VL Reranker :8011"]
        DeepSeek["DeepSeek NL2SQL"]
        YOLO["YOLOv26x 检测"]
        VLLM["VLLM 语义分析"]
    end

    subgraph Storage["数据存储层"]
        direction TB
        LDB[("LanceDB 向量库")]
        SQLite[("SQLite 结构化")]
        FS["文件系统 图片/视频"]
    end

    QA_Page --> Agent_Layer
    Search_Page --> Search_Layer
    Label_Page --> YOLO
    Label_Page --> VLLM
    Agent_Layer --> DeepSeek
    Agent_Layer --> SQLite
    Search_Layer --> Qwen_Embed
    Search_Layer --> Qwen_Rerank
    Search_Layer --> LDB
    Rerank --> LDB
    LDB --> FS''').classes('w-full overflow-x-auto').style(
                'min-height:420px'
            )

        # ── 四大核心能力 ──
        with ui.grid(columns=2).classes('w-full gap-5 mb-6'):
            capabilities = [
                ('智能问答', 'chat', 'blue', 'Agent 驱动的对话式数据分析', [
                    '自然语言转 SQL（NL2SQL）— DeepSeek Chat 驱动',
                    'LangGraph 状态机编排 — 解析→验证→执行→格式化',
                    'SQL 执行失败自动修正重试（最多 3 次）',
                    '安全护栏 — SQL 注入防护 / 表白名单 / 危险操作拦截',
                    '完整链路追踪 — 每步耗时、SQL、结果可回溯',
                ]),
                ('多模态检索', 'search', 'purple', '图文视频统一入口互搜', [
                    'Qwen3-VL Embedding — 图文跨模态向量编码',
                    '混合检索 — 向量相似度 + 关键词匹配，权重可调',
                    'Qwen3-VL Reranker — 二阶段精排重排序',
                    '视频上传自动抽帧 → 关键帧向量检索',
                    '多维过滤 — 时间/地点/类型/设备/置信度',
                ]),
                ('自动标注', 'label', 'amber', '双引擎批量检测与语义分析', [
                    'YOLOv26x 快速目标检测 — 18 类工程车辆识别',
                    'VLLM API 语义分析 — 场景理解与描述生成',
                    '卡尔曼多目标跟踪 — 视频轨迹关联 & ID 分配',
                    '标注结果可编辑 / YOLO 格式导出',
                    '视频逐帧标注 & 智能切片',
                ]),
                ('系统监控', 'monitoring', 'emerald', '全链路可观测性', [
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
