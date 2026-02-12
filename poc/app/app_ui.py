#!/usr/bin/env python3
"""
多模态数据底座 - NiceGUI 前端 (完整版)
移植自 app_v2.py (Streamlit)，5 个页面全功能实现
"""
import sys
import json
import sqlite3
import asyncio
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import ui, app

# ── 后端导入 ──────────────────────────────────────────────────────────────
try:
    from poc.pipeline.utils import load_yaml, connect_db, resolve_path
    from poc.qa.agent import create_agent
    from poc.qa.trace import init_trace_manager, get_trace_manager, QueryTrace
    from poc.qa.tools import init_tool_registry, get_tool_registry
    from poc.search.model_manager import ModelManager
    from poc.search.query import hybrid_search, build_asset_id_filter
    config = load_yaml("poc/config/poc.yaml")
except ImportError as _ie:
    config = {}
    print(f"Warning: backend import failed: {_ie}")

# ── 静态文件服务 ──────────────────────────────────────────────────────────
try:
    app.add_static_files('/warning_img', str(resolve_path('warning_img')))
    app.add_static_files('/warning_file', str(resolve_path('warning_file')))
except Exception:
    pass

# ── 全局单例 ──────────────────────────────────────────────────────────────
_model_manager: Optional[ModelManager] = None
_agent = None
_systems_inited = False


def get_model_manager() -> Optional[ModelManager]:
    global _model_manager
    if _model_manager is None and config:
        print("Loading ModelManager...")
        _model_manager = ModelManager(config)
    return _model_manager


def get_agent():
    global _agent
    if _agent is None and config:
        _agent = create_agent(config, max_retries=3)
    return _agent


def ensure_systems():
    global _systems_inited
    if _systems_inited:
        return
    if not config:
        return
    try:
        trace_db = Path(config.get("paths", {}).get("trace_db_path", "logs/traces.db"))
        trace_db.parent.mkdir(parents=True, exist_ok=True)
        init_trace_manager(db_path=trace_db, enable_file_log=True,
                           log_dir=Path(config.get("paths", {}).get("log_dir", "logs")))
        db_path = config.get("paths", {}).get("db_path", "poc/data/metadata.db")
        if Path(db_path).exists() or resolve_path(db_path).exists():
            init_tool_registry(db_path)
    except Exception as e:
        print(f"init systems error: {e}")
    _systems_inited = True


# ── 数据库辅助 ────────────────────────────────────────────────────────────

def db_stats(db_path) -> Dict[str, int]:
    p = resolve_path(str(db_path)) if not isinstance(db_path, Path) else db_path
    if not p.exists():
        return {"assets": 0, "events": 0, "detections": 0}
    conn = connect_db(p)
    s = {}
    try:
        for t in ("assets", "events", "detections"):
            s[t] = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
    except Exception:
        s = {"assets": 0, "events": 0, "detections": 0}
    finally:
        conn.close()
    return s


def fetch_events_by_asset_ids(db_path, asset_ids: List[str]) -> Dict[str, dict]:
    if not asset_ids:
        return {}
    try:
        conn = connect_db(db_path)
        ph = ", ".join("?" for _ in asset_ids)
        sql = (
            "SELECT e.*, a.file_path, a.file_name "
            "FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id "
            f"WHERE a.asset_id IN ({ph})"
        )
        rows = conn.execute(sql, asset_ids).fetchall()
        conn.close()
        result = {}
        for r in rows:
            rd = dict(r)
            extra = {}
            if rd.get("extra_json"):
                try:
                    extra = json.loads(rd["extra_json"])
                except Exception:
                    pass
            rd["_extra"] = extra
            result[rd["asset_id"]] = rd
        return result
    except Exception as e:
        print(f"DB Error: {e}")
        return {}


def build_result_item(rd: dict, score: float = 0.0) -> dict:
    extra = rd.get("_extra", {})
    video_url = ""
    if extra.get("video_url"):
        video_url = f"/warning_file/{Path(extra['video_url'].split(',')[0].strip()).name}"
    file_path = rd.get("file_path", "")
    img_url = ""
    if file_path:
        img_url = f"/warning_img/{Path(file_path).name}"
    return {
        "asset_id": rd.get("asset_id", ""),
        "score": score,
        "file_path": file_path,
        "img_url": img_url,
        "event_type": rd.get("event_type", ""),
        "alarm_time": rd.get("alarm_time", ""),
        "alarm_level": rd.get("alarm_level") or extra.get("emergency_level", ""),
        "summary": rd.get("summary", ""),
        "description": rd.get("description", ""),
        "address": rd.get("address", ""),
        "device_name": rd.get("device_name", ""),
        "confidence_level": rd.get("confidence_level"),
        "city_name": extra.get("city_name", ""),
        "county_name": extra.get("county_name", ""),
        "town_name": extra.get("town_name", ""),
        "video_url": video_url,
    }


def lance_count() -> int:
    try:
        import lancedb
        ldb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))
        db = lancedb.connect(str(ldb_dir))
        return db.open_table("embeddings").count_rows()
    except Exception:
        return 0


# ── UI 组件 ───────────────────────────────────────────────────────────────

GLOBAL_CSS = '''
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
body { font-family: 'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f8fafc; }
.nicegui-content { padding: 0 !important; margin: 0 !important; max-width: none !important; }
.chat-user { background: #2563eb; color: white; border-radius: 20px 20px 4px 20px; padding: 12px 18px; max-width: 70%; }
.chat-ai { background: white; color: #334155; border: 1px solid #e2e8f0; border-radius: 20px 20px 20px 4px; padding: 12px 18px; max-width: 80%; }
.kpi-card { background: white; border-radius: 16px; padding: 24px; border: 1px solid #e2e8f0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04); transition: all 0.2s; }
.kpi-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); transform: translateY(-2px); }
.result-card { background: white; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden;
               box-shadow: 0 1px 3px rgba(0,0,0,0.04); transition: all 0.3s; }
.result-card:hover { box-shadow: 0 8px 24px rgba(0,0,0,0.1); transform: translateY(-4px); }
'''


def sidebar_item(label: str, icon: str, target: str, current: str):
    active = current == target
    base = 'w-full flex items-center gap-3 p-3 rounded-xl transition-all font-medium cursor-pointer no-underline'
    cls = f'{base} bg-blue-600 text-white shadow-lg shadow-blue-200' if active \
        else f'{base} text-slate-600 hover:bg-slate-100'
    with ui.link(target=target).classes('no-underline w-full'):
        with ui.element('div').classes(cls):
            ui.icon(icon).classes('text-xl')
            ui.label(label).classes('text-sm')
            if active:
                ui.icon('chevron_right').classes('ml-auto text-sm opacity-80')


@contextmanager
def create_layout(active_path: str):
    ui.add_head_html(f'<style>{GLOBAL_CSS}</style>')
    with ui.row().classes('h-screen w-full gap-0 overflow-hidden'):
        # Sidebar
        with ui.column().classes('h-full bg-white border-r border-slate-200 flex flex-col').style('width:256px;min-width:256px'):
            with ui.row().classes('items-center gap-2 px-6 py-6 mb-2'):
                ui.icon('smart_toy').classes('text-3xl text-blue-600')
                ui.label('Multimodal AI').classes('text-xl font-bold text-slate-800')
            with ui.column().classes('flex-1 w-full gap-1 px-3'):
                sidebar_item('架构概览', 'dashboard', '/', active_path)
                sidebar_item('智能问答', 'chat', '/qa', active_path)
                sidebar_item('多模态检索', 'search', '/search', active_path)
                sidebar_item('自动标注', 'label', '/label', active_path)
                sidebar_item('系统监控', 'monitoring', '/monitor', active_path)
            ui.separator().classes('my-2 opacity-30 mx-3')
            with ui.row().classes('items-center gap-3 p-4 mx-3 mb-4 text-red-500 hover:bg-red-50 rounded-xl cursor-pointer'):
                ui.icon('logout').classes('text-xl')
                ui.label('退出登录').classes('text-sm font-medium')
        # Main
        with ui.column().classes('flex-1 h-full bg-slate-50 overflow-hidden'):
            with ui.row().classes('w-full h-14 items-center px-6 bg-white/70 backdrop-blur border-b border-slate-100'):
                ui.space()
                with ui.row().classes('items-center gap-3 bg-slate-50 px-4 py-2 rounded-xl'):
                    with ui.element('div').classes('w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-bold text-xs'):
                        ui.label('AD')
                    ui.label('管理员').classes('text-xs font-semibold text-slate-700')
            with ui.scroll_area().classes('w-full flex-1'):
                with ui.column().classes('max-w-7xl mx-auto w-full p-8'):
                    yield


def page_header(title: str, subtitle: str):
    with ui.column().classes('gap-1 mb-8'):
        ui.label(title).classes('text-2xl font-bold text-slate-900')
        ui.label(subtitle).classes('text-slate-500 text-sm')


# ══════════════════════════════════════════════════════════════════════════
# Page 1: 架构概览
# ══════════════════════════════════════════════════════════════════════════

@ui.page('/')
def dashboard_page():
    with create_layout('/'):
        page_header('架构概览', '生产级 RAG + Agent + 多模态检索架构概览')

        # KPI 卡片
        kpis = [
            ('Agent 引擎', 'LangGraph', '状态机编排', 'psychology', 'blue'),
            ('向量数据库', 'LanceDB', 'GPU 加速检索', 'storage', 'purple'),
            ('多模态模型', 'Qwen3-VL', 'Embedding + Rerank', 'image', 'amber'),
            ('目标检测', 'YOLOv26x', 'VL 语义双引擎', 'videocam', 'emerald'),
        ]
        with ui.grid(columns=4).classes('w-full gap-6 mb-8'):
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
                with ui.column():
                    ui.markdown('''**AI 模型层**
- Qwen3-VL Embedding — 图文跨模态理解
- Qwen3-VL Reranker — 二阶段精排
- YOLOv26x + VLLM — 双引擎标注
- DeepSeek Chat — NL2SQL 生成''')
                with ui.column():
                    ui.markdown('''**数据存储层**
- LanceDB — 向量+元数据一体化
- SQLite — 告警事件结构化存储
- 本地文件系统 — 图片/视频统一管理''')
                with ui.column():
                    ui.markdown('''**框架工具层**
- LangGraph — 状态机 Agent 编排
- NiceGUI — 现代化交互界面
- ModelManager — 统一模型管理
- Kalman Tracker — 多目标跟踪''')

        # 架构图
        with ui.element('div').classes('kpi-card mb-8'):
            with ui.row().classes('items-center gap-2 mb-4'):
                ui.icon('account_tree').classes('text-slate-400')
                ui.label('系统架构图').classes('font-bold text-lg text-slate-800')
            ui.mermaid('''graph TD
    User[用户交互层] --> Agent
    subgraph "前端 Frontend"
        NUI[NiceGUI Modern UI]
    end
    subgraph "Agent 层 LangGraph"
        Agent[Agent Orchestrator]
        State[Parse → Validate → Execute → Format]
        Agent --> State
    end
    subgraph "模型层 Model Inference"
        Qwen[Qwen3-VL Embedding]
        Rerank[Qwen3-VL Reranker]
        YOLO[YOLOv26x + VLLM]
    end
    subgraph "数据层 Storage"
        LDB[(LanceDB 向量库)]
        SQL[(SQLite 结构化库)]
    end
    State --> LDB
    State --> SQL
    LDB <--> Qwen''').classes('w-full flex justify-center bg-slate-50 rounded-2xl p-4')

        # 实时数据统计
        with ui.element('div').classes('kpi-card mb-8'):
            ui.label('实时数据统计').classes('font-bold text-lg text-slate-800 mb-4')
            try:
                db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
                stats = db_stats(db_path)
                lc = lance_count()
            except Exception:
                stats = {"assets": 0, "events": 0, "detections": 0}
                lc = 0
            with ui.grid(columns=4).classes('w-full gap-4'):
                for label, val in [("资产数", stats["assets"]), ("事件数", stats["events"]),
                                   ("检测数", stats["detections"]), ("向量数", lc)]:
                    with ui.element('div').classes('bg-slate-50 rounded-xl p-4 text-center'):
                        ui.label(f'{val:,}').classes('text-2xl font-bold text-blue-600')
                        ui.label(label).classes('text-sm text-slate-500')

        # 性能指标
        with ui.grid(columns=4).classes('w-full gap-6'):
            for label, val, sub in [("向量化速度", "~80 张/秒", "API推理"),
                                     ("检索延迟", "< 100ms", "亚秒级"),
                                     ("问答准确率", "> 95%", "自我修正"),
                                     ("数据规模", "可扩展", "百万级")]:
                with ui.element('div').classes('kpi-card text-center'):
                    ui.label(val).classes('text-xl font-bold text-slate-800')
                    ui.label(label).classes('text-sm text-slate-500')
                    ui.label(sub).classes('text-xs text-slate-400')


# ══════════════════════════════════════════════════════════════════════════
# Page 2: 智能问答
# ══════════════════════════════════════════════════════════════════════════

@ui.page('/qa')
def qa_page():
    with create_layout('/qa'):
        page_header('智能问答', '基于 LangGraph Agent 的自然语言查询，支持 SQL 自我修正')

        # 聊天状态（per-client）
        messages = []
        messages.append({
            "role": "ai",
            "content": "你好！我是多模态智能助手。可以帮你查询告警事件、分析趋势或检索视频。试试下面的快捷问题吧。",
        })

        chat_container = ui.column().classes('w-full')
        input_ref = {'text': ''}

        def render_messages():
            chat_container.clear()
            with chat_container:
                for msg in messages:
                    is_user = msg["role"] == "user"
                    with ui.row().classes(f'w-full {"justify-end" if is_user else "justify-start"} mb-3'):
                        if not is_user:
                            ui.icon('smart_toy').classes('text-2xl text-blue-500 mt-1')
                        with ui.element('div').classes('chat-user' if is_user else 'chat-ai'):
                            # 文本内容
                            if msg.get("content"):
                                ui.markdown(msg["content"]).classes('text-sm')
                            # SQL 代码块
                            if msg.get("sql"):
                                ui.code(msg["sql"], language='sql').classes('w-full mt-2')
                            # 数据表格
                            if msg.get("table_data"):
                                cols = msg["table_data"]["columns"]
                                rows = msg["table_data"]["rows"]
                                with ui.element('div').classes('w-full mt-2 overflow-x-auto'):
                                    tbl = ui.table(
                                        columns=[{"name": c, "label": c, "field": c, "sortable": True} for c in cols],
                                        rows=rows,
                                        pagination={"rowsPerPage": 10},
                                    ).classes('w-full')
                            # 图片网格
                            if msg.get("images"):
                                with ui.row().classes('flex-wrap gap-2 mt-2'):
                                    for img_src in msg["images"][:9]:
                                        ui.image(img_src).classes('w-32 h-24 object-cover rounded-lg')
                            # 视频
                            if msg.get("videos"):
                                for vid_src in msg["videos"][:3]:
                                    ui.video(vid_src).classes('w-full max-w-md mt-2 rounded-lg')
                            # 追问建议
                            if msg.get("suggestions"):
                                with ui.row().classes('flex-wrap gap-2 mt-3'):
                                    for s in msg["suggestions"]:
                                        ui.button(s[:20] + ('...' if len(s) > 20 else ''),
                                                  on_click=lambda s=s: do_ask(s)) \
                                            .props('outline size=sm color=blue-6 rounded-lg')
                        if is_user:
                            ui.icon('person').classes('text-2xl text-slate-400 mt-1')

        async def do_ask(question: str):
            if not question.strip():
                ui.notify('请输入问题', type='warning')
                return
            # 用户消息
            messages.append({"role": "user", "content": question})
            render_messages()
            input_box.value = ''

            # 思考中
            messages.append({"role": "ai", "content": "正在思考..."})
            render_messages()

            try:
                ensure_systems()
                agent = get_agent()
                if not agent:
                    messages[-1] = {"role": "ai", "content": "Agent 未初始化，请检查后端配置。"}
                    render_messages()
                    return

                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: agent.query(question, user_id="nicegui_user")
                )

                # 保存追踪
                try:
                    tm = get_trace_manager()
                    if tm:
                        t = QueryTrace(question=question)
                        t.intent = result.get("intent")
                        t.sql = result.get("sql")
                        t.sql_params = result.get("sql_params")
                        t.status = result.get("status", "error")
                        t.error_message = result.get("error")
                        answer = result.get("answer")
                        if isinstance(answer, dict) and isinstance(answer.get("value"), list):
                            t.result_count = len(answer["value"])
                        step = t.add_step("agent_query")
                        step.finish("success" if result.get("status") == "success" else "error")
                        t.finish(status=t.status)
                        tm.save_trace(t)
                except Exception:
                    pass

                # 构建 AI 回复
                ai_msg: Dict = {"role": "ai", "content": ""}

                if result["status"] == "error":
                    ai_msg["content"] = f"查询失败: {result.get('error', '未知错误')}"
                else:
                    answer = result.get("answer", {})
                    ai_msg["content"] = answer.get("message", "查询完成")
                    ai_msg["sql"] = result.get("sql", "")

                    answer_val = answer.get("value")
                    if isinstance(answer_val, list) and len(answer_val) > 0:
                        if isinstance(answer_val[0], dict):
                            cols = list(answer_val[0].keys())
                            ai_msg["table_data"] = {"columns": cols, "rows": answer_val[:50]}

                            # 提取图片
                            imgs = []
                            for row in answer_val[:9]:
                                fp = row.get("file_path") or row.get("图片路径") or ""
                                if fp:
                                    imgs.append(f"/warning_img/{Path(fp).name}")
                            if imgs:
                                ai_msg["images"] = imgs

                            # 提取视频
                            vids = []
                            for row in answer_val[:3]:
                                ej = row.get("extra_json", "")
                                if isinstance(ej, str) and "video_url" in ej:
                                    try:
                                        ex = json.loads(ej)
                                        vu = ex.get("video_url", "")
                                        if vu:
                                            vids.append(f"/warning_file/{Path(vu.split(',')[0].strip()).name}")
                                    except Exception:
                                        pass
                            if vids:
                                ai_msg["videos"] = vids

                    # 追问建议
                    intent = result.get("intent", "")
                    suggestions = []
                    if intent == "count":
                        if isinstance(answer_val, list) and len(answer_val) > 0:
                            first = answer_val[0]
                            gk = next((k for k, v in first.items() if not isinstance(v, (int, float))), None)
                            if gk:
                                for row in answer_val[:4]:
                                    gv = row.get(gk, "")
                                    if gv:
                                        suggestions.append(f"查询最近20条{gv}的详细信息")
                        if not suggestions:
                            suggestions.append("查询最近20条告警的详细信息")
                    else:
                        suggestions = ["按告警类型统计数量", "按街道统计告警分布", "按设备统计告警次数TOP10"]
                    ai_msg["suggestions"] = suggestions

                messages[-1] = ai_msg
                render_messages()

            except Exception as e:
                messages[-1] = {"role": "ai", "content": f"出错了: {e}"}
                render_messages()

        # 预设快捷问题
        presets = [
            "按街道统计最近30天各类告警数量",
            "查询最近20条车辆闯入告警的详细信息",
            "统计各设备触发告警次数最多的TOP10",
            "查询置信度大于0.9的高置信告警",
        ]
        with ui.row().classes('w-full gap-2 mb-4 flex-wrap'):
            for q in presets:
                ui.button(q[:16] + '...', on_click=lambda q=q: do_ask(q)) \
                    .props('outline size=sm color=blue-6 rounded-lg')

        # 聊天区域
        with ui.element('div').classes('kpi-card p-0 overflow-hidden w-full') \
                .style('height: calc(100vh - 340px); display: flex; flex-direction: column'):
            with ui.scroll_area().classes('flex-1 bg-slate-50 p-6'):
                render_messages()
            with ui.row().classes('p-4 border-t border-slate-100 gap-3 bg-white items-center'):
                input_box = ui.input(placeholder='输入问题，如：按街道统计最近30天各类告警数量') \
                    .classes('flex-1').props('outlined rounded dense')
                input_box.on('keydown.enter', lambda: do_ask(input_box.value))
                ui.button(icon='send', on_click=lambda: do_ask(input_box.value)) \
                    .props('round color=blue-6 unelevated')


# ══════════════════════════════════════════════════════════════════════════
# Page 3: 多模态检索
# ══════════════════════════════════════════════════════════════════════════

@ui.page('/search')
def search_page():
    with create_layout('/search'):
        page_header('多模态检索', '基于 Qwen3-VL + LanceDB 的图文视频混合检索')

        state = {'results': [], 'query_text': '', 'top_k': 10,
                 'vector_weight': 0.7, 'enable_hybrid': True}
        results_container = ui.column().classes('w-full')

        def render_results():
            results_container.clear()
            with results_container:
                if not state['results']:
                    return
                with ui.grid(columns=3).classes('w-full gap-6'):
                    for item in state['results']:
                        with ui.element('div').classes('result-card'):
                            # 图片区域
                            with ui.element('div').classes('w-full h-48 bg-slate-100 relative overflow-hidden'):
                                if item.get('img_url'):
                                    ui.image(item['img_url']).classes('w-full h-full object-cover')
                                else:
                                    with ui.element('div').classes('w-full h-full flex items-center justify-center'):
                                        ui.icon('image_not_supported').classes('text-4xl text-slate-300')
                                if item.get('video_url'):
                                    with ui.element('div').classes('absolute inset-0 flex items-center justify-center bg-black/20'):
                                        ui.icon('play_circle').classes('text-white text-5xl opacity-80')
                                # 分数 badge
                                if item.get('score', 0) > 0:
                                    with ui.element('div').classes('absolute top-2 right-2 bg-blue-600 text-white text-xs px-2 py-1 rounded-lg'):
                                        ui.label(f"{item['score']:.3f}")
                            # 内容区域
                            with ui.column().classes('p-4 gap-2'):
                                ui.label(item.get('event_type', '未知事件')).classes('font-bold text-slate-800 truncate')
                                ui.label(item.get('description') or item.get('summary') or '暂无描述') \
                                    .classes('text-sm text-slate-500 line-clamp-2').style('display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden')
                                with ui.row().classes('items-center gap-2 mt-1'):
                                    if item.get('city_name') or item.get('town_name'):
                                        loc = ' '.join(filter(None, [item.get('city_name'), item.get('county_name'), item.get('town_name')]))
                                        with ui.row().classes('items-center gap-1'):
                                            ui.icon('place').classes('text-sm text-slate-400')
                                            ui.label(loc).classes('text-xs text-slate-400')
                                    ui.space()
                                    if item.get('alarm_time'):
                                        ui.label(str(item['alarm_time'])[:10]).classes('text-xs text-slate-400')
                                # 视频播放
                                if item.get('video_url'):
                                    ui.video(item['video_url']).classes('w-full rounded-lg mt-2')

        async def do_search():
            q = state['query_text']
            if not q:
                ui.notify('请输入检索关键词', type='warning')
                return
            ui.notify('检索中...', type='info')
            try:
                mgr = get_model_manager()
                if not mgr:
                    ui.notify('模型未加载', type='negative')
                    return
                import lancedb
                ldb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))
                db = lancedb.connect(str(ldb_dir))
                table = db.open_table("embeddings")

                query_vec = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: mgr.encode_text(q).astype("float32")
                )

                top_k = state['top_k']
                if state['enable_hybrid']:
                    results_df = hybrid_search(table, query_vec, query_text=q, top_k=top_k,
                                               vector_weight=state['vector_weight'],
                                               keyword_weight=round(1.0 - state['vector_weight'], 1))
                else:
                    results_df = table.search(query_vec.tolist()).limit(top_k).to_pandas()

                asset_ids = results_df["asset_id"].tolist()
                db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
                details = fetch_events_by_asset_ids(db_path, asset_ids)

                formatted = []
                for _, row in results_df.iterrows():
                    aid = row["asset_id"]
                    score = float(row.get("hybrid_score", row.get("_distance", 0)))
                    rd = details.get(aid, {"_extra": {}})
                    formatted.append(build_result_item(rd, score))

                # Reranker
                search_cfg = config.get("search", {})
                if search_cfg.get("reranker_enabled") and q:
                    formatted = mgr.rerank(q, formatted, top_k=top_k)
                else:
                    formatted = formatted[:top_k]

                state['results'] = formatted
                ui.notify(f'找到 {len(formatted)} 条结果', type='positive')
                render_results()
            except Exception as e:
                ui.notify(f'检索失败: {e}', type='negative')
                print(traceback.format_exc())

        # 搜索栏
        with ui.element('div').classes('kpi-card flex items-center gap-4 mb-6 w-full'):
            ui.icon('search').classes('text-slate-400 text-xl')
            search_input = ui.input(placeholder='输入关键词搜索，例如：车辆闯入...') \
                .classes('flex-1').props('borderless dense')
            search_input.bind_value(state, 'query_text')
            search_input.on('keydown.enter', do_search)
            ui.separator().props('vertical').classes('h-8')
            ui.button('搜索', on_click=do_search).props('unelevated color=blue-6 rounded')

        # 参数面板
        with ui.expansion('检索参数', icon='tune').classes('w-full mb-6 bg-white rounded-xl'):
            with ui.grid(columns=3).classes('w-full gap-4 p-4'):
                ui.number('返回数量', min=1, max=50, value=10, step=1) \
                    .bind_value(state, 'top_k').classes('w-full')
                ui.switch('混合检索').bind_value(state, 'enable_hybrid')
                ui.slider(min=0, max=1, step=0.1, value=0.7) \
                    .bind_value(state, 'vector_weight') \
                    .props('label-always label="向量权重"')

        # 结果区域
        render_results()


# ══════════════════════════════════════════════════════════════════════════
# Page 4: 自动标注
# ══════════════════════════════════════════════════════════════════════════

@ui.page('/label')
def label_page():
    with create_layout('/label'):
        page_header('自动标注', 'YOLOv26x + VL 语义双引擎自动检测与标注')

        label_state = {
            'files': [],
            'current_idx': 0,
            'detections': [],
            'engine': None,
            'stats': {'total': 0, 'auto': 0, 'by_class': {}},
        }
        preview_container = ui.column().classes('w-full')
        stats_container = ui.row().classes('w-full gap-4')

        def init_engine():
            if label_state['engine'] is not None:
                return label_state['engine']
            try:
                from poc.pipeline.auto_label_engine import AutoLabelEngine
                engine = AutoLabelEngine()
                label_state['engine'] = engine
                return engine
            except Exception as e:
                ui.notify(f'标注引擎初始化失败: {e}', type='negative')
                return None

        def scan_files(directory: str):
            p = resolve_path(directory)
            if not p.exists():
                ui.notify(f'目录不存在: {p}', type='warning')
                return
            exts = {'.jpg', '.jpeg', '.png', '.bmp'}
            files = sorted([f for f in p.iterdir() if f.suffix.lower() in exts])
            label_state['files'] = files
            label_state['current_idx'] = 0
            label_state['detections'] = []
            ui.notify(f'扫描到 {len(files)} 个文件', type='positive')
            show_current()

        def show_current():
            preview_container.clear()
            files = label_state['files']
            if not files:
                with preview_container:
                    ui.label('暂无文件，请先扫描目录').classes('text-slate-400')
                return
            idx = label_state['current_idx']
            fp = files[idx]
            dets = label_state['detections']

            with preview_container:
                ui.label(f'{fp.name}  ({idx + 1}/{len(files)})').classes('font-bold text-slate-700 mb-2')
                # 如果有检测结果，用 OpenCV 绘制标注框后展示
                if dets:
                    try:
                        import cv2
                        import numpy as np
                        img = cv2.imread(str(fp))
                        h, w = img.shape[:2]
                        for d in dets:
                            bbox = d['bbox']
                            # 归一化坐标转像素
                            if all(0 <= v <= 1.0 for v in bbox):
                                x1, y1, x2, y2 = int(bbox[0]*w), int(bbox[1]*h), int(bbox[2]*w), int(bbox[3]*h)
                            else:
                                x1, y1, x2, y2 = [int(v) for v in bbox]
                            color = (0, 255, 0)
                            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                            label_text = f"{d.get('class', '?')} {d.get('confidence', 0):.2f}"
                            cv2.putText(img, label_text, (x1, max(y1 - 8, 12)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                        # 转为 base64
                        import base64
                        _, buf = cv2.imencode('.jpg', img)
                        b64 = base64.b64encode(buf).decode()
                        ui.image(f'data:image/jpeg;base64,{b64}').classes('w-full max-w-2xl rounded-xl')
                    except Exception:
                        # fallback: 直接显示原图
                        ui.image(f'/warning_img/{fp.name}').classes('w-full max-w-2xl rounded-xl')
                else:
                    ui.image(f'/warning_img/{fp.name}').classes('w-full max-w-2xl rounded-xl')

                # 检测结果列表
                if dets:
                    with ui.element('div').classes('mt-4 w-full'):
                        ui.label(f'检测到 {len(dets)} 个目标').classes('font-semibold text-slate-700 mb-2')
                        tbl_rows = [{"类别": d.get("class", ""), "置信度": f"{d.get('confidence', 0):.2f}",
                                     "边界框": str(d.get("bbox", []))} for d in dets]
                        ui.table(
                            columns=[
                                {"name": "类别", "label": "类别", "field": "类别"},
                                {"name": "置信度", "label": "置信度", "field": "置信度"},
                                {"name": "边界框", "label": "边界框", "field": "边界框"},
                            ],
                            rows=tbl_rows,
                        ).classes('w-full')

        def update_stats():
            stats_container.clear()
            s = label_state['stats']
            with stats_container:
                for lbl, val in [("总检测数", s['total']), ("自动标注", s['auto'])]:
                    with ui.element('div').classes('kpi-card text-center flex-1'):
                        ui.label(str(val)).classes('text-2xl font-bold text-blue-600')
                        ui.label(lbl).classes('text-sm text-slate-500')
                if s['by_class']:
                    with ui.element('div').classes('kpi-card flex-1'):
                        ui.label('按类别').classes('text-sm text-slate-500 mb-1')
                        for cls, cnt in s['by_class'].items():
                            ui.label(f'{cls}: {cnt}').classes('text-sm text-slate-700')

        async def detect_current():
            engine = init_engine()
            if not engine:
                return
            files = label_state['files']
            if not files:
                ui.notify('请先扫描目录', type='warning')
                return
            fp = files[label_state['current_idx']]
            ui.notify(f'正在检测 {fp.name}...', type='info')
            try:
                dets = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: engine.detect_image(str(fp))
                )
                label_state['detections'] = dets
                # 更新统计
                label_state['stats']['total'] += len(dets)
                label_state['stats']['auto'] += len(dets)
                for d in dets:
                    cls = d.get('class', 'unknown')
                    label_state['stats']['by_class'][cls] = label_state['stats']['by_class'].get(cls, 0) + 1
                ui.notify(f'检测到 {len(dets)} 个目标', type='positive')
                show_current()
                update_stats()
            except Exception as e:
                ui.notify(f'检测失败: {e}', type='negative')

        def nav(delta: int):
            files = label_state['files']
            if not files:
                return
            label_state['current_idx'] = max(0, min(len(files) - 1, label_state['current_idx'] + delta))
            label_state['detections'] = []
            show_current()

        # 控制面板
        with ui.element('div').classes('kpi-card mb-6 w-full'):
            with ui.row().classes('items-center gap-4 w-full'):
                dir_input = ui.input('图片目录', value='warning_img', placeholder='warning_img') \
                    .classes('flex-1').props('outlined dense')
                ui.button('扫描目录', on_click=lambda: scan_files(dir_input.value)) \
                    .props('unelevated color=blue-6 rounded')
                ui.button('自动检测', on_click=detect_current) \
                    .props('unelevated color=teal-6 rounded')
            with ui.row().classes('items-center gap-2 mt-3'):
                ui.button(icon='navigate_before', on_click=lambda: nav(-1)).props('flat round')
                ui.button(icon='navigate_next', on_click=lambda: nav(1)).props('flat round')

        # 统计
        update_stats()

        # 预览
        show_current()


# ══════════════════════════════════════════════════════════════════════════
# Page 5: 系统监控
# ══════════════════════════════════════════════════════════════════════════

@ui.page('/monitor')
def monitor_page():
    with create_layout('/monitor'):
        page_header('系统监控', '数据统计、查询追踪与 Tool 注册中心')

        ensure_systems()

        # 数据统计 KPI
        try:
            db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
            stats = db_stats(db_path)
            lc = lance_count()
        except Exception:
            stats = {"assets": 0, "events": 0, "detections": 0}
            lc = 0

        ui.label('数据统计').classes('font-bold text-lg text-slate-800 mb-3')
        with ui.grid(columns=4).classes('w-full gap-6 mb-8'):
            for label, val, icon in [("资产数", stats["assets"], "inventory_2"),
                                      ("事件数", stats["events"], "warning"),
                                      ("检测数", stats["detections"], "center_focus_strong"),
                                      ("向量数", lc, "hub")]:
                with ui.element('div').classes('kpi-card flex items-center gap-4'):
                    with ui.element('div').classes('w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center'):
                        ui.icon(icon).classes('text-blue-600')
                    with ui.column().classes('gap-0'):
                        ui.label(f'{val:,}').classes('text-xl font-bold text-slate-800')
                        ui.label(label).classes('text-sm text-slate-500')

        # 查询追踪统计
        ui.label('查询追踪统计').classes('font-bold text-lg text-slate-800 mb-3')
        tm = get_trace_manager()
        if tm:
            trace_stats = tm.get_statistics()
            total = trace_stats.get("total_queries", 0)
            success = trace_stats.get("success_count", 0)
            error = trace_stats.get("error_count", 0)
            rate = (success / total * 100) if total > 0 else 0
            avg_ms = trace_stats.get("avg_duration_ms", 0)

            with ui.grid(columns=5).classes('w-full gap-4 mb-6'):
                for label, val in [("总查询数", str(total)), ("成功数", str(success)),
                                    ("失败数", str(error)), ("成功率", f"{rate:.1f}%"),
                                    ("平均耗时", f"{avg_ms:.0f}ms")]:
                    with ui.element('div').classes('kpi-card text-center'):
                        ui.label(val).classes('text-xl font-bold text-slate-800')
                        ui.label(label).classes('text-sm text-slate-500')

            # 最近查询记录
            ui.label('最近查询记录').classes('font-bold text-lg text-slate-800 mb-3')
            recent = tm.query_traces(limit=20)
            if recent:
                rows = []
                for r in recent:
                    rows.append({
                        "时间": str(r.get("timestamp", ""))[:19],
                        "问题": str(r.get("question", ""))[:40],
                        "意图": str(r.get("intent", "")),
                        "状态": str(r.get("status", "")),
                        "耗时ms": f"{r.get('total_duration_ms', 0):.0f}" if r.get('total_duration_ms') else "-",
                    })
                cols = [{"name": c, "label": c, "field": c, "sortable": True} for c in rows[0].keys()]
                ui.table(columns=cols, rows=rows, pagination={"rowsPerPage": 10}).classes('w-full mb-8')
            else:
                ui.label('暂无查询记录').classes('text-slate-400 mb-8')
        else:
            ui.label('追踪系统未启用').classes('text-slate-400 mb-8')

        # Tool 注册中心
        ui.label('Tool 注册中心').classes('font-bold text-lg text-slate-800 mb-3')
        tr = get_tool_registry()
        if tr:
            tools = tr.list_tools()
            if tools:
                tool_rows = [{"名称": t["name"], "描述": t["description"]} for t in tools]
                tool_cols = [{"name": c, "label": c, "field": c} for c in tool_rows[0].keys()]
                ui.table(columns=tool_cols, rows=tool_rows).classes('w-full')
            else:
                ui.label('无已注册 Tool').classes('text-slate-400')
        else:
            ui.label('Tool 注册中心未初始化').classes('text-slate-400')


# ══════════════════════════════════════════════════════════════════════════
# 启动
# ══════════════════════════════════════════════════════════════════════════

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="0.0.0.0",
        port=8080,
        title="多模态数据底座",
        favicon="🏗️",
        storage_secret="multimodal-ai-secret",
        reload=False,
    )
