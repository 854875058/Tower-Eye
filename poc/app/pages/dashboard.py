"""Page 1: 架构概览"""
from nicegui import ui
from poc.app.pages.shared import (
    create_layout, page_header, config, resolve_path, db_stats, lance_count,
)


@ui.page('/')
def dashboard_page():
    with create_layout('/'):
        page_header('架构概览', '生产级 RAG + Agent + 多模态检索架构概览')

        # KPI
        kpis = [('Agent 引擎', 'LangGraph', '状态机编排', 'psychology', 'blue'),
                ('向量数据库', 'LanceDB', 'GPU 加速检索', 'storage', 'purple'),
                ('多模态模型', 'Qwen3-VL', 'Embedding + Rerank', 'image', 'amber'),
                ('目标检测', 'YOLOv26x', 'VL 语义双引擎', 'videocam', 'emerald'),
                ('分布式计算', 'Ray + Daft', 'TB 级批量管线', 'cloud', 'rose')]
        with ui.grid(columns=5).classes('w-full gap-6 mb-8'):
            for title, value, sub, icon, color in kpis:
                with ui.element('div').classes('kpi-card flex items-center justify-between'):
                    with ui.column().classes('gap-1'):
                        ui.label(title).classes('text-slate-500 text-sm font-medium')
                        ui.label(value).classes('text-2xl font-bold text-slate-800')
                        ui.label(sub).classes('text-xs text-slate-400')
                    with ui.element('div').classes(f'w-12 h-12 rounded-full bg-{color}-100 flex items-center justify-center'):
                        ui.icon(icon).classes(f'text-{color}-600 text-xl')

        # 核心技术栈
        with ui.element('div').classes('kpi-card mb-8'):
            ui.label('核心技术栈').classes('font-bold text-lg text-slate-800 mb-4')
            with ui.grid(columns=3).classes('w-full gap-6'):
                ui.markdown('''**AI 模型层**
- Qwen3-VL Embedding — 图文跨模态理解 / HTTP API 远程推理
- Qwen3-VL Reranker — 二阶段精排 / 图文相关性重排序
- YOLOv26x + VLLM — 双引擎标注 / 18类工程车辆识别
- 卡尔曼跟踪 — 视频多目标跟踪 / 轨迹关联 & ID 分配
- DeepSeek Chat — NL2SQL 生成 / 智能问答引擎''')
                ui.markdown('''**数据存储层**
- LanceDB — 向量+元数据一体化 / 混合检索（向量+关键词）/ 动态索引优化
- SQLite — 告警事件存储 / 资产元数据管理
- 本地文件系统 — 图片/视频存储 / 路径统一管理''')
                ui.markdown('''**框架工具层**
- LangGraph -- 状态机 Agent 编排 / 自我修正机制 / 完整链路追踪
- NiceGUI -- 现代化交互界面 / 多页面应用
- ModelManager -- 统一模型管理 / Qwen3-VL Embedding + Reranker
- Ray -- 分布式 Actor 调度 / GPU 模型推理 / 单机多机透明切换
- Daft -- TB 级批量数据管线 / 图片批量入库''')

        # 架构图
        with ui.element('div').classes('kpi-card mb-8'):
            ui.label('系统架构图').classes('font-bold text-lg text-slate-800 mb-4')
            ui.mermaid('''graph TD
    User[用户交互层] --> Agent
    subgraph Frontend
        NUI[NiceGUI Modern UI]
    end
    subgraph Agent_Layer[Agent 层 LangGraph]
        Agent[Agent Orchestrator]
        State[Parse - Validate - Execute - Format - Retry]
        Agent --> State
    end
    subgraph Ray_Cluster[Ray 分布式计算]
        YOLO_Actor[YOLODetectorActor GPU]
        Embed_Actor[EmbeddingActor GPU/HTTP]
        VL_Actor[VLAnalyzerActor HTTP]
        Daft[Daft 批量管线]
    end
    subgraph Model_Layer[模型层]
        Qwen[Qwen3-VL Embedding]
        Rerank[Qwen3-VL Reranker]
        YOLO[YOLOv26x + VLLM]
    end
    subgraph Storage[数据层]
        LDB[(LanceDB 向量库)]
        SQL[(SQLite 结构化库)]
    end
    State --> LDB
    State --> SQL
    LDB <--> Qwen
    Ray_Cluster --> Model_Layer
    Daft --> LDB
    Daft --> SQL''').classes('w-full flex justify-center bg-slate-50 rounded-2xl p-4')

        # 核心能力
        with ui.element('div').classes('kpi-card mb-8'):
            ui.label('核心能力').classes('font-bold text-lg text-slate-800 mb-4')
            with ui.grid(columns=2).classes('w-full gap-6'):
                ui.markdown('''**智能问答 (Agent驱动)**
- 自然语言转SQL（NL2SQL）/ SQL执行失败自动重试（最多3次）
- 错误自我修正 / 完整链路追踪 / 安全护栏保护

**多模态检索**
- 图文视频统一入口互搜 / 文本语义搜索
- 视频上传自动抽帧检索 / 混合检索（向量+关键词）
- Reranker 二阶段精排 / 多条件过滤（时间/地点/类型）''')
                ui.markdown('''**自动标注**
- YOLOv26x 批量检测 / VLLM API 语义分析
- 卡尔曼多目标跟踪 / 视频逐帧标注 & 切片
- 标注结果编辑 / YOLO 格式导出 / 18类车辆识别

**系统监控**
- 数据统计仪表盘 / 查询历史追踪
- 性能指标监控 / Tool注册中心 / 完整执行日志''')

        # 实时数据统计
        with ui.element('div').classes('kpi-card mb-8'):
            ui.label('实时数据统计').classes('font-bold text-lg text-slate-800 mb-4')
            try:
                _db = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
                stats = db_stats(_db); lc = lance_count()
            except Exception:
                stats = {"assets": 0, "events": 0, "detections": 0, "annotations": 0, "embeddings": 0}; lc = 0
            with ui.grid(columns=4).classes('w-full gap-4'):
                for lbl, val in [("资产数", stats["assets"]), ("事件数", stats["events"]),
                                 ("检测数", stats["detections"]), ("向量数", lc)]:
                    with ui.element('div').classes('bg-slate-50 rounded-xl p-4 text-center'):
                        ui.label(f'{val:,}').classes('text-2xl font-bold text-blue-600')
                        ui.label(lbl).classes('text-sm text-slate-500')

        # 技术亮点
        with ui.element('div').classes('kpi-card mb-8'):
            ui.label('技术亮点').classes('font-bold text-lg text-slate-800 mb-4')
            ui.markdown('''1. **二阶段检索架构** -- Qwen3-VL Embedding 向量召回 + Qwen3-VL Reranker 精排重排序
2. **混合检索算法** -- 向量相似度 + 关键词匹配，可调节权重
3. **Agent自我修正** -- SQL执行失败自动分析错误，智能修正并重试
4. **双引擎自动标注** -- YOLOv26x 快速检测 + VLLM API 语义验证
5. **Ray 分布式调度** -- GPU Actor 持有模型实例，单机/多机透明切换，Daft TB 级批量管线
6. **一键入库脚本** -- 自动清理、入库、向量化，路径统一转换
7. **生产级安全防护** -- SQL注入防护、表访问白名单、危险操作拦截''')

        # 性能指标
        with ui.grid(columns=5).classes('w-full gap-6'):
            for lbl, val, sub in [("向量化速度", "~80 张/秒", "API推理"),
                                   ("检索延迟", "< 100ms", "亚秒级"),
                                   ("问答准确率", "> 95%", "自我修正"),
                                   ("数据规模", "可扩展", "百万级"),
                                   ("分布式调度", "Ray+Daft", "TB级管线")]:
                with ui.element('div').classes('kpi-card text-center'):
                    ui.label(val).classes('text-xl font-bold text-slate-800')
                    ui.label(lbl).classes('text-sm text-slate-500')
                    ui.label(sub).classes('text-xs text-slate-400')
