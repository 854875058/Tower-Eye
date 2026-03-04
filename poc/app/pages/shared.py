"""
共享模块 — 导入、配置、单例、DuckDB 辅助函数、UI 布局
从 app_ui.py 拆分而来，供各页面模块引用
"""
import re
import sys
import json
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
    from poc.pipeline.utils import load_yaml, resolve_path
    from poc.qa.agent import create_agent
    from poc.qa.trace import init_trace_manager, get_trace_manager, QueryTrace
    from poc.qa.tools import init_tool_registry, get_tool_registry
    from poc.qa.conversation import init_conversation_manager, get_conversation_manager
    from poc.search.model_manager import ModelManager
    from poc.search.query import hybrid_search, build_asset_id_filter
    from poc.search.duckdb_engine import get_duckdb_engine
    from poc.infra.metrics import init_metrics_collector, get_metrics_collector
    config = load_yaml("poc/config/poc.yaml")
except ImportError as _ie:
    config = {}
    ModelManager = None  # type: ignore
    get_metrics_collector = lambda: None  # type: ignore
    get_conversation_manager = lambda: None  # type: ignore
    print(f"Warning: backend import failed: {_ie}")


def _get_engine():
    """获取 DuckDB 引擎单例"""
    lancedb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))
    return get_duckdb_engine(str(lancedb_dir))

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
        print(f"[ensure_systems] trace_manager 初始化成功: {trace_db}")
    except Exception as e:
        print(f"[ensure_systems] trace_manager 初始化失败: {e}")
        import traceback; traceback.print_exc()

    try:
        db_path = config.get("paths", {}).get("db_path", "poc/data/metadata.db")
        db_abs = resolve_path(db_path)
        if db_abs.exists():
            init_tool_registry(str(db_abs))
            print(f"[ensure_systems] tool_registry 初始化成功: {db_abs}")
        else:
            print(f"[ensure_systems] tool_registry 跳过: db_path 不存在 ({db_abs})")
    except Exception as e:
        print(f"[ensure_systems] tool_registry 初始化失败: {e}")
        import traceback; traceback.print_exc()

    # 初始化 metrics collector
    try:
        metrics_db = Path(config.get("paths", {}).get("metrics_db_path", "logs/metrics.db"))
        metrics_db.parent.mkdir(parents=True, exist_ok=True)
        init_metrics_collector(db_path=metrics_db)
        print(f"[ensure_systems] metrics_collector 初始化成功: {metrics_db}")
    except Exception as e:
        print(f"[ensure_systems] metrics_collector 初始化失败: {e}")
        import traceback; traceback.print_exc()

    # 初始化 conversation manager
    try:
        init_conversation_manager(max_sessions=100, max_turns_per_session=50)
        print(f"[ensure_systems] conversation_manager 初始化成功")
    except Exception as e:
        print(f"[ensure_systems] conversation_manager 初始化失败: {e}")
        import traceback; traceback.print_exc()

    # 初始化 Ray（如果配置启用）
    try:
        from poc.infra.ray_init import init_ray, create_actors
        if init_ray(config):
            create_actors(config)
    except Exception as e:
        print(f"[Ray] 初始化跳过: {e}")

    _systems_inited = True


# ══════════════════════════════════════════════════════════════════════════
# DuckDB 辅助函数（数据统一在 Lance 表中）
# ══════════════════════════════════════════════════════════════════════════

def build_sqlite_filter(filters: dict) -> Tuple[str, list]:
    """构建 SQL 过滤条件（兼容旧接口名，实际走 DuckDB）"""
    clauses, params = [], []
    mapping = [
        ("event_type", "event_type LIKE ?", lambda v: f"%{v}%"),
        ("city_name", "city_name LIKE ?", lambda v: f"%{v}%"),
        ("county_name", "county_name LIKE ?", lambda v: f"%{v}%"),
        ("town_name", "town_name LIKE ?", lambda v: f"%{v}%"),
        ("device_name", "device_name LIKE ?", lambda v: f"%{v}%"),
        ("alarm_level", "alarm_level LIKE ?", lambda v: f"%{v}%"),
        ("order_status", "order_status LIKE ?", lambda v: f"%{v}%"),
        ("algorithm_name", "algorithm_name LIKE ?", lambda v: f"%{v}%"),
        ("algorithm_code", "algorithm_code LIKE ?", lambda v: f"%{v}%"),
        ("device_code", "device_code LIKE ?", lambda v: f"%{v}%"),
        ("importance_level", "importance_level LIKE ?", lambda v: f"%{v}%"),
        ("warning_source_name", "alarm_source LIKE ?", lambda v: f"%{v}%"),
        ("alarm_body", "alarm_body LIKE ?", lambda v: f"%{v}%"),
        ("tenant_name", "tenant_name LIKE ?", lambda v: f"%{v}%"),
        ("channel_name", "channel_name LIKE ?", lambda v: f"%{v}%"),
    ]
    for key, clause, fmt in mapping:
        if filters.get(key):
            clauses.append(clause)
            params.append(fmt(filters[key]))
    if filters.get("confidence_min") is not None:
        clauses.append("confidence_level >= ?"); params.append(filters["confidence_min"])
    if filters.get("confidence_max") is not None:
        clauses.append("confidence_level <= ?"); params.append(filters["confidence_max"])
    if filters.get("start_time"):
        clauses.append("alarm_time >= ?"); params.append(filters["start_time"])
    if filters.get("end_time"):
        clauses.append("alarm_time <= ?"); params.append(filters["end_time"])
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def _inject_sql_filters(sql: str, filters: Dict) -> str:
    conditions = []
    simple = [("event_type", "event_type = '{}'"), ("alarm_level", "alarm_level = '{}'"),
              ("order_status", "order_status = '{}'"), ("city_name", "city_name = '{}'"),
              ("county_name", "county_name = '{}'"), ("town_name", "town_name = '{}'")]
    for k, tpl in simple:
        if filters.get(k): conditions.append(tpl.format(filters[k]))
    if filters.get("device_name"): conditions.append(f"device_name LIKE '%{filters['device_name']}%'")
    if filters.get("algorithm_name"): conditions.append(f"algorithm_name LIKE '%{filters['algorithm_name']}%'")
    if filters.get("confidence_min") is not None: conditions.append(f"confidence_level >= {filters['confidence_min']}")
    if filters.get("confidence_max") is not None: conditions.append(f"confidence_level <= {filters['confidence_max']}")
    if filters.get("start_time"): conditions.append(f"alarm_time >= '{filters['start_time']}'")
    if filters.get("end_time"): conditions.append(f"alarm_time <= '{filters['end_time']}'")
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
    """统计数据量（从 DuckDB/Lance 获取）"""
    try:
        engine = _get_engine()
        total = engine.count("embeddings")
        return {
            "assets": total, "events": total,
            "detections": 0, "annotations": 0, "embeddings": total,
        }
    except Exception:
        return {"assets": 0, "events": 0, "detections": 0, "annotations": 0, "embeddings": 0}


def lance_count() -> int:
    try:
        engine = _get_engine()
        return engine.count("embeddings")
    except Exception:
        return 0


def fetch_events_by_asset_ids(db_path, asset_ids: List[str]) -> Dict[str, dict]:
    """通过 asset_id 列表获取事件详情（从 DuckDB）"""
    if not asset_ids: return {}
    try:
        engine = _get_engine()
        ph = ", ".join("?" for _ in asset_ids)
        rows = engine.execute(
            f"SELECT * FROM events WHERE asset_id IN ({ph})",
            asset_ids
        )
        result = {}
        for rd in rows:
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
    """获取下拉选项（从 DuckDB 直接查询列）"""
    try:
        engine = _get_engine()
    except Exception:
        return {}
    # 这些字段现在是 Lance 表的直接列
    fields = ["tenant_name", "channel_name", "device_name", "device_code",
              "algorithm_name", "algorithm_code", "alarm_source",
              "alarm_body", "importance_level"]
    result = {}
    for f in fields:
        try:
            vals = engine.distinct_values(f)
            if vals:
                result[f] = vals
        except Exception:
            pass
    return result


def get_area_hierarchy(db_path_str: str) -> Dict:
    """获取地区层级（从 DuckDB）"""
    empty = {"cities": [], "county_by_city": {}, "town_by_county": {}}
    try:
        engine = _get_engine()
        rows = engine.execute(
            "SELECT DISTINCT city_name AS city, county_name AS county, town_name AS town "
            "FROM events WHERE city_name IS NOT NULL AND city_name != ''"
        )
    except Exception:
        return empty
    cities = set(); cbc: Dict[str, set] = {}; tbc: Dict[str, set] = {}
    for r in rows:
        city, county, town = r.get("city") or "", r.get("county") or "", r.get("town") or ""
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
# 地图选点组件（高德地图 JS SDK）
# ══════════════════════════════════════════════════════════════════════════

def render_map_picker(state_dict: dict, lat_key: str = 'lat', lon_key: str = 'lon',
                      radius_key: str = 'radius_km', map_id: str = 'map-picker'):
    """嵌入高德地图选点组件，点击设置经纬度，拖拽圆圈设置半径。

    Args:
        state_dict: 绑定的状态字典，选点结果写入 state_dict[lat_key] / state_dict[lon_key]
        lat_key / lon_key / radius_key: 状态字典中的键名
        map_id: DOM 容器 id（同页面多个地图时需不同）
    """
    gaode_cfg = config.get("gaode", {})
    api_key = gaode_cfg.get("api_key", "")
    geocode_url = gaode_cfg.get("geocode_url", "")

    # 地址搜索行
    with ui.row().classes('w-full gap-2 items-center mb-1'):
        geo_input = ui.input('地址搜索', placeholder='如：天安门、深圳市南山区').props('outlined dense').classes('flex-1')

        async def _do_geocode():
            addr = geo_input.value
            if not addr:
                ui.notify('请输入地址', type='warning')
                return
            r = geocode_address(addr, api_key, geocode_url)
            if r:
                lat_val, lon_val, formatted = r
                state_dict[lat_key] = str(lat_val)
                state_dict[lon_key] = str(lon_val)
                ui.notify(f'解析成功: {formatted}', type='positive')
                # 更新地图中心
                try:
                    await ui.run_javascript(f'''
                        if (window._mapPicker_{map_id}) {{
                            var center = new AMap.LngLat({lon_val}, {lat_val});
                            window._mapPicker_{map_id}.setCenter(center);
                            if (window._mapMarker_{map_id}) {{
                                window._mapMarker_{map_id}.setPosition(center);
                            }} else {{
                                window._mapMarker_{map_id} = new AMap.Marker({{position: center, map: window._mapPicker_{map_id}}});
                            }}
                            if (window._mapCircle_{map_id}) {{
                                window._mapCircle_{map_id}.setCenter(center);
                            }}
                        }}
                    ''', timeout=5.0)
                except (TimeoutError, Exception):
                    pass
            else:
                ui.notify('地址解析失败', type='warning')

        ui.button('解析', on_click=_do_geocode).props('outline size=sm rounded')

    # 经纬度 + 半径显示
    with ui.row().classes('w-full gap-3 items-center mb-1'):
        ui.input('纬度', placeholder='lat').bind_value(state_dict, lat_key).props('outlined dense').classes('w-28')
        ui.input('经度', placeholder='lon').bind_value(state_dict, lon_key).props('outlined dense').classes('w-28')
        ui.number('半径(km)', min=0.5, max=100, step=0.5, value=5.0).bind_value(state_dict, radius_key).props('outlined dense').classes('w-28')

    # 地图容器
    map_container = ui.html(f'<div id="{map_id}" style="width:100%;height:280px;border-radius:12px;border:1px solid #e2e8f0;"></div>')

    # 初始化地图 JS
    init_lat = state_dict.get(lat_key, '') or '39.9'
    init_lon = state_dict.get(lon_key, '') or '116.4'
    init_radius = float(state_dict.get(radius_key, 5.0) or 5.0) * 1000

    ui.add_head_html(f'''
    <script src="https://webapi.amap.com/maps?v=2.0&key={api_key}"></script>
    ''')

    async def _init_map():
        try:
            await ui.run_javascript(f'''
            (function() {{
                if (window._mapPicker_{map_id}) return;
                var map = new AMap.Map("{map_id}", {{
                    zoom: 12,
                    center: [{init_lon}, {init_lat}],
                    mapStyle: "amap://styles/light"
                }});
                window._mapPicker_{map_id} = map;

                var marker = new AMap.Marker({{
                    position: [{init_lon}, {init_lat}],
                    map: map, draggable: true
                }});
                window._mapMarker_{map_id} = marker;

                var circle = new AMap.Circle({{
                    center: [{init_lon}, {init_lat}],
                    radius: {init_radius},
                    strokeColor: "#2563eb", strokeWeight: 2, strokeOpacity: 0.6,
                    fillColor: "#2563eb", fillOpacity: 0.1,
                    map: map
                }});
                window._mapCircle_{map_id} = circle;

                map.on('click', function(e) {{
                    var lng = e.lnglat.getLng();
                    var lat = e.lnglat.getLat();
                    marker.setPosition(e.lnglat);
                    circle.setCenter(e.lnglat);
                    emitEvent('map_click_{map_id}', {{lat: lat, lon: lng}});
                }});

                marker.on('dragend', function(e) {{
                    var pos = marker.getPosition();
                    circle.setCenter(pos);
                    emitEvent('map_click_{map_id}', {{lat: pos.getLat(), lon: pos.getLng()}});
                }});
            }})();
            ''', timeout=5.0)
        except (TimeoutError, Exception):
            pass  # 地图初始化失败不影响主功能

    # 监听地图点击事件
    def _on_map_click(e):
        data = e.args if isinstance(e.args, dict) else {}
        if 'lat' in data and 'lon' in data:
            state_dict[lat_key] = str(round(data['lat'], 6))
            state_dict[lon_key] = str(round(data['lon'], 6))

    ui.on(f'map_click_{map_id}', _on_map_click)

    # 页面加载后初始化地图
    ui.timer(0.5, _init_map, once=True)


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
.mermaid svg { width: 100% !important; max-width: none !important; }
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
                ui.label('Tower-Eye'
                         '').classes('text-xl font-bold text-slate-800')
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
