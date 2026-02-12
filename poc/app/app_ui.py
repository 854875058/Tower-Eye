#!/usr/bin/env python3
"""
多模态数据底座 - NiceGUI 前端 (完整版)
移植自 app_v2.py (Streamlit)，5 个页面全功能实现
"""
import re
import sys
import json
import sqlite3
import asyncio
import hashlib
import tempfile
import traceback
import requests
from contextlib import contextmanager
from datetime import datetime, date, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import ui, app, events

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


# ══════════════════════════════════════════════════════════════════════════
# SQLite 辅助函数（完整移植自 app_v2.py）
# ══════════════════════════════════════════════════════════════════════════

def build_sqlite_filter(filters: dict) -> Tuple[str, list]:
    clauses, params = [], []
    mapping = [
        ("event_type", "e.event_type LIKE ?", lambda v: f"%{v}%"),
        ("city_name", "e.extra_json LIKE ?", lambda v: f'%"city_name": "{v}"%'),
        ("county_name", "e.extra_json LIKE ?", lambda v: f'%"county_name": "{v}"%'),
        ("town_name", "e.extra_json LIKE ?", lambda v: f'%"town_name": "{v}"%'),
        ("device_name", "e.device_name LIKE ?", lambda v: f"%{v}%"),
        ("alarm_level", "e.extra_json LIKE ?", lambda v: f'%"emergency_level": "{v}"%'),
        ("order_status", "e.extra_json LIKE ?", lambda v: f'%"order_status": "{v}"%'),
        ("algorithm_name", "e.extra_json LIKE ?", lambda v: f'%{v}%'),
        ("algorithm_code", "e.extra_json LIKE ?", lambda v: f'%"algorithm_code": "{v}"%'),
        ("device_code", "e.extra_json LIKE ?", lambda v: f'%"device_code": "{v}"%'),
        ("importance_level", "e.extra_json LIKE ?", lambda v: f'%"importance_level": "{v}"%'),
        ("warning_source_name", "e.extra_json LIKE ?", lambda v: f'%"warning_source_name": "{v}"%'),
        ("alarm_body", "e.extra_json LIKE ?", lambda v: f'%"alarm_body": "{v}"%'),
        ("tenant_name", "e.extra_json LIKE ?", lambda v: f'%"tenant_name": "{v}"%'),
        ("channel_name", "e.extra_json LIKE ?", lambda v: f'%"channel_name": "{v}"%'),
    ]
    for key, clause, fmt in mapping:
        if filters.get(key):
            clauses.append(clause)
            params.append(fmt(filters[key]))
    if filters.get("confidence_min") is not None:
        clauses.append("e.confidence_level >= ?"); params.append(filters["confidence_min"])
    if filters.get("confidence_max") is not None:
        clauses.append("e.confidence_level <= ?"); params.append(filters["confidence_max"])
    if filters.get("start_time"):
        clauses.append("e.alarm_time >= ?"); params.append(filters["start_time"])
    if filters.get("end_time"):
        clauses.append("e.alarm_time <= ?"); params.append(filters["end_time"])
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def _inject_sql_filters(sql: str, filters: Dict) -> str:
    conditions = []
    simple = [("event_type", "e.event_type = '{}'"), ("alarm_level", "e.alarm_level = '{}'"),
              ("order_status", "e.order_status = '{}'"), ("city_name", "e.city_name = '{}'"),
              ("county_name", "e.county_name = '{}'"), ("town_name", "e.town_name = '{}'")]
    for k, tpl in simple:
        if filters.get(k): conditions.append(tpl.format(filters[k]))
    if filters.get("device_name"): conditions.append(f"e.device_name LIKE '%{filters['device_name']}%'")
    if filters.get("algorithm_name"): conditions.append(f"e.algorithm_name LIKE '%{filters['algorithm_name']}%'")
    if filters.get("confidence_min") is not None: conditions.append(f"e.confidence_level >= {filters['confidence_min']}")
    if filters.get("confidence_max") is not None: conditions.append(f"e.confidence_level <= {filters['confidence_max']}")
    if filters.get("start_time"): conditions.append(f"e.alarm_time >= '{filters['start_time']}'")
    if filters.get("end_time"): conditions.append(f"e.alarm_time <= '{filters['end_time']}'")
    if not conditions: return sql
    extra = " AND ".join(conditions)
    tail = re.search(r'\b(GROUP\s+BY|ORDER\s+BY|LIMIT)\b', sql, re.IGNORECASE)
    where = re.search(r'\bWHERE\b', sql, re.IGNORECASE)
    if where:
        pos = tail.start() if tail and tail.start() > where.end() else len(sql)
        return sql[:pos] + f"AND {extra} " + sql[pos:]
    pos = tail.start() if tail else len(sql)
    return sql[:pos] + f"WHERE {extra} " + sql[pos:]


def db_stats(db_path) -> Dict[str, int]:
    p = resolve_path(str(db_path)) if not isinstance(db_path, Path) else db_path
    if not p.exists():
        return {"assets": 0, "events": 0, "detections": 0, "annotations": 0, "embeddings": 0}
    conn = connect_db(p)
    s = {}
    try:
        for t in ("assets", "events", "detections", "annotations", "embeddings"):
            s[t] = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
    except Exception:
        s = {"assets": 0, "events": 0, "detections": 0, "annotations": 0, "embeddings": 0}
    finally:
        conn.close()
    return s


def lance_count() -> int:
    try:
        import lancedb
        ldb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))
        return lancedb.connect(str(ldb_dir)).open_table("embeddings").count_rows()
    except Exception:
        return 0


def fetch_events_by_asset_ids(db_path, asset_ids: List[str]) -> Dict[str, dict]:
    if not asset_ids: return {}
    try:
        conn = connect_db(db_path)
        ph = ", ".join("?" for _ in asset_ids)
        rows = conn.execute(
            f"SELECT e.*, a.file_path, a.file_name FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id WHERE a.asset_id IN ({ph})",
            asset_ids).fetchall()
        conn.close()
        result = {}
        for r in rows:
            rd = dict(r)
            extra = {}
            if rd.get("extra_json"):
                try: extra = json.loads(rd["extra_json"])
                except Exception: pass
            rd["_extra"] = extra
            result[rd["asset_id"]] = rd
        return result
    except Exception:
        return {}


def build_result_item(rd: dict, score: float = 0.0) -> dict:
    extra = rd.get("_extra", {})
    video_url = ""
    if extra.get("video_url"):
        video_url = f"/warning_file/{Path(extra['video_url'].split(',')[0].strip()).name}"
    fp = rd.get("file_path", "")
    fn = rd.get("file_name", "")
    img_url = f"/warning_img/{Path(fp).name}" if fp else ""
    return {
        "asset_id": rd.get("asset_id", ""), "score": score,
        "file_path": fp, "file_name": fn, "img_url": img_url,
        "event_type": rd.get("event_type", ""), "alarm_time": rd.get("alarm_time", ""),
        "alarm_level": rd.get("alarm_level") or extra.get("emergency_level", ""),
        "summary": rd.get("summary", ""), "description": rd.get("description", ""),
        "address": rd.get("address", ""), "device_name": rd.get("device_name", ""),
        "confidence_level": rd.get("confidence_level"),
        "province_name": extra.get("province_name", ""),
        "city_name": extra.get("city_name", ""), "county_name": extra.get("county_name", ""),
        "town_name": extra.get("town_name", ""), "device_code": extra.get("device_code", ""),
        "algorithm_name": extra.get("algorithm_name", ""),
        "order_status": extra.get("order_status", ""), "video_url": video_url,
        "file_img_url_src": fp, "file_img_url_icon": "",
    }


def get_dropdown_options(db_path_str: str) -> Dict[str, List[str]]:
    p = Path(db_path_str)
    if not p.exists(): return {}
    conn = connect_db(p)
    fields = ["tenant_name", "channel_name", "device_name", "device_code",
              "algorithm_name", "algorithm_code", "warning_source_name",
              "warning_type_name", "alarm_body", "importance_level"]
    result = {}
    for f in fields:
        try:
            rows = conn.execute(
                f"SELECT DISTINCT json_extract(extra_json, '$.{f}') AS val FROM events "
                f"WHERE json_extract(extra_json, '$.{f}') IS NOT NULL AND json_extract(extra_json, '$.{f}') != '' ORDER BY val"
            ).fetchall()
            vals = [r["val"] for r in rows]
            if vals: result[f] = vals
        except Exception: pass
    conn.close()
    return result


def get_area_hierarchy(db_path_str: str) -> Dict:
    p = Path(db_path_str)
    empty = {"cities": [], "county_by_city": {}, "town_by_county": {}}
    if not p.exists(): return empty
    conn = connect_db(p)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "city_name" not in cols:
        rows = conn.execute(
            "SELECT DISTINCT json_extract(extra_json,'$.city_name') AS city,"
            "json_extract(extra_json,'$.county_name') AS county,"
            "json_extract(extra_json,'$.town_name') AS town "
            "FROM events WHERE json_extract(extra_json,'$.city_name') IS NOT NULL").fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT city_name AS city, county_name AS county, town_name AS town "
            "FROM events WHERE city_name IS NOT NULL AND city_name != ''").fetchall()
    conn.close()
    cities = set(); cbc: Dict[str, set] = {}; tbc: Dict[str, set] = {}
    for r in rows:
        city, county, town = r["city"] or "", r["county"] or "", r["town"] or ""
        if city:
            cities.add(city)
            if county:
                cbc.setdefault(city, set()).add(county)
                if town: tbc.setdefault(county, set()).add(town)
    return {"cities": sorted(cities),
            "county_by_city": {k: sorted(v) for k, v in cbc.items()},
            "town_by_county": {k: sorted(v) for k, v in tbc.items()}}


def geocode_address(address: str, api_key: str, geocode_url: str) -> Optional[Tuple[float, float, str]]:
    try:
        resp = requests.get(geocode_url, params={"key": api_key, "address": address, "output": "JSON"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "1" or not data.get("geocodes"): return None
        geo = data["geocodes"][0]
        lon_s, lat_s = geo["location"].split(",")
        return float(lat_s), float(lon_s), geo.get("formatted_address", address)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════
# UI 组件 & 布局
# ══════════════════════════════════════════════════════════════════════════

GLOBAL_CSS = '''
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
body { font-family: 'Inter','PingFang SC','Microsoft YaHei',sans-serif; background:#f8fafc; }
.nicegui-content { padding:0!important; margin:0!important; max-width:none!important; }
.chat-user { background:#2563eb; color:white; border-radius:20px 20px 4px 20px; padding:12px 18px; max-width:70%; }
.chat-ai { background:white; color:#334155; border:1px solid #e2e8f0; border-radius:20px 20px 20px 4px; padding:12px 18px; max-width:85%; }
.kpi-card { background:white; border-radius:16px; padding:24px; border:1px solid #e2e8f0;
            box-shadow:0 1px 3px rgba(0,0,0,0.04); transition:all 0.2s; }
.kpi-card:hover { box-shadow:0 4px 12px rgba(0,0,0,0.08); transform:translateY(-2px); }
.result-card { background:white; border-radius:16px; border:1px solid #e2e8f0; overflow:hidden;
               box-shadow:0 1px 3px rgba(0,0,0,0.04); transition:all 0.3s; }
.result-card:hover { box-shadow:0 8px 24px rgba(0,0,0,0.1); transform:translateY(-4px); }
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
            # 系统状态
            with ui.column().classes('px-4 mb-4 gap-1'):
                ui.label('系统状态').classes('text-xs font-semibold text-slate-400 mb-1')
                for txt in ['Agent 已就绪', '混合检索已启用', 'Reranker 已启用']:
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('check_circle').classes('text-green-500 text-sm')
                        ui.label(txt).classes('text-xs text-slate-600')
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

        # KPI
        kpis = [('Agent 引擎', 'LangGraph', '状态机编排', 'psychology', 'blue'),
                ('向量数据库', 'LanceDB', 'GPU 加速检索', 'storage', 'purple'),
                ('多模态模型', 'Qwen3-VL', 'Embedding + Rerank', 'image', 'amber'),
                ('目标检测', 'YOLOv26x', 'VL 语义双引擎', 'videocam', 'emerald')]
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
- LangGraph — 状态机 Agent 编排 / 自我修正机制 / 完整链路追踪
- NiceGUI — 现代化交互界面 / 多页面应用
- ModelManager — 统一模型管理 / Qwen3-VL Embedding + Reranker''')

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
    LDB <--> Qwen''').classes('w-full flex justify-center bg-slate-50 rounded-2xl p-4')

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
            ui.markdown('''1. **二阶段检索架构** — Qwen3-VL Embedding 向量召回 + Qwen3-VL Reranker 精排重排序
2. **混合检索算法** — 向量相似度 + 关键词匹配，可调节权重
3. **Agent自我修正** — SQL执行失败自动分析错误，智能修正并重试
4. **双引擎自动标注** — YOLOv26x 快速检测 + VLLM API 语义验证
5. **一键入库脚本** — 自动清理、入库、向量化，路径统一转换
6. **生产级安全防护** — SQL注入防护、表访问白名单、危险操作拦截''')

        # 性能指标
        with ui.grid(columns=4).classes('w-full gap-6'):
            for lbl, val, sub in [("向量化速度", "~80 张/秒", "API推理"),
                                   ("检索延迟", "< 100ms", "亚秒级"),
                                   ("问答准确率", "> 95%", "自我修正"),
                                   ("数据规模", "可扩展", "百万级")]:
                with ui.element('div').classes('kpi-card text-center'):
                    ui.label(val).classes('text-xl font-bold text-slate-800')
                    ui.label(lbl).classes('text-sm text-slate-500')
                    ui.label(sub).classes('text-xs text-slate-400')


# ══════════════════════════════════════════════════════════════════════════
# Page 2: 智能问答（完整版 — SQL编辑器 / 执行历史 / 对话记录 / 高级筛选 / 追问 / 媒体预览）
# ══════════════════════════════════════════════════════════════════════════

@ui.page('/qa')
def qa_page():
    with create_layout('/qa'):
        page_header('智能问答（Agent 驱动）',
                     '基于 LangGraph Agent，支持 NL2SQL、SQL 自我修正、完整链路追踪、安全护栏')

        ensure_systems()
        _db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))

        # ── per-client state ──
        qa_state: Dict[str, Any] = {'result': None}
        result_container = ui.column().classes('w-full')

        # ── 预设快捷问题 ──
        presets = ["按街道统计最近30天各类告警数量", "查询最近20条车辆闯入告警的详细信息",
                   "统计各设备触发告警次数最多的TOP10", "查询置信度大于0.9的高置信告警"]
        with ui.row().classes('w-full gap-2 mb-4 flex-wrap'):
            for q in presets:
                ui.button(q[:14] + '...', on_click=lambda q=q: do_ask(q)) \
                    .props('outline size=sm color=blue-6 rounded-lg no-caps')

        # ── 输入区 ──
        with ui.row().classes('w-full gap-4 items-end mb-2'):
            question_input = ui.input(placeholder='输入问题，如：按街道统计最近30天各类告警数量') \
                .classes('flex-1').props('outlined dense')
            enable_trace = ui.switch('启用追踪').props('dense').classes('text-xs')
            enable_trace.value = True

        # ── 高级筛选面板 ──
        qa_filters_state: Dict[str, Any] = {
            'event_type': '', 'alarm_level': '', 'order_status': '',
            'city': '', 'county': '', 'town': '',
            'device_name': '', 'algorithm_name': '',
            'confidence_min': 0.0, 'confidence_max': 1.0,
            'enable_time': False, 'start_date': '', 'end_date': '',
        }
        area_h = get_area_hierarchy(str(_db_path))

        with ui.expansion('高级筛选', icon='tune').classes('w-full mb-4 bg-white rounded-xl'):
            with ui.grid(columns=3).classes('w-full gap-3 p-4'):
                ui.input('事件类型', placeholder='如：车辆闯入监控告警').bind_value(qa_filters_state, 'event_type').props('outlined dense')
                ui.select({'' : '全部', '01': '等级01'}, label='告警等级').bind_value(qa_filters_state, 'alarm_level').props('outlined dense')
                ui.select({'': '全部', '1': '待处理', '2': '处理中', '4': '已完成', '6': '已关闭'}, label='工单状态') \
                    .bind_value(qa_filters_state, 'order_status').props('outlined dense')
            with ui.grid(columns=3).classes('w-full gap-3 px-4'):
                city_opts = {'': '全部'}; city_opts.update({c: c for c in area_h['cities']})
                ui.select(city_opts, label='城市').bind_value(qa_filters_state, 'city').props('outlined dense')
                county_opts = {'': '全部'}
                for cs in area_h['county_by_city'].values():
                    for c in cs: county_opts[c] = c
                ui.select(county_opts, label='区/县').bind_value(qa_filters_state, 'county').props('outlined dense')
                town_opts = {'': '全部'}
                for ts in area_h['town_by_county'].values():
                    for t in ts: town_opts[t] = t
                ui.select(town_opts, label='街道/乡镇').bind_value(qa_filters_state, 'town').props('outlined dense')
            with ui.grid(columns=3).classes('w-full gap-3 px-4 pb-4'):
                ui.input('设备名称', placeholder='模糊匹配').bind_value(qa_filters_state, 'device_name').props('outlined dense')
                ui.input('算法名称', placeholder='模糊匹配').bind_value(qa_filters_state, 'algorithm_name').props('outlined dense')
                with ui.column().classes('gap-1'):
                    ui.label('置信度范围').classes('text-xs text-slate-500')
                    with ui.row().classes('gap-2'):
                        ui.number(min=0, max=1, step=0.05, value=0).bind_value(qa_filters_state, 'confidence_min').props('outlined dense').classes('w-20')
                        ui.label('~').classes('self-center')
                        ui.number(min=0, max=1, step=0.05, value=1).bind_value(qa_filters_state, 'confidence_max').props('outlined dense').classes('w-20')

        def collect_qa_filters() -> Dict:
            f = {}
            for k in ['event_type', 'alarm_level', 'order_status', 'device_name', 'algorithm_name']:
                if qa_filters_state.get(k): f[k] = qa_filters_state[k]
            if qa_filters_state.get('city'): f['city_name'] = qa_filters_state['city']
            if qa_filters_state.get('county'): f['county_name'] = qa_filters_state['county']
            if qa_filters_state.get('town'): f['town_name'] = qa_filters_state['town']
            if qa_filters_state['confidence_min'] > 0: f['confidence_min'] = qa_filters_state['confidence_min']
            if qa_filters_state['confidence_max'] < 1: f['confidence_max'] = qa_filters_state['confidence_max']
            return f

        # ── 执行按钮 ──
        async def do_ask(question: str = ''):
            q = question or question_input.value
            if not q or not q.strip():
                ui.notify('请输入问题', type='warning'); return
            question_input.value = q
            ui.notify('Agent 正在思考...', type='info', spinner=True, timeout=0, close_button=False)
            try:
                agent = get_agent()
                if not agent:
                    ui.notify('Agent 未初始化', type='negative'); return
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: agent.query(q, user_id="nicegui_user"))

                # 高级筛选注入
                qa_f = collect_qa_filters()
                if qa_f and result.get("status") == "success" and result.get("sql"):
                    try:
                        injected = result["sql"]
                        for p in (result.get("sql_params") or []):
                            injected = injected.replace("?", f"'{p}'" if isinstance(p, str) else str(p), 1)
                        injected = _inject_sql_filters(injected, qa_f)
                        conn = connect_db(_db_path)
                        rows = conn.execute(injected).fetchall(); conn.close()
                        new_data = [dict(r) for r in rows]
                        sql_upper = injected.upper()
                        has_agg = any(fn in sql_upper for fn in ("COUNT(", "SUM(", "AVG("))
                        new_intent = "count" if has_agg and "GROUP BY" in sql_upper else result.get("intent", "list")
                        if new_intent == "count" and len(new_data) == 1 and len(new_data[0]) == 1:
                            result["answer"] = {"type": "count", "value": list(new_data[0].values())[0],
                                                "message": f"共 {list(new_data[0].values())[0]} 条"}
                        else:
                            result["answer"] = {"type": "list", "value": new_data,
                                                "message": f"返回 {len(new_data)} 条记录"}
                        result["sql"] = injected; result["sql_params"] = []; result["intent"] = new_intent
                        result["execution_history"] = result.get("execution_history", []) + [
                            {"sql": injected, "params": [], "result_count": len(new_data), "status": "success"}]
                    except Exception as fe:
                        print(f"Filter inject failed: {fe}")

                # 保存追踪
                try:
                    tm = get_trace_manager()
                    if tm:
                        t = QueryTrace(question=q); t.intent = result.get("intent")
                        t.sql = result.get("sql"); t.sql_params = result.get("sql_params")
                        t.status = result.get("status", "error"); t.error_message = result.get("error")
                        ans = result.get("answer")
                        if isinstance(ans, dict) and isinstance(ans.get("value"), list):
                            t.result_count = len(ans["value"])
                        step = t.add_step("agent_query")
                        step.finish("success" if result.get("status") == "success" else "error")
                        t.finish(status=t.status); tm.save_trace(t)
                except Exception: pass

                qa_state['result'] = result
                render_result()
                ui.notify('查询完成', type='positive')
            except Exception as e:
                ui.notify(f'查询失败: {e}', type='negative')
                traceback.print_exc()

        with ui.row().classes('w-full gap-3 mb-6'):
            ui.button('执行查询', icon='play_arrow', on_click=lambda: do_ask()) \
                .props('unelevated color=blue-6 rounded no-caps').classes('flex-1')
            question_input.on('keydown.enter', lambda: do_ask())

        # ── 结果渲染 ──
        def render_result():
            result_container.clear()
            result = qa_state.get('result')
            if not result: return
            with result_container:
                # 状态
                if result["status"] == "success":
                    ui.label('查询成功').classes('text-green-600 font-semibold mb-2')
                else:
                    ui.label(f'查询失败: {result.get("error", "")}').classes('text-red-600 font-semibold mb-2')

                # 指标
                with ui.grid(columns=3).classes('w-full gap-4 mb-4'):
                    for lbl, val in [("查询意图", result.get("intent", "未知")),
                                     ("重试次数", str(result.get("retry_count", 0))),
                                     ("返回记录", _count_answer(result))]:
                        with ui.element('div').classes('kpi-card text-center'):
                            ui.label(str(val)).classes('text-xl font-bold text-slate-800')
                            ui.label(lbl).classes('text-sm text-slate-500')

                # 执行详情 Tabs
                with ui.tabs().classes('w-full') as tabs:
                    tab_sql = ui.tab('生成的 SQL')
                    tab_hist = ui.tab('执行历史')
                    tab_conv = ui.tab('对话记录')
                with ui.tab_panels(tabs, value=tab_sql).classes('w-full'):
                    # Tab 1: SQL 编辑器
                    with ui.tab_panel(tab_sql):
                        display_sql = _expand_sql_params(result.get("sql", ""), result.get("sql_params"))
                        sql_editor = ui.textarea('可直接编辑 SQL 后重新执行', value=display_sql) \
                            .classes('w-full font-mono text-sm').props('outlined rows=5')
                        if result.get("sql_params"):
                            ui.label(f'原始参数: {result["sql_params"]}').classes('text-xs text-slate-400')

                        async def rerun_sql():
                            try:
                                conn = connect_db(_db_path)
                                rows = conn.execute(sql_editor.value).fetchall(); conn.close()
                                new_data = [dict(r) for r in rows]
                                sql_upper = sql_editor.value.upper()
                                has_agg = any(fn in sql_upper for fn in ("COUNT(", "SUM(", "AVG("))
                                new_intent = "count" if has_agg and "GROUP BY" in sql_upper else result.get("intent", "list")
                                if new_intent == "count" and len(new_data) == 1 and len(new_data[0]) == 1:
                                    result["answer"] = {"type": "count", "value": list(new_data[0].values())[0],
                                                        "message": f"共 {list(new_data[0].values())[0]} 条"}
                                else:
                                    result["answer"] = {"type": "list", "value": new_data,
                                                        "message": f"返回 {len(new_data)} 条记录"}
                                result["sql"] = sql_editor.value; result["sql_params"] = []
                                result["intent"] = new_intent; result["status"] = "success"; result["error"] = None
                                result["execution_history"] = result.get("execution_history", []) + [
                                    {"sql": sql_editor.value, "params": [], "result_count": len(new_data), "status": "success"}]
                                qa_state['result'] = result
                                render_result()
                                ui.notify('SQL 重新执行成功', type='positive')
                            except Exception as e:
                                ui.notify(f'SQL 执行失败: {e}', type='negative')

                        ui.button('重新执行 SQL', icon='refresh', on_click=rerun_sql) \
                            .props('outline color=blue-6 rounded no-caps size=sm')

                    # Tab 2: 执行历史
                    with ui.tab_panel(tab_hist):
                        hist = result.get("execution_history", [])
                        if hist:
                            for i, rec in enumerate(hist):
                                icon = 'check_circle' if rec["status"] == "success" else 'error'
                                color = 'text-green-600' if rec["status"] == "success" else 'text-red-600'
                                with ui.row().classes('items-center gap-2 mb-1'):
                                    ui.icon(icon).classes(f'{color} text-sm')
                                    ui.label(f'尝试 {i+1}').classes('font-semibold text-sm')
                                ui.code(rec.get("sql", ""), language='sql').classes('w-full mb-1')
                                if rec.get("error"):
                                    ui.label(f'错误: {rec["error"]}').classes('text-red-500 text-xs mb-2')
                                else:
                                    ui.label(f'返回 {rec.get("result_count", 0)} 条记录').classes('text-green-600 text-xs mb-2')
                        else:
                            ui.label('无执行历史').classes('text-slate-400')

                    # Tab 3: 对话记录
                    with ui.tab_panel(tab_conv):
                        msgs = result.get("messages", [])
                        if msgs:
                            for msg in msgs:
                                if hasattr(msg, 'type'):
                                    role, content = msg.type, msg.content
                                elif isinstance(msg, dict):
                                    role, content = msg.get("role", "system"), msg.get("content", "")
                                else:
                                    role, content = "system", str(msg)
                                icon_name = 'person' if role in ('user', 'human') else 'smart_toy' if role in ('assistant', 'ai') else 'settings'
                                with ui.row().classes('items-start gap-2 mb-2'):
                                    ui.icon(icon_name).classes('text-slate-400 mt-1')
                                    ui.markdown(str(content)[:500]).classes('text-sm')
                        else:
                            ui.label('无对话记录').classes('text-slate-400')

                # ── 查询结果 ──
                answer = result.get("answer")
                if answer:
                    ui.separator().classes('my-4')
                    ui.label('查询结果').classes('font-bold text-lg text-slate-800 mb-3')
                    answer_data = answer.get("value")

                    if isinstance(answer_data, list) and len(answer_data) > 0 and isinstance(answer_data[0], dict):
                        ui.label(f'共返回 {len(answer_data)} 条记录').classes('text-blue-600 text-sm mb-2')
                        cols_raw = list(answer_data[0].keys())
                        # 表格
                        tbl_cols = [{"name": c, "label": c.replace('_', ' ').title(), "field": c, "sortable": True} for c in cols_raw]
                        ui.table(columns=tbl_cols, rows=answer_data[:50],
                                 pagination={"rowsPerPage": 10}).classes('w-full mb-4')

                        # 图片/视频列检测
                        img_col_indices = []
                        video_col_idx = None
                        for idx, cn in enumerate(cols_raw):
                            cnl = cn.lower()
                            if cnl in ('图片路径', 'file_path', '图片文件路径'):
                                img_col_indices.insert(0, idx)
                            elif 'img_src' in cnl or '原图' in cnl:
                                img_col_indices.append(idx)
                            elif '图片' in cnl and '缩略' not in cnl and 'icon' not in cnl:
                                img_col_indices.append(idx)
                            if video_col_idx is None and (cnl in ('视频路径', 'video_path') or '视频' in cnl or 'video' in cnl):
                                video_col_idx = idx

                        # 媒体预览
                        if img_col_indices or video_col_idx is not None:
                            ui.label('媒体预览').classes('font-semibold text-slate-700 mb-2')
                            with ui.grid(columns=3).classes('w-full gap-4 mb-4'):
                                for row_idx, row in enumerate(answer_data[:9]):
                                    with ui.element('div').classes('result-card p-2'):
                                        shown = False
                                        for ic in img_col_indices:
                                            if shown: break
                                            iv = row.get(cols_raw[ic], "")
                                            if iv:
                                                ui.image(f'/warning_img/{Path(str(iv)).name}').classes('w-full h-32 object-cover rounded')
                                                shown = True
                                        if video_col_idx is not None:
                                            vv = row.get(cols_raw[video_col_idx], "")
                                            if vv:
                                                vn = Path(str(vv).split(",")[0].strip()).name
                                                ui.video(f'/warning_file/{vn}').classes('w-full rounded mt-1')
                                                shown = True
                                        if not shown:
                                            ui.label(f'第{row_idx+1}条：无媒体').classes('text-xs text-slate-400 p-2')

                        # count 类型 → 查看明细按钮
                        if result.get("intent") == "count" and isinstance(answer_data, list) and len(answer_data) > 0:
                            first_row = answer_data[0]
                            group_key = next((k for k, v in first_row.items() if not isinstance(v, (int, float))), None)
                            if group_key:
                                ui.label('查看明细').classes('font-semibold text-slate-700 mb-2')
                                time_m = re.search(r'(最近\d+[天小时月年周]|本[月周年日]|今[天年月])', result.get("question", ""))
                                time_cond = time_m.group(1) + "内" if time_m else ""
                                with ui.row().classes('flex-wrap gap-2 mb-4'):
                                    for row in answer_data:
                                        gv = row.get(group_key, "")
                                        cnt_vals = [v for v in row.values() if isinstance(v, (int, float))]
                                        cnt_str = f"({int(cnt_vals[0])}条)" if cnt_vals else ""
                                        if gv:
                                            ui.button(f'{gv} {cnt_str}',
                                                      on_click=lambda gv=gv: do_ask(f"查询{time_cond}最近20条{gv}的详细信息")) \
                                                .props('outline size=sm color=blue-6 rounded-lg no-caps')

                        # 追问建议
                        ui.separator().classes('my-3')
                        ui.label('您可能还想了解').classes('font-semibold text-slate-700 mb-2')
                        suggestions = _build_suggestions(result, answer_data)
                        with ui.row().classes('flex-wrap gap-2'):
                            for s in suggestions[:4]:
                                ui.button(f'{s[:20]}{"..." if len(s)>20 else ""}',
                                          on_click=lambda s=s: do_ask(s)) \
                                    .props('outline size=sm color=teal-6 rounded-lg no-caps')

                    elif isinstance(answer_data, int):
                        with ui.element('div').classes('kpi-card text-center'):
                            ui.label(f'{answer_data:,}').classes('text-3xl font-bold text-blue-600')
                            ui.label('统计结果').classes('text-sm text-slate-500')
                        ui.separator().classes('my-3')
                        ui.label('您可能还想了解').classes('font-semibold text-slate-700 mb-2')
                        suggestions = _build_suggestions(result, answer_data)
                        with ui.row().classes('flex-wrap gap-2'):
                            for s in suggestions[:4]:
                                ui.button(s[:20], on_click=lambda s=s: do_ask(s)) \
                                    .props('outline size=sm color=teal-6 rounded-lg no-caps')
                    else:
                        ui.code(json.dumps(answer, ensure_ascii=False, indent=2), language='json')

        render_result()


def _count_answer(result: dict) -> str:
    ans = result.get("answer")
    if not ans: return "N/A"
    v = ans.get("value")
    if isinstance(v, int): return str(v)
    if isinstance(v, list): return str(len(v))
    return "1"


def _expand_sql_params(sql: str, params) -> str:
    if not params: return sql
    for p in params:
        sql = sql.replace("?", f"'{p}'" if isinstance(p, str) else str(p), 1)
    return sql


def _build_suggestions(result: dict, answer_data) -> List[str]:
    intent = result.get("intent", "")
    suggestions = []
    if intent == "count":
        if isinstance(answer_data, list) and len(answer_data) > 0:
            first = answer_data[0]
            gk = next((k for k, v in first.items() if not isinstance(v, (int, float))), None)
            if gk:
                for row in answer_data[:4]:
                    gv = row.get(gk, "")
                    if gv: suggestions.append(f"查询最近20条{gv}的详细信息")
        if not suggestions:
            suggestions.append("查询最近20条告警的详细信息")
    else:
        suggestions = ["按告警类型统计数量", "按街道统计告警分布", "按设备统计告警次数TOP10"]
    return suggestions


# ══════════════════════════════════════════════════════════════════════════
# Page 3: 多模态检索（完整版 — 文件上传 / 视频抽帧 / 全部高级过滤 / 关联数据）
# ══════════════════════════════════════════════════════════════════════════

@ui.page('/search')
def search_page():
    with create_layout('/search'):
        page_header('多模态检索 · 图文视频互搜',
                     '基于 Qwen3-VL + LanceDB 的向量检索，支持图片/文本/视频统一入口互搜')

        _db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
        lancedb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))

        # 检查 LanceDB
        if not lancedb_dir.exists() or not (lancedb_dir / "embeddings.lance").exists():
            ui.label('向量数据库未初始化，请运行 bash 重新入库.sh').classes('text-red-600 font-semibold')
            return

        state: Dict[str, Any] = {
            'results': [], 'query_text': '', 'top_k': 10,
            'vector_weight': 0.7, 'enable_hybrid': True, 'show_related': True,
            'uploaded_path': None, 'uploaded_is_video': False,
        }
        # 过滤器状态
        f_state: Dict[str, Any] = {
            'event_type': '', 'alarm_level': '', 'order_status': '',
            'importance': '', 'warning_source': '', 'alarm_body': '',
            'city': '', 'county': '', 'town': '',
            'tenant': '', 'device': '', 'device_code': '',
            'channel': '', 'algorithm': '', 'algorithm_code': '',
            'confidence_min': 0.0, 'confidence_max': 1.0,
            'enable_time': False, 'start_date': '', 'end_date': '',
            'enable_geo': False, 'lat': '', 'lon': '', 'radius_km': 5.0,
        }
        results_container = ui.column().classes('w-full')

        # ── 输入区 ──
        with ui.grid(columns='3fr 2fr').classes('w-full gap-6 mb-4'):
            with ui.column().classes('gap-3'):
                search_input = ui.input('文本检索', placeholder='输入关键词，如：车辆闯入监控告警') \
                    .classes('w-full').props('outlined dense')
                search_input.bind_value(state, 'query_text')

                upload_preview = ui.column().classes('w-full')

                async def handle_upload(e: events.UploadEventArguments):
                    content = e.content.read()
                    name = e.name
                    suffix = Path(name).suffix.lower()
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                    tmp.write(content); tmp.close()
                    upload_preview.clear()
                    if suffix == '.mp4':
                        state['uploaded_is_video'] = True
                        try:
                            import cv2
                            cap = cv2.VideoCapture(tmp.name)
                            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                            cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
                            ret, frame = cap.read(); cap.release()
                            if ret:
                                frame_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                                cv2.imwrite(frame_tmp.name, frame); frame_tmp.close()
                                state['uploaded_path'] = frame_tmp.name
                                import base64
                                _, buf = cv2.imencode('.jpg', cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                                with upload_preview:
                                    ui.image(f'data:image/jpeg;base64,{base64.b64encode(buf).decode()}') \
                                        .classes('w-full max-h-48 object-contain rounded-lg')
                                    ui.label(f'视频关键帧（第 {total//2}/{total} 帧）').classes('text-xs text-slate-400')
                        except Exception as ex:
                            with upload_preview:
                                ui.label(f'视频抽帧失败: {ex}').classes('text-red-500 text-sm')
                        finally:
                            Path(tmp.name).unlink(missing_ok=True)
                    else:
                        state['uploaded_is_video'] = False
                        state['uploaded_path'] = tmp.name
                        import base64
                        with upload_preview:
                            ui.image(f'data:image/{suffix[1:]};base64,{base64.b64encode(content).decode()}') \
                                .classes('w-full max-h-48 object-contain rounded-lg')
                            ui.label('上传的图片').classes('text-xs text-slate-400')

                ui.upload(label='上传图片或视频', auto_upload=True, on_upload=handle_upload,
                          max_file_size=50_000_000) \
                    .props('accept=".jpg,.jpeg,.png,.bmp,.mp4"').classes('w-full')

            with ui.column().classes('gap-3'):
                ui.number('返回数量', min=1, max=50, value=10, step=1).bind_value(state, 'top_k').props('outlined dense')
                ui.switch('混合检索').bind_value(state, 'enable_hybrid')
                ui.slider(min=0, max=1, step=0.1, value=0.7).bind_value(state, 'vector_weight') \
                    .props('label-always label="向量权重"')
                ui.switch('显示关联数据').bind_value(state, 'show_related')

        # ── 高级过滤 ──
        dd_opts = get_dropdown_options(str(_db_path))
        area_h = get_area_hierarchy(str(_db_path))

        with ui.expansion('高级过滤', icon='tune').classes('w-full mb-4 bg-white rounded-xl'):
            # 行1: 告警类型 + 紧急等级 + 工单状态
            with ui.grid(columns=3).classes('w-full gap-3 p-4'):
                _wt = {'': '全部'}; _wt.update({v: v for v in dd_opts.get("warning_type_name", [])})
                ui.select(_wt, label='告警类型').bind_value(f_state, 'event_type').props('outlined dense')
                ui.select({'': '全部', '1': '等级1(高)', '2': '等级2(中)', '3': '等级3(低)'}, label='紧急等级') \
                    .bind_value(f_state, 'alarm_level').props('outlined dense')
                ui.select({'': '全部', '1': '待处理', '2': '处理中', '4': '已完成', '6': '已关闭'}, label='工单状态') \
                    .bind_value(f_state, 'order_status').props('outlined dense')
            # 行2: 重要等级 + 告警来源 + 告警主体
            with ui.grid(columns=3).classes('w-full gap-3 px-4'):
                _imp = {'': '全部'}; _imp.update({v: f'等级 {v}' for v in dd_opts.get("importance_level", [])})
                ui.select(_imp, label='重要等级').bind_value(f_state, 'importance').props('outlined dense')
                _ws = {'': '全部'}; _ws.update({v: v for v in dd_opts.get("warning_source_name", [])})
                ui.select(_ws, label='告警来源').bind_value(f_state, 'warning_source').props('outlined dense')
                _ab = {'': '全部'}; _ab.update({v: v for v in dd_opts.get("alarm_body", [])})
                ui.select(_ab, label='告警主体').bind_value(f_state, 'alarm_body').props('outlined dense')
            # 行3: 城市 + 区县 + 街道
            with ui.grid(columns=3).classes('w-full gap-3 px-4'):
                _ci = {'': '全部'}; _ci.update({c: c for c in area_h['cities']})
                ui.select(_ci, label='城市').bind_value(f_state, 'city').props('outlined dense')
                _co = {'': '全部'}
                for cs in area_h['county_by_city'].values():
                    for c in cs: _co[c] = c
                ui.select(_co, label='区/县').bind_value(f_state, 'county').props('outlined dense')
                _tw = {'': '全部'}
                for ts in area_h['town_by_county'].values():
                    for t in ts: _tw[t] = t
                ui.select(_tw, label='街道/乡镇').bind_value(f_state, 'town').props('outlined dense')
            # 行4: 租户 + 设备名称 + 设备编码
            with ui.grid(columns=3).classes('w-full gap-3 px-4'):
                _tn = {'': '全部'}; _tn.update({v: v for v in dd_opts.get("tenant_name", [])})
                ui.select(_tn, label='租户').bind_value(f_state, 'tenant').props('outlined dense')
                _dn = {'': '全部'}; _dn.update({v: v for v in dd_opts.get("device_name", [])})
                ui.select(_dn, label='设备名称').bind_value(f_state, 'device').props('outlined dense')
                _dc = {'': '全部'}; _dc.update({v: v for v in dd_opts.get("device_code", [])})
                ui.select(_dc, label='设备编码').bind_value(f_state, 'device_code').props('outlined dense')
            # 行5: 通道 + 算法名称 + 算法编码
            with ui.grid(columns=3).classes('w-full gap-3 px-4'):
                _cn = {'': '全部'}; _cn.update({v: v for v in dd_opts.get("channel_name", [])})
                ui.select(_cn, label='通道名称').bind_value(f_state, 'channel').props('outlined dense')
                _an = {'': '全部'}; _an.update({v: v for v in dd_opts.get("algorithm_name", [])})
                ui.select(_an, label='算法名称').bind_value(f_state, 'algorithm').props('outlined dense')
                _ac = {'': '全部'}; _ac.update({v: v for v in dd_opts.get("algorithm_code", [])})
                ui.select(_ac, label='算法编码').bind_value(f_state, 'algorithm_code').props('outlined dense')
            # 行6: 置信度
            with ui.row().classes('w-full gap-4 px-4'):
                ui.label('置信度范围').classes('text-sm text-slate-500 self-center')
                ui.number(min=0, max=1, step=0.05, value=0).bind_value(f_state, 'confidence_min').props('outlined dense').classes('w-24')
                ui.label('~').classes('self-center')
                ui.number(min=0, max=1, step=0.05, value=1).bind_value(f_state, 'confidence_max').props('outlined dense').classes('w-24')
            # 行7: 时间过滤
            with ui.column().classes('w-full px-4 gap-2'):
                ui.switch('启用时间过滤').bind_value(f_state, 'enable_time')
                with ui.row().classes('gap-4'):
                    ui.input('开始时间', placeholder='YYYY-MM-DD HH:MM:SS').bind_value(f_state, 'start_date').props('outlined dense')
                    ui.input('结束时间', placeholder='YYYY-MM-DD HH:MM:SS').bind_value(f_state, 'end_date').props('outlined dense')
            # 行8: 地理位置
            with ui.column().classes('w-full px-4 pb-4 gap-2'):
                ui.switch('启用地理位置过滤').bind_value(f_state, 'enable_geo')
                with ui.row().classes('gap-4'):
                    geo_addr = ui.input('地址搜索', placeholder='如：天安门、深圳市南山区').props('outlined dense')
                    async def do_geocode():
                        gaode = config.get("gaode", {})
                        r = geocode_address(geo_addr.value, gaode.get("api_key", ""), gaode.get("geocode_url", ""))
                        if r:
                            f_state['lat'] = str(r[0]); f_state['lon'] = str(r[1])
                            ui.notify(f'解析成功: {r[2]}', type='positive')
                        else:
                            ui.notify('地址解析失败', type='warning')
                    ui.button('解析', on_click=do_geocode).props('outline size=sm rounded')
                with ui.row().classes('gap-4'):
                    ui.input('纬度').bind_value(f_state, 'lat').props('outlined dense').classes('w-32')
                    ui.input('经度').bind_value(f_state, 'lon').props('outlined dense').classes('w-32')
                    ui.number('半径(km)', min=1, max=50, value=5).bind_value(f_state, 'radius_km').props('outlined dense').classes('w-32')

        def collect_search_filters() -> dict:
            f = {}
            for k, fk in [('event_type', 'event_type'), ('alarm_level', 'alarm_level'),
                          ('order_status', 'order_status'), ('importance', 'importance_level'),
                          ('warning_source', 'warning_source_name'), ('alarm_body', 'alarm_body'),
                          ('city', 'city_name'), ('county', 'county_name'), ('town', 'town_name'),
                          ('tenant', 'tenant_name'), ('device', 'device_name'), ('device_code', 'device_code'),
                          ('channel', 'channel_name'), ('algorithm', 'algorithm_name'),
                          ('algorithm_code', 'algorithm_code')]:
                if f_state.get(k): f[fk] = f_state[k]
            if f_state['confidence_min'] > 0: f['confidence_min'] = f_state['confidence_min']
            if f_state['confidence_max'] < 1: f['confidence_max'] = f_state['confidence_max']
            if f_state.get('enable_time'):
                if f_state.get('start_date'): f['start_time'] = f_state['start_date']
                if f_state.get('end_date'): f['end_time'] = f_state['end_date']
            return f

        def render_results():
            results_container.clear()
            if not state['results']: return
            with results_container:
                ui.label(f'找到 {len(state["results"])} 条结果').classes('text-green-600 font-semibold mb-4')
                for idx, item in enumerate(state['results']):
                    with ui.element('div').classes('result-card mb-6'):
                        with ui.grid(columns='1fr 2fr').classes('w-full'):
                            # 左: 媒体
                            with ui.column().classes('p-4'):
                                if item.get('img_url'):
                                    ui.image(item['img_url']).classes('w-full h-48 object-cover rounded-lg')
                                else:
                                    with ui.element('div').classes('w-full h-48 bg-slate-100 rounded-lg flex items-center justify-center'):
                                        ui.icon('image_not_supported').classes('text-4xl text-slate-300')
                                if item.get('video_url'):
                                    ui.video(item['video_url']).classes('w-full rounded-lg mt-2')
                                if item.get('score', 0) > 0:
                                    ui.label(f'相似度: {item["score"]:.4f}').classes('text-blue-600 font-semibold text-sm mt-2')
                            # 右: 详情
                            with ui.column().classes('p-4 gap-1'):
                                ui.label(item.get('event_type', '未知事件')).classes('font-bold text-lg text-slate-800')
                                for lbl, key in [('告警等级', 'alarm_level'), ('时间', 'alarm_time'),
                                                 ('地址', 'address'), ('设备', 'device_name'),
                                                 ('算法', 'algorithm_name'), ('工单状态', 'order_status'),
                                                 ('置信度', 'confidence_level')]:
                                    v = item.get(key)
                                    if v:
                                        val_str = f'{v:.2f}' if isinstance(v, float) else str(v)
                                        with ui.row().classes('gap-2'):
                                            ui.label(f'{lbl}:').classes('text-xs text-slate-400 w-16')
                                            ui.label(val_str).classes('text-sm text-slate-700')
                                geo = ' / '.join(filter(None, [item.get('province_name'), item.get('city_name'),
                                                               item.get('county_name'), item.get('town_name')]))
                                if geo:
                                    with ui.row().classes('gap-2'):
                                        ui.label('地区:').classes('text-xs text-slate-400 w-16')
                                        ui.label(geo).classes('text-sm text-slate-700')
                                if item.get('summary'):
                                    ui.label('图像理解:').classes('text-xs text-slate-400 mt-2')
                                    ui.label(item['summary']).classes('text-sm text-slate-600')
                                if item.get('description') and item.get('description') != item.get('summary'):
                                    ui.label('描述:').classes('text-xs text-slate-400 mt-1')
                                    ui.label(item['description']).classes('text-sm text-slate-600')

                        # 关联数据
                        if state.get('show_related') and item.get('asset_id'):
                            with ui.expansion(f'关联数据 — 结果 {idx+1}', icon='link').classes('w-full'):
                                _render_related_data(item, _db_path)

        def _render_related_data(item: dict, db_path):
            try:
                conn = connect_db(db_path)
                cur = conn.execute("SELECT * FROM events WHERE asset_id = ?", (item['asset_id'],)).fetchone()
                if not cur: conn.close(); return
                ed = dict(cur)
                extra = {}
                if ed.get("extra_json"):
                    try: extra = json.loads(ed["extra_json"])
                    except Exception: pass
                video_key = ""
                raw_video = extra.get("video_url", "")
                if raw_video:
                    video_key = Path(raw_video.split(",")[0].strip()).stem
                siblings = []
                if video_key:
                    siblings = conn.execute(
                        "SELECT e.*, a.file_path, a.file_name FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id WHERE e.extra_json LIKE ?",
                        (f'%{video_key}%',)).fetchall()
                conn.close()
                if video_key:
                    ui.label(f'同一告警共 {len(siblings)} 条记录').classes('text-xs text-slate-400 mb-2')
                if len(siblings) > 1:
                    ui.label('同一告警的所有图片').classes('font-semibold text-sm text-slate-700 mb-1')
                    with ui.row().classes('flex-wrap gap-2 mb-3'):
                        for se in siblings[:8]:
                            sd = dict(se)
                            fp = sd.get("file_path") or sd.get("file_name")
                            if fp:
                                ui.image(f'/warning_img/{Path(fp).name}').classes('w-24 h-20 object-cover rounded')
                # 完整事件信息
                ui.label('完整事件信息').classes('font-semibold text-sm text-slate-700 mb-1')
                display_info = {}
                for field, label in [("event_type", "事件类型"), ("alarm_level", "告警等级"),
                                     ("alarm_time", "告警时间"), ("address", "地址"),
                                     ("device_name", "设备名称"), ("confidence_level", "置信度"),
                                     ("summary", "图像理解"), ("description", "描述")]:
                    val = ed.get(field) or extra.get(field)
                    if val and str(val).strip(): display_info[label] = val
                for field, label in [("warning_type_name", "告警类型"), ("warning_source_name", "告警来源"),
                                     ("alarm_body", "告警主体"), ("algorithm_name", "算法名称"),
                                     ("emergency_level", "紧急等级"), ("importance_level", "重要等级"),
                                     ("order_status", "工单状态"), ("tenant_name", "租户"),
                                     ("city_name", "城市"), ("county_name", "区县"), ("town_name", "街道"),
                                     ("device_code", "设备编码"), ("channel_name", "通道")]:
                    val = ed.get(field) or extra.get(field)
                    if val and str(val).strip() and label not in display_info: display_info[label] = val
                ui.code(json.dumps(display_info, ensure_ascii=False, indent=2), language='json').classes('w-full')
            except Exception as e:
                ui.label(f'加载关联数据失败: {e}').classes('text-red-500 text-xs')

        async def do_search():
            q = state['query_text']
            uploaded = state.get('uploaded_path')
            filters = collect_search_filters()
            has_query = bool(q) or bool(uploaded)
            has_filter = bool(filters)
            if not has_query and not has_filter:
                ui.notify('请输入检索文本、上传图片/视频，或设置筛选条件', type='warning'); return
            ui.notify('检索中...', type='info')
            try:
                import lancedb
                db = lancedb.connect(str(lancedb_dir))
                table = db.open_table("embeddings")
                mgr = get_model_manager()
                top_k = int(state['top_k'])
                search_cfg = config.get("search", {})
                reranker_enabled = search_cfg.get("reranker_enabled", False)
                fetch_k = top_k * 3 if reranker_enabled and q else top_k

                query_vec = None
                if q:
                    # 文本检索：自动提取实体
                    try:
                        from poc.qa.nl2sql import _parse_time_range, _parse_area_name, SCENE_KEYWORDS
                        auto_start, auto_end = _parse_time_range(q)
                        auto_town, auto_county = _parse_area_name(q)
                        auto_event = None
                        for key, value in SCENE_KEYWORDS.items():
                            if key in q: auto_event = value; break
                        if auto_start and not filters.get("start_time"): filters["start_time"] = auto_start
                        if auto_end and not filters.get("end_time"): filters["end_time"] = auto_end
                        if auto_town and not filters.get("town_name"): filters["town_name"] = auto_town
                        if auto_county and not filters.get("county_name"): filters["county_name"] = auto_county
                        if auto_event and not filters.get("event_type"): filters["event_type"] = auto_event
                    except Exception: pass
                    query_vec = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: mgr.encode_text(q).astype("float32"))
                elif uploaded:
                    query_vec = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: mgr.encode_image(uploaded).astype("float32"))

                if query_vec is None:
                    # 纯筛选模式
                    conn = connect_db(_db_path)
                    sql = "SELECT e.*, a.file_path, a.file_name FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id WHERE 1=1"
                    where_extra, params = build_sqlite_filter(filters)
                    sql += where_extra + f" ORDER BY e.alarm_time DESC LIMIT {top_k}"
                    rows = conn.execute(sql, params).fetchall(); conn.close()
                    formatted = []
                    for r in rows:
                        rd = dict(r)
                        extra = {}
                        if rd.get("extra_json"):
                            try: extra = json.loads(rd["extra_json"])
                            except Exception: pass
                        rd["_extra"] = extra
                        formatted.append(build_result_item(rd))
                else:
                    # 向量检索
                    where_extra, sql_params = build_sqlite_filter(filters)
                    pre_filtered_ids = None
                    if where_extra:
                        conn = connect_db(_db_path)
                        id_sql = "SELECT DISTINCT a.asset_id FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id WHERE 1=1" + where_extra
                        pre_filtered_ids = [r[0] for r in conn.execute(id_sql, sql_params).fetchall()]
                        conn.close()
                        if not pre_filtered_ids:
                            state['results'] = []; render_results()
                            ui.notify('筛选条件无匹配结果', type='warning'); return

                    lance_filter = None; post_filter_ids = None
                    if pre_filtered_ids is not None:
                        if len(pre_filtered_ids) <= 100:
                            lance_filter = build_asset_id_filter(pre_filtered_ids)
                        else:
                            post_filter_ids = set(pre_filtered_ids); fetch_k *= 3

                    if q and state['enable_hybrid']:
                        results_df = hybrid_search(table, query_vec, query_text=q, top_k=fetch_k,
                                                   filter_str=lance_filter,
                                                   vector_weight=state['vector_weight'],
                                                   keyword_weight=round(1.0 - state['vector_weight'], 1))
                    else:
                        query_builder = table.search(query_vec.tolist()).limit(fetch_k)
                        if lance_filter: query_builder = query_builder.where(lance_filter)
                        results_df = query_builder.to_pandas()

                    if post_filter_ids is not None:
                        results_df = results_df[results_df["asset_id"].isin(post_filter_ids)]

                    asset_ids = results_df["asset_id"].tolist()
                    details = fetch_events_by_asset_ids(_db_path, asset_ids)
                    formatted = []
                    for _, row in results_df.iterrows():
                        aid = row["asset_id"]
                        score = float(row.get("hybrid_score", row.get("_distance", 0)))
                        rd = details.get(aid, {"_extra": {}})
                        formatted.append(build_result_item(rd, score))

                    if reranker_enabled and q:
                        formatted = mgr.rerank(q, formatted, top_k=top_k)
                    else:
                        formatted = formatted[:top_k]

                state['results'] = formatted
                render_results()
                ui.notify(f'找到 {len(formatted)} 条结果', type='positive')
            except Exception as e:
                ui.notify(f'检索失败: {e}', type='negative')
                traceback.print_exc()

        # 搜索按钮
        ui.button('开始检索', icon='search', on_click=do_search) \
            .props('unelevated color=blue-6 rounded no-caps').classes('w-full mb-6')
        search_input.on('keydown.enter', do_search)

        render_results()


# ══════════════════════════════════════════════════════════════════════════
# Page 4: 自动标注
# ══════════════════════════════════════════════════════════════════════════

@ui.page('/label')
def label_page():
    with create_layout('/label'):
        page_header('自动标注', 'YOLOv26x + VL 语义双引擎自动检测与标注')

        ls = {'files': [], 'idx': 0, 'dets': [], 'engine': None,
              'stats': {'total': 0, 'auto': 0, 'by_class': {}}}
        preview = ui.column().classes('w-full')
        stats_row = ui.row().classes('w-full gap-4 mb-4')

        def init_engine():
            if ls['engine']: return ls['engine']
            try:
                from poc.pipeline.auto_label_engine import AutoLabelEngine
                ls['engine'] = AutoLabelEngine(); return ls['engine']
            except Exception as e:
                ui.notify(f'标注引擎初始化失败: {e}', type='negative'); return None

        def scan(directory: str):
            p = resolve_path(directory)
            if not p.exists():
                ui.notify(f'目录不存在: {p}', type='warning'); return
            exts = {'.jpg', '.jpeg', '.png', '.bmp'}
            ls['files'] = sorted([f for f in p.iterdir() if f.suffix.lower() in exts])
            ls['idx'] = 0; ls['dets'] = []
            ui.notify(f'扫描到 {len(ls["files"])} 个文件', type='positive')
            show()

        def show():
            preview.clear()
            if not ls['files']:
                with preview: ui.label('暂无文件，请先扫描目录').classes('text-slate-400')
                return
            fp = ls['files'][ls['idx']]
            with preview:
                ui.label(f'{fp.name}  ({ls["idx"]+1}/{len(ls["files"])})').classes('font-bold text-slate-700 mb-2')
                if ls['dets']:
                    try:
                        import cv2, base64
                        img = cv2.imread(str(fp)); h, w = img.shape[:2]
                        for d in ls['dets']:
                            bbox = d['bbox']
                            if all(0 <= v <= 1.0 for v in bbox):
                                x1, y1, x2, y2 = int(bbox[0]*w), int(bbox[1]*h), int(bbox[2]*w), int(bbox[3]*h)
                            else:
                                x1, y1, x2, y2 = [int(v) for v in bbox]
                            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(img, f"{d.get('class','?')} {d.get('confidence',0):.2f}",
                                        (x1, max(y1-8, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                        _, buf = cv2.imencode('.jpg', img)
                        ui.image(f'data:image/jpeg;base64,{base64.b64encode(buf).decode()}').classes('w-full max-w-2xl rounded-xl')
                    except Exception:
                        ui.image(f'/warning_img/{fp.name}').classes('w-full max-w-2xl rounded-xl')
                else:
                    ui.image(f'/warning_img/{fp.name}').classes('w-full max-w-2xl rounded-xl')
                if ls['dets']:
                    ui.label(f'检测到 {len(ls["dets"])} 个目标').classes('font-semibold text-slate-700 mt-3 mb-1')
                    rows = [{"类别": d.get("class", ""), "置信度": f"{d.get('confidence',0):.2f}",
                             "边界框": str(d.get("bbox", []))} for d in ls['dets']]
                    ui.table(columns=[{"name": c, "label": c, "field": c} for c in ["类别", "置信度", "边界框"]],
                             rows=rows).classes('w-full')

        def update_stats():
            stats_row.clear()
            with stats_row:
                for lbl, val in [("总检测数", ls['stats']['total']), ("自动标注", ls['stats']['auto'])]:
                    with ui.element('div').classes('kpi-card text-center flex-1'):
                        ui.label(str(val)).classes('text-2xl font-bold text-blue-600')
                        ui.label(lbl).classes('text-sm text-slate-500')
                if ls['stats']['by_class']:
                    with ui.element('div').classes('kpi-card flex-1'):
                        ui.label('按类别').classes('text-sm text-slate-500 mb-1')
                        for cls, cnt in ls['stats']['by_class'].items():
                            ui.label(f'{cls}: {cnt}').classes('text-sm text-slate-700')

        async def detect():
            engine = init_engine()
            if not engine or not ls['files']:
                ui.notify('请先扫描目录', type='warning'); return
            fp = ls['files'][ls['idx']]
            ui.notify(f'正在检测 {fp.name}...', type='info')
            try:
                dets = await asyncio.get_event_loop().run_in_executor(None, lambda: engine.detect_image(str(fp)))
                ls['dets'] = dets
                ls['stats']['total'] += len(dets); ls['stats']['auto'] += len(dets)
                for d in dets:
                    cls = d.get('class', 'unknown')
                    ls['stats']['by_class'][cls] = ls['stats']['by_class'].get(cls, 0) + 1
                ui.notify(f'检测到 {len(dets)} 个目标', type='positive')
                show(); update_stats()
            except Exception as e:
                ui.notify(f'检测失败: {e}', type='negative')

        async def detect_all():
            engine = init_engine()
            if not engine or not ls['files']:
                ui.notify('请先扫描目录', type='warning'); return
            ui.notify(f'批量检测 {len(ls["files"])} 张图片...', type='info')
            for i, fp in enumerate(ls['files']):
                try:
                    dets = await asyncio.get_event_loop().run_in_executor(None, lambda fp=fp: engine.detect_image(str(fp)))
                    ls['stats']['total'] += len(dets); ls['stats']['auto'] += len(dets)
                    for d in dets:
                        cls = d.get('class', 'unknown')
                        ls['stats']['by_class'][cls] = ls['stats']['by_class'].get(cls, 0) + 1
                except Exception: pass
            update_stats()
            ui.notify(f'批量检测完成', type='positive')

        def nav(delta):
            if not ls['files']: return
            ls['idx'] = max(0, min(len(ls['files'])-1, ls['idx']+delta))
            ls['dets'] = []; show()

        # 控制面板
        with ui.element('div').classes('kpi-card mb-6 w-full'):
            with ui.row().classes('items-center gap-4 w-full'):
                dir_input = ui.input('图片目录', value='warning_img').classes('flex-1').props('outlined dense')
                ui.button('扫描目录', on_click=lambda: scan(dir_input.value)).props('unelevated color=blue-6 rounded no-caps')
                ui.button('自动检测', on_click=detect).props('unelevated color=teal-6 rounded no-caps')
                ui.button('批量检测', on_click=detect_all).props('outline color=amber-8 rounded no-caps')
            with ui.row().classes('items-center gap-2 mt-3'):
                ui.button(icon='navigate_before', on_click=lambda: nav(-1)).props('flat round')
                ui.button(icon='navigate_next', on_click=lambda: nav(1)).props('flat round')

        update_stats()
        show()


# ══════════════════════════════════════════════════════════════════════════
# Page 5: 系统监控
# ══════════════════════════════════════════════════════════════════════════

@ui.page('/monitor')
def monitor_page():
    with create_layout('/monitor'):
        page_header('系统监控', '数据统计、查询追踪与 Tool 注册中心')
        ensure_systems()

        # 数据统计
        try:
            _db = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
            stats = db_stats(_db); lc = lance_count()
        except Exception:
            stats = {"assets": 0, "events": 0, "detections": 0, "annotations": 0, "embeddings": 0}; lc = 0

        ui.label('数据统计').classes('font-bold text-lg text-slate-800 mb-3')
        with ui.grid(columns=5).classes('w-full gap-4 mb-8'):
            for lbl, val, icon in [("资产数", stats["assets"], "inventory_2"),
                                    ("事件数", stats["events"], "warning"),
                                    ("检测数", stats["detections"], "center_focus_strong"),
                                    ("标注数", stats["annotations"], "label"),
                                    ("向量数", lc, "hub")]:
                with ui.element('div').classes('kpi-card flex items-center gap-4'):
                    with ui.element('div').classes('w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center'):
                        ui.icon(icon).classes('text-blue-600')
                    with ui.column().classes('gap-0'):
                        ui.label(f'{val:,}').classes('text-xl font-bold text-slate-800')
                        ui.label(lbl).classes('text-sm text-slate-500')

        # 查询追踪
        ui.label('查询追踪统计').classes('font-bold text-lg text-slate-800 mb-3')
        tm = get_trace_manager()
        if tm:
            ts = tm.get_statistics()
            total = ts.get("total_queries", 0)
            success = ts.get("success_count", 0)
            error = ts.get("error_count", 0)
            rate = (success / total * 100) if total > 0 else 0
            avg_ms = ts.get("avg_duration_ms", 0)

            with ui.grid(columns=5).classes('w-full gap-4 mb-6'):
                for lbl, val in [("总查询数", str(total)), ("成功数", str(success)),
                                  ("失败数", str(error)), ("成功率", f"{rate:.1f}%"),
                                  ("平均耗时", f"{avg_ms:.0f}ms")]:
                    with ui.element('div').classes('kpi-card text-center'):
                        ui.label(val).classes('text-xl font-bold text-slate-800')
                        ui.label(lbl).classes('text-sm text-slate-500')

            # 按意图分组
            by_intent = ts.get("by_intent")
            if by_intent:
                ui.label('按意图分组').classes('font-semibold text-slate-700 mb-2')
                intent_rows = [{"意图": k, "数量": v} for k, v in by_intent.items()]
                ui.table(columns=[{"name": c, "label": c, "field": c} for c in ["意图", "数量"]],
                         rows=intent_rows).classes('w-full mb-4')

            # 最近查询记录
            ui.label('最近查询记录').classes('font-bold text-lg text-slate-800 mb-3')
            recent = tm.query_traces(limit=20)
            if recent:
                rows = []
                for r in recent:
                    rows.append({
                        "时间": str(r.get("timestamp", ""))[:19],
                        "问题": str(r.get("question", ""))[:50],
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
                tool_rows = [{"名称": t.get("name", ""), "描述": t.get("description", "")} for t in tools]
                ui.table(columns=[{"name": c, "label": c, "field": c} for c in ["名称", "描述"]],
                         rows=tool_rows).classes('w-full')
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
