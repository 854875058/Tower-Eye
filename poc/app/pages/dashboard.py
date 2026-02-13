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

        # ── 技术栈（紧凑横条卡片） ──
        with ui.element('div').classes(
            'w-full rounded-2xl bg-white border border-slate-100 shadow-sm p-5 mb-6'
        ):
            ui.label('核心技术栈').classes('text-sm font-semibold text-slate-500 mb-3')
            tech_cards = [
                ('LangGraph', 'Agent 引擎', 'psychology', 'blue'),
                ('LanceDB', '向量数据库', 'storage', 'purple'),
                ('Qwen3-VL', '多模态模型', 'auto_awesome', 'amber'),
                ('YOLOv26x', '目标检测', 'videocam', 'emerald'),
                ('Ray + Daft', '分布式计算', 'cloud', 'rose'),
                ('DeepSeek', 'NL2SQL', 'chat', 'sky'),
                ('SQLite', '结构化存储', 'table_chart', 'slate'),
                ('NiceGUI', 'Web 前端', 'web', 'indigo'),
            ]
            with ui.row().classes('w-full flex-wrap gap-3'):
                for name, role, icon, color in tech_cards:
                    with ui.element('div').classes(
                        f'flex items-center gap-2 px-4 py-2 rounded-xl bg-{color}-50 border border-{color}-100'
                    ):
                        ui.icon(icon).classes(f'text-{color}-500 text-base')
                        with ui.column().classes('gap-0'):
                            ui.label(name).classes('text-sm font-bold text-slate-700 leading-tight')
                            ui.label(role).classes('text-[10px] text-slate-400 leading-tight')

        # ── 系统架构图（卡片式分层） ──
        with ui.element('div').classes('w-full rounded-2xl bg-white border border-slate-100 shadow-sm p-6 mb-6'):
            with ui.row().classes('items-center gap-2 mb-5'):
                ui.icon('account_tree').classes('text-blue-500 text-xl')
                ui.label('系统架构图').classes('font-bold text-lg text-slate-800')

            def _arch_layer(title, color, gradient, items):
                """渲染一个架构层：标题条 + 内部节点卡片"""
                with ui.element('div').classes('w-full'):
                    # 层标题
                    with ui.element('div').classes(
                        f'w-full rounded-t-xl bg-gradient-to-r {gradient} px-4 py-2'
                    ):
                        ui.label(title).classes('text-white font-bold text-sm tracking-wide')
                    # 节点卡片区
                    with ui.element('div').classes(
                        f'w-full rounded-b-xl border border-t-0 border-{color}-100 bg-{color}-50/30 p-4'
                    ):
                        with ui.row().classes('w-full flex-wrap gap-3 justify-center'):
                            for icon, name, desc in items:
                                with ui.element('div').classes(
                                    'flex items-center gap-2 bg-white rounded-lg px-3 py-2 shadow-sm border border-slate-100'
                                ).style('min-width:140px'):
                                    ui.icon(icon).classes(f'text-{color}-500 text-lg flex-shrink-0')
                                    with ui.column().classes('gap-0'):
                                        ui.label(name).classes('text-xs font-bold text-slate-700 leading-tight')
                                        ui.label(desc).classes('text-[10px] text-slate-400 leading-tight')

            def _arrow_down():
                with ui.row().classes('w-full justify-center py-1'):
                    ui.icon('keyboard_double_arrow_down').classes('text-slate-300 text-2xl')

            # Layer 1: 前端交互层
            _arch_layer('前端交互层 · NiceGUI Web UI', 'blue', 'from-blue-500 to-blue-600', [
                ('chat', '智能问答', '自然语言提问'),
                ('search', '多模态检索', '文本/图片/视频'),
                ('label', '自动标注', '图片/视频批量'),
                ('desktop_windows', '系统监控', '全链路追踪'),
            ])
            _arrow_down()

            # Layer 2: 业务逻辑层（三列并排）
            with ui.grid(columns=3).classes('w-full gap-3'):
                # 智能问答流程
                with ui.element('div').classes('w-full'):
                    with ui.element('div').classes(
                        'w-full rounded-t-xl bg-gradient-to-r from-blue-400 to-blue-500 px-3 py-1.5'
                    ):
                        ui.label('智能问答 · LangGraph Agent').classes('text-white font-semibold text-xs')
                    with ui.element('div').classes(
                        'w-full rounded-b-xl border border-t-0 border-blue-100 bg-blue-50/30 p-3'
                    ):
                        steps = [
                            ('edit_note', 'NL2SQL 意图解析'),
                            ('schedule', '时间/地区实体提取'),
                            ('code', 'SQL 生成 + 时间注入'),
                            ('shield', '安全护栏验证'),
                            ('play_arrow', 'SQL 执行'),
                            ('autorenew', '失败自我修正 x3'),
                            ('format_list_bulleted', '结果格式化'),
                        ]
                        with ui.column().classes('gap-1'):
                            for i, (ic, st) in enumerate(steps):
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon(ic).classes('text-blue-400 text-sm flex-shrink-0')
                                    ui.label(st).classes('text-[11px] text-slate-600')
                                if i < len(steps) - 1:
                                    with ui.row().classes('pl-2'):
                                        ui.icon('arrow_downward').classes('text-blue-200 text-xs')

                # 多模态检索流程
                with ui.element('div').classes('w-full'):
                    with ui.element('div').classes(
                        'w-full rounded-t-xl bg-gradient-to-r from-purple-400 to-purple-500 px-3 py-1.5'
                    ):
                        ui.label('多模态检索 · 二阶段').classes('text-white font-semibold text-xs')
                    with ui.element('div').classes(
                        'w-full rounded-b-xl border border-t-0 border-purple-100 bg-purple-50/30 p-3'
                    ):
                        steps = [
                            ('call_split', '输入分流 文本/图片/视频'),
                            ('movie', '视频抽帧 OpenCV'),
                            ('auto_awesome', '向量编码 Qwen3-VL'),
                            ('filter_alt', '结构化预过滤 SQLite'),
                            ('manage_search', '混合检索 向量+关键词'),
                            ('filter_list', '后置过滤 asset_id'),
                            ('sort', 'Reranker 精排'),
                        ]
                        with ui.column().classes('gap-1'):
                            for i, (ic, st) in enumerate(steps):
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon(ic).classes('text-purple-400 text-sm flex-shrink-0')
                                    ui.label(st).classes('text-[11px] text-slate-600')
                                if i < len(steps) - 1:
                                    with ui.row().classes('pl-2'):
                                        ui.icon('arrow_downward').classes('text-purple-200 text-xs')

                # 自动标注流程
                with ui.element('div').classes('w-full'):
                    with ui.element('div').classes(
                        'w-full rounded-t-xl bg-gradient-to-r from-amber-400 to-amber-500 px-3 py-1.5'
                    ):
                        ui.label('自动标注 · 双引擎').classes('text-white font-semibold text-xs')
                    with ui.element('div').classes(
                        'w-full rounded-b-xl border border-t-0 border-amber-100 bg-amber-50/30 p-3'
                    ):
                        steps = [
                            ('upload_file', '图片/视频输入'),
                            ('videocam', 'YOLOv26x 目标检测'),
                            ('timeline', '卡尔曼多目标跟踪'),
                            ('auto_awesome', 'VLLM 语义分析'),
                            ('download', '标注导出 YOLO格式'),
                        ]
                        with ui.column().classes('gap-1'):
                            for i, (ic, st) in enumerate(steps):
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon(ic).classes('text-amber-400 text-sm flex-shrink-0')
                                    ui.label(st).classes('text-[11px] text-slate-600')
                                if i < len(steps) - 1:
                                    with ui.row().classes('pl-2'):
                                        ui.icon('arrow_downward').classes('text-amber-200 text-xs')

            _arrow_down()

            # Layer 3: AI 模型服务层
            _arch_layer('AI 模型服务层', 'rose', 'from-rose-400 to-pink-500', [
                ('auto_awesome', 'Qwen3-VL Embed', ':8010 图文跨模态'),
                ('sort', 'Qwen3-VL Rerank', ':8011 精排重排序'),
                ('chat', 'DeepSeek Chat', 'NL2SQL / 自我修正'),
                ('videocam', 'YOLOv26x', '18类目标检测'),
                ('psychology', 'VLLM API', '语义分析'),
            ])
            _arrow_down()

            # Layer 4: 数据存储层 + 入库管线
            with ui.grid(columns=2).classes('w-full gap-3'):
                # 存储层
                with ui.element('div').classes('w-full'):
                    with ui.element('div').classes(
                        'w-full rounded-t-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-4 py-2'
                    ):
                        ui.label('数据存储层').classes('text-white font-bold text-sm')
                    with ui.element('div').classes(
                        'w-full rounded-b-xl border border-t-0 border-emerald-100 bg-emerald-50/30 p-4'
                    ):
                        with ui.row().classes('w-full flex-wrap gap-3 justify-center'):
                            for ic, nm, ds in [
                                ('hub', 'LanceDB', '向量索引'),
                                ('table_chart', 'SQLite', '结构化数据'),
                                ('folder', '文件系统', '图片/视频/告警'),
                            ]:
                                with ui.element('div').classes(
                                    'flex items-center gap-2 bg-white rounded-lg px-3 py-2 shadow-sm border border-slate-100'
                                ).style('min-width:130px'):
                                    ui.icon(ic).classes('text-emerald-500 text-lg flex-shrink-0')
                                    with ui.column().classes('gap-0'):
                                        ui.label(nm).classes('text-xs font-bold text-slate-700 leading-tight')
                                        ui.label(ds).classes('text-[10px] text-slate-400 leading-tight')

                # 入库管线
                with ui.element('div').classes('w-full'):
                    with ui.element('div').classes(
                        'w-full rounded-t-xl bg-gradient-to-r from-slate-500 to-slate-600 px-4 py-2'
                    ):
                        ui.label('数据入库管线 · Ray + Daft').classes('text-white font-bold text-sm')
                    with ui.element('div').classes(
                        'w-full rounded-b-xl border border-t-0 border-slate-200 bg-slate-50 p-4'
                    ):
                        with ui.row().classes('w-full flex-wrap gap-3 justify-center'):
                            for ic, nm, ds in [
                                ('cloud_download', '数据采集', '告警/资产/图片'),
                                ('memory', 'Ray GPU Actor', '分布式调度'),
                                ('transform', 'Daft ETL', 'TB级批量处理'),
                                ('auto_awesome', '批量向量化', 'Qwen3-VL'),
                                ('build', '索引构建', 'LanceDB 入库'),
                            ]:
                                with ui.element('div').classes(
                                    'flex items-center gap-2 bg-white rounded-lg px-3 py-2 shadow-sm border border-slate-100'
                                ).style('min-width:120px'):
                                    ui.icon(ic).classes('text-slate-500 text-lg flex-shrink-0')
                                    with ui.column().classes('gap-0'):
                                        ui.label(nm).classes('text-xs font-bold text-slate-700 leading-tight')
                                        ui.label(ds).classes('text-[10px] text-slate-400 leading-tight')

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
