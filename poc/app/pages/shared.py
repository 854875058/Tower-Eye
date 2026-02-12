"""
共享模块 — 导入、配置、单例、SQLite 辅助函数、UI 布局
从 app_ui.py 拆分而来，供各页面模块引用
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

ROOT = Path(__file__).resolve().parents[3]
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

    # 初始化 Ray（如果配置启用）
    try:
        from poc.infra.ray_init import init_ray, create_actors
        if init_ray(config):
            create_actors(config)
    except Exception as e:
        print(f"[Ray] 初始化跳过: {e}")

    _systems_inited = True


# ══════════════════════════════════════════════════════════════════════════
# SQLite 辅助函数
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
