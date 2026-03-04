"""Page 2: 智能问答 — Agent 聊天助手"""
import io
import re
import sys
import json
import base64
import queue
import asyncio
import tempfile
import threading
import traceback
from pathlib import Path as _Path
from typing import Any, Dict, List

from nicegui import ui, events
from poc.app.pages.shared import (
    create_layout, page_header, config, resolve_path,
    ensure_systems, get_agent, get_model_manager, get_trace_manager, QueryTrace,
    get_area_hierarchy, _inject_sql_filters, _get_engine,
    hybrid_search, build_asset_id_filter, fetch_events_by_asset_ids,
    render_map_picker,
)


class _StdoutCapture:
    """线程安全的 stdout 捕获器，同时写入原始 stdout 和 queue"""

    def __init__(self, original, q: queue.Queue):
        self._orig = original
        self._q = q

    def write(self, s):
        if s and s.strip():
            self._q.put(s.rstrip('\n'))
        self._orig.write(s)

    def flush(self):
        self._orig.flush()


# ── 工具函数 ──────────────────────────────────────────────────────────────

def _expand_sql_params(sql: str, params) -> str:
    if not params:
        return sql
    for p in params:
        sql = sql.replace("?", f"'{p}'" if isinstance(p, str) else str(p), 1)
    return sql


def _count_answer(result: dict) -> str:
    ans = result.get("answer")
    if not ans:
        return "N/A"
    v = ans.get("value")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return str(len(v))
    return "1"


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
                    if gv:
                        suggestions.append(f"查询最近20条{gv}的详细信息")
        if not suggestions:
            suggestions.append("查询最近20条告警的详细信息")
    elif intent == "search":
        suggestions = ["找红色挖掘机的图片", "找工地上有卡车的图片", "按告警类型统计数量"]
    else:
        suggestions = ["按告警类型统计数量", "按街道统计告警分布", "按设备统计告警次数TOP10"]
    return suggestions


def _detect_media_cols(cols_raw: List[str]):
    """检测图片/视频列索引"""
    img_cols = []
    video_col = None
    for idx, cn in enumerate(cols_raw):
        cnl = cn.lower()
        if cnl in ('图片路径', 'file_path', '图片文件路径'):
            img_cols.insert(0, idx)
        elif 'img_src' in cnl or '原图' in cnl:
            img_cols.append(idx)
        elif '图片' in cnl and '缩略' not in cnl and 'icon' not in cnl:
            img_cols.append(idx)
        if video_col is None and (cnl in ('视频路径', 'video_path') or '视频' in cnl or 'video' in cnl):
            video_col = idx
    return img_cols, video_col


def _render_detail_fields(row: dict, cols_raw: list, img_cols: list, video_col):
    """渲染记录的完整字段信息（优先字段 + 剩余字段 + extra_json 展开）"""
    PRIORITY = [
        ('event_id', '事件ID'), ('event_type', '事件类型'),
        ('alarm_level', '告警等级'), ('alarm_time', '告警时间'),
        ('alarm_source', '告警来源'), ('alarm_body', '告警主体'),
        ('address', '地址'), ('province_name', '省份'),
        ('city_name', '城市'), ('county_name', '区县'),
        ('town_name', '街道'), ('device_name', '设备名称'),
        ('device_code', '设备编码'), ('channel_name', '通道名称'),
        ('channel_code', '通道编码'), ('algorithm_name', '算法名称'),
        ('algorithm_code', '算法编码'), ('order_status', '工单状态'),
        ('confidence_level', '置信度'), ('confidence_level_max', '最大置信度'),
        ('importance_level', '重要等级'), ('emergency_level', '紧急等级'),
        ('tenant_name', '租户'), ('warning_order_id', '工单ID'),
        ('warning_type_id', '告警类型ID'),
        ('summary', '摘要'), ('description', '描述'),
    ]
    skip = {cols_raw[ic] for ic in img_cols}
    if video_col is not None:
        skip.add(cols_raw[video_col])
    # 媒体相关列在右侧 tab 展示，左侧字段列表中跳过
    for media_col in ('img_icon_path', 'img_src_path', 'file_path', 'video_path'):
        if media_col in cols_raw:
            skip.add(media_col)
    shown = set()
    for key, label in PRIORITY:
        v = row.get(key)
        if v is not None and str(v).strip():
            shown.add(key)
            val_str = f'{v:.2f}' if isinstance(v, float) else str(v)
            with ui.row().classes('gap-2'):
                ui.label(f'{label}:').classes('text-xs text-slate-400 w-20 flex-shrink-0')
                ui.label(val_str).classes('text-xs text-slate-700')
    for key in cols_raw:
        if key in shown or key in skip:
            continue
        v = row.get(key)
        if v is None or not str(v).strip():
            continue
        if key == 'extra_json':
            try:
                extra = json.loads(v) if isinstance(v, str) else v
                if isinstance(extra, dict):
                    with ui.expansion('扩展字段', icon='data_object').classes('w-full').props('dense'):
                        for ek, ev in sorted(extra.items()):
                            if ev is not None and str(ev).strip():
                                with ui.row().classes('gap-2'):
                                    ui.label(f'{ek}:').classes('text-xs text-slate-400 w-28 flex-shrink-0')
                                    ui.label(str(ev)).classes('text-xs text-slate-700 break-all')
                    continue
            except Exception:
                pass
        val_str = f'{v:.2f}' if isinstance(v, float) else str(v)
        with ui.row().classes('gap-2'):
            ui.label(f'{key}:').classes('text-xs text-slate-400 w-20 flex-shrink-0')
            ui.label(val_str).classes('text-xs text-slate-700 break-all')


def _draw_yolo_boxes(img_path: str, detections: list) -> str:
    """在图片上绘制 YOLO 检测框，返回 base64 data URI。cv2 不可用时返回空字符串。"""
    try:
        import cv2
        import numpy as np
        full = str(resolve_path(f'warning_img/{_Path(img_path).name}'))
        img = cv2.imread(full)
        if img is None:
            return ""
        h, w = img.shape[:2]
        colors = [(0, 255, 0), (255, 0, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255)]
        for i, det in enumerate(detections):
            color = colors[i % len(colors)]
            if all(k in det for k in ('bbox_x', 'bbox_y', 'bbox_w', 'bbox_h')):
                bx, by, bw, bh = det['bbox_x'], det['bbox_y'], det['bbox_w'], det['bbox_h']
                if all(0 <= v <= 1.0 for v in (bx, by, bw, bh)):
                    bx, by, bw, bh = bx * w, by * h, bw * w, bh * h
                x1, y1 = int(bx), int(by)
                x2, y2 = int(bx + bw), int(by + bh)
            elif 'bbox' in det and isinstance(det['bbox'], (list, tuple)) and len(det['bbox']) == 4:
                coords = det['bbox']
                if all(0 <= v <= 1.0 for v in coords):
                    coords = [coords[0]*w, coords[1]*h, coords[2]*w, coords[3]*h]
                x1, y1, x2, y2 = [int(c) for c in coords]
            else:
                continue
            label = det.get('label', '')
            conf = det.get('confidence', 0)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            if label:
                txt = f"{label} {conf:.2f}" if conf else label
                cv2.putText(img, txt, (x1, max(y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        b64 = base64.b64encode(buf.tobytes()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


def _parse_detections(row: dict) -> list:
    """从 row 的 extra_json 中解析检测结果列表。"""
    raw = row.get('extra_json', '')
    if not raw:
        return []
    try:
        extra = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    if not isinstance(extra, dict):
        return []
    for key in ('detections', 'detection_results', 'bbox_list', 'objects'):
        if key in extra and isinstance(extra[key], list):
            return extra[key]
    return []


def _find_sibling_images(row: dict) -> list:
    """根据 video_path / extra_json.video_url 查找同源视频的所有关联图片。
    返回去重后的文件名列表（不含当前记录自身）。"""
    video_stem = ""
    vp = row.get('video_path', '')
    if vp:
        video_stem = _Path(str(vp).split(",")[0].strip()).stem
    if not video_stem:
        raw = row.get('extra_json', '')
        if raw:
            try:
                extra = json.loads(raw) if isinstance(raw, str) else raw
                vu = extra.get('video_url', '')
                if vu:
                    video_stem = _Path(str(vu).split(",")[0].strip()).stem
            except Exception:
                pass
    if not video_stem:
        return []
    try:
        engine = _get_engine()
        siblings = engine.execute(
            "SELECT file_path, img_src_path FROM events WHERE extra_json LIKE ? LIMIT 30",
            [f'%{video_stem}%'])
        # 收集所有可用图片路径（去重，排除当前记录）
        current_src = _Path(row.get('img_src_path', '') or '').name
        seen = set()
        result = []
        for s in siblings:
            for col in ('img_src_path', 'file_path'):
                fp = s.get(col, '')
                if fp:
                    name = _Path(fp).name
                    if name and name not in seen and name != current_src:
                        seen.add(name)
                        result.append(name)
        return result
    except Exception:
        return []


def _render_media_panel(panel_id: str, file_path: str, img_src: str,
                        img_icon: str, video_path: str,
                        detections: list, siblings: list, row_idx: int):
    """渲染单个媒体面板内容。"""
    if panel_id == 'alert_img' and file_path:
        img_name = _Path(file_path).name
        img_url = f'/warning_img/{img_name}'
        img_el = ui.image(img_url).classes('w-full rounded cursor-pointer')
        with ui.dialog() as dlg:
            with ui.card().classes('p-2'):
                ui.image(img_url).classes('max-w-[80vw] max-h-[80vh]')
                ui.button('关闭', on_click=dlg.close).props('flat color=grey')
        img_el.on('click', dlg.open)

    elif panel_id == 'icon_img' and img_icon:
        # img_icon_path 是带标注框的版本（_02_ 系列）
        for sp in str(img_icon).split(','):
            sp = sp.strip()
            if sp:
                icon_name = _Path(sp).name
                icon_url = f'/warning_img/{icon_name}'
                icon_el = ui.image(icon_url).classes('w-full rounded cursor-pointer mb-1')
                with ui.dialog() as dlg2:
                    with ui.card().classes('p-2'):
                        ui.image(icon_url).classes('max-w-[80vw] max-h-[80vh]')
                        ui.button('关闭', on_click=dlg2.close).props('flat color=grey')
                icon_el.on('click', dlg2.open)

    elif panel_id == 'video' and video_path:
        vn = _Path(str(video_path).split(",")[0].strip()).name
        ui.video(f'/warning_file/{vn}').classes('w-full rounded').props('controls')

    elif panel_id == 'yolo' and detections and file_path:
        annotated_uri = _draw_yolo_boxes(file_path, detections)
        if annotated_uri:
            ann_el = ui.image(annotated_uri).classes('w-full rounded cursor-pointer')
            with ui.dialog() as dlg3:
                with ui.card().classes('p-2'):
                    ui.image(annotated_uri).classes('max-w-[80vw] max-h-[80vh]')
                    ui.button('关闭', on_click=dlg3.close).props('flat color=grey')
            ann_el.on('click', dlg3.open)
        else:
            ui.label('YOLO (cv2 unavailable)').classes('text-xs text-slate-500 mb-1')
        for det in detections:
            lbl = det.get('label', '?')
            conf = det.get('confidence', 0)
            conf_str = f" ({conf:.0%})" if conf else ""
            ui.label(f"  - {lbl}{conf_str}").classes('text-xs text-slate-600 font-mono')

    elif panel_id == 'related' and siblings:
        ui.label(f'同源视频共 {len(siblings)} 张关联图片').classes('text-xs text-slate-500 mb-1')
        with ui.row().classes('flex-wrap gap-1'):
            for fname in siblings[:12]:
                sib_url = f'/warning_img/{fname}'
                sib_el = ui.image(sib_url).classes('w-16 h-12 object-cover rounded cursor-pointer')
                with ui.dialog() as dlg4:
                    with ui.card().classes('p-2'):
                        ui.image(sib_url).classes('max-w-[80vw] max-h-[80vh]')
                        ui.button('关闭', on_click=dlg4.close).props('flat color=grey')
                sib_el.on('click', dlg4.open)


def _render_search_results(results: list, question: str):
    """渲染向量检索结果为图片卡片网格（在聊天气泡内）"""
    with ui.row().classes('flex-wrap gap-3 w-full'):
        for idx, item in enumerate(results[:20]):
            fp = item.get('file_path', '')
            img_name = _Path(fp).name if fp else ''
            img_url = f'/warning_img/{img_name}' if img_name else ''
            score = item.get('hybrid_score', item.get('_distance', 0))
            if 0 < score < 1.0:
                score = 1.0 / (1.0 + score)

            with ui.card().classes('w-56 shadow-sm hover:shadow-md transition-shadow'):
                if img_url:
                    card_img = ui.image(img_url).classes('w-full h-36 object-cover')
                    with ui.dialog() as dlg:
                        with ui.card().classes('p-2'):
                            ui.image(img_url).classes('max-w-[80vw] max-h-[80vh]')
                            ui.button('关闭', on_click=dlg.close).props('flat color=grey')
                    card_img.on('click', dlg.open)
                else:
                    with ui.element('div').classes('w-full h-36 bg-slate-100 flex items-center justify-center'):
                        ui.icon('image_not_supported').classes('text-3xl text-slate-300')

                with ui.column().classes('p-2 gap-0.5'):
                    if score > 0:
                        ui.label(f'相似度: {score:.3f}').classes('text-xs text-blue-600 font-semibold')
                    et = item.get('event_type', '')
                    if et:
                        ui.label(et).classes('text-xs text-slate-800 font-medium truncate')
                    at = item.get('alarm_time', '')
                    if at:
                        ui.label(str(at)[:19]).classes('text-xs text-slate-400')
                    summary = item.get('summary', '')
                    if summary:
                        ui.label(summary[:50] + ('...' if len(summary) > 50 else '')).classes('text-xs text-slate-500')
                    addr = item.get('address', '')
                    if addr:
                        ui.label(addr[:30]).classes('text-xs text-slate-400 truncate')


# ── 页面 ──────────────────────────────────────────────────────────────────

@ui.page('/qa')
def qa_page():
    with create_layout('/qa'):
        page_header('智能问答 · Agent 助手',
                     '基于 LangGraph Agent 的对话式数据分析，支持 NL2SQL、图表、媒体预览')

        ensure_systems()
        _db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))

        # ── per-client state ──
        chat_history: List[Dict[str, Any]] = []  # [{role, content, result}]

        # ── 预设快捷问题 ──
        presets = [
            "按街道统计最近30天各类告警数量",
            "查询最近20条车辆闯入告警的详细信息",
            "统计各设备触发告警次数最多的TOP10",
            "查询置信度大于0.9的高置信告警",
        ]
        with ui.row().classes('w-full gap-2 mb-2 flex-wrap'):
            for q in presets:
                ui.button(q[:14] + '...', on_click=lambda q=q: do_ask(q)) \
                    .props('outline size=sm color=blue-6 rounded-lg no-caps')

        # ── 高级筛选面板 ──
        qa_filters_state: Dict[str, Any] = {
            'event_type': '', 'alarm_level': '', 'order_status': '',
            'city': '', 'county': '', 'town': '',
            'device_name': '', 'algorithm_name': '',
            'confidence_min': 0.0, 'confidence_max': 1.0,
            'enable_geo': False, 'lat': '', 'lon': '', 'radius_km': 5.0,
        }
        area_h = get_area_hierarchy(str(_db_path))

        with ui.expansion('高级筛选', icon='tune').classes('w-full mb-2 bg-white rounded-xl'):
            with ui.grid(columns=3).classes('w-full gap-3 p-4'):
                ui.input('事件类型', placeholder='如：车辆闯入监控告警').bind_value(qa_filters_state, 'event_type').props('outlined dense')
                ui.select({'' : '全部', '01': '等级01'}, label='告警等级').bind_value(qa_filters_state, 'alarm_level').props('outlined dense')
                ui.select({'': '全部', '1': '待处理', '2': '处理中', '4': '已完成', '6': '已关闭'}, label='工单状态') \
                    .bind_value(qa_filters_state, 'order_status').props('outlined dense')
            with ui.grid(columns=3).classes('w-full gap-3 px-4'):
                city_opts = {'': '全部'}
                city_opts.update({c: c for c in area_h['cities']})
                ui.select(city_opts, label='城市').bind_value(qa_filters_state, 'city').props('outlined dense')
                county_opts = {'': '全部'}
                for cs in area_h['county_by_city'].values():
                    for c in cs:
                        county_opts[c] = c
                ui.select(county_opts, label='区/县').bind_value(qa_filters_state, 'county').props('outlined dense')
                town_opts = {'': '全部'}
                for ts in area_h['town_by_county'].values():
                    for t in ts:
                        town_opts[t] = t
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
            with ui.column().classes('w-full px-4 pb-4 gap-2'):
                ui.switch('启用地理位置过滤').bind_value(qa_filters_state, 'enable_geo')
                render_map_picker(qa_filters_state, lat_key='lat', lon_key='lon',
                                  radius_key='radius_km', map_id='qa-map')

        def collect_qa_filters() -> Dict:
            f = {}
            for k in ['event_type', 'alarm_level', 'order_status', 'device_name', 'algorithm_name']:
                if qa_filters_state.get(k):
                    f[k] = qa_filters_state[k]
            if qa_filters_state.get('city'):
                f['city_name'] = qa_filters_state['city']
            if qa_filters_state.get('county'):
                f['county_name'] = qa_filters_state['county']
            if qa_filters_state.get('town'):
                f['town_name'] = qa_filters_state['town']
            if qa_filters_state['confidence_min'] > 0:
                f['confidence_min'] = qa_filters_state['confidence_min']
            if qa_filters_state['confidence_max'] < 1:
                f['confidence_max'] = qa_filters_state['confidence_max']
            return f

        def _build_filter_context(filters: Dict) -> str:
            """将筛选条件转为自然语言上下文，拼接到用户问题前"""
            parts = []
            label_map = {
                'event_type': '事件类型', 'alarm_level': '告警等级',
                'order_status': '工单状态', 'device_name': '设备名称',
                'algorithm_name': '算法名称', 'city_name': '城市',
                'county_name': '区县', 'town_name': '街道',
            }
            for k, label in label_map.items():
                if filters.get(k):
                    parts.append(f"{label}={filters[k]}")
            if filters.get('confidence_min'):
                parts.append(f"置信度>={filters['confidence_min']}")
            if filters.get('confidence_max') and filters['confidence_max'] < 1:
                parts.append(f"置信度<={filters['confidence_max']}")
            if not parts:
                return ""
            return "[筛选条件: " + ", ".join(parts) + "] "

        # ── 聊天消息区 ──
        chat_scroll = ui.scroll_area().classes('w-full border rounded-xl bg-slate-50').style('height: 60vh')
        chat_container = ui.column().classes('w-full p-4 gap-4')
        # 将 chat_container 移入 scroll_area
        chat_scroll.clear()
        with chat_scroll:
            chat_container = ui.column().classes('w-full p-4 gap-4')

        def _render_user_bubble(text: str):
            """渲染用户消息气泡（右对齐）"""
            with ui.row().classes('w-full justify-end'):
                with ui.element('div').classes(
                    'bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-2 max-w-[70%] shadow-sm'
                ):
                    ui.label(text).classes('text-sm')

        def _render_agent_bubble(result: dict, question: str):
            """渲染 Agent 回复气泡（左对齐），包含思考过程、SQL、表格、媒体、追问"""
            with ui.row().classes('w-full justify-start items-start gap-2').style('max-width:100%;overflow:hidden'):
                ui.icon('smart_toy').classes('text-blue-500 text-2xl mt-1 flex-shrink-0')
                with ui.column().classes(
                    'bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm gap-2 min-w-0'
                ).style('max-width:calc(100% - 48px);overflow-x:auto'):
                    # 状态指标行
                    status_ok = result.get("status") == "success"
                    with ui.row().classes('gap-3 items-center'):
                        if status_ok:
                            ui.badge('查询成功', color='green').props('outline')
                        else:
                            ui.badge('查询失败', color='red').props('outline')
                        ui.label(f'意图: {result.get("intent", "未知")}').classes('text-xs text-slate-500')
                        retry = result.get("retry_count", 0)
                        if retry > 0:
                            ui.label(f'重试: {retry}').classes('text-xs text-orange-500')

                    # 错误信息
                    if not status_ok and result.get("error"):
                        ui.label(result["error"]).classes('text-sm text-red-500')

                    # 思考过程（实时日志回放）
                    thinking_lines = result.get('_thinking_lines') or []
                    exec_hist = result.get("execution_history") or []
                    if thinking_lines or exec_hist or result.get("intent"):
                        with ui.expansion('思考过程', icon='psychology').classes('w-full').props('dense'):
                            if thinking_lines:
                                with ui.element('div').classes(
                                    'w-full bg-slate-900 rounded-lg p-3 font-mono text-xs '
                                    'leading-relaxed max-h-48 overflow-y-auto'
                                ).style('scrollbar-width:thin'):
                                    for line in thinking_lines:
                                        _render_log_line(line)
                            elif exec_hist:
                                # fallback: 没有实时日志时用 execution_history
                                with ui.element('div').classes('pl-3 border-l-2 border-blue-200 space-y-1'):
                                    intent = result.get("intent", "未知")
                                    with ui.row().classes('items-center gap-1'):
                                        ui.icon('search').classes('text-blue-400 text-sm')
                                        ui.label(f'意图识别 → {intent}').classes('text-xs text-slate-600')
                                    for i, rec in enumerate(exec_hist):
                                        ok = rec.get("status") == "success"
                                        icon_name = 'check_circle' if ok else 'error'
                                        icon_color = 'text-green-500' if ok else 'text-red-400'
                                        with ui.row().classes('items-start gap-1'):
                                            ui.icon(icon_name).classes(f'{icon_color} text-sm mt-0.5')
                                            with ui.column().classes('gap-0'):
                                                if ok:
                                                    ui.label(f'执行成功 → 返回 {rec.get("result_count", 0)} 条').classes('text-xs text-green-600')
                                                else:
                                                    err_msg = str(rec.get("error", ""))[:60]
                                                    ui.label(f'执行失败 → {err_msg}').classes('text-xs text-red-500')

                    # SQL 折叠（最终 SQL，可编辑）
                    sql_text = _expand_sql_params(result.get("sql", ""), result.get("sql_params"))
                    if sql_text:
                        with ui.expansion('SQL', icon='code').classes('w-full').props('dense'):
                            ui.code(sql_text, language='sql').classes('w-full text-xs')
                            # SQL 编辑 + 重新执行
                            sql_editor = ui.textarea(value=sql_text).classes('w-full font-mono text-xs mt-1').props('outlined dense rows=3')

                            async def rerun_sql(editor=sql_editor, res=result):
                                try:
                                    engine = _get_engine()
                                    new_data = engine.execute(editor.value)
                                    sql_upper = editor.value.upper()
                                    has_agg = any(fn in sql_upper for fn in ("COUNT(", "SUM(", "AVG("))
                                    new_intent = "count" if has_agg and "GROUP BY" in sql_upper else res.get("intent", "list")
                                    if new_intent == "count" and len(new_data) == 1 and len(new_data[0]) == 1:
                                        res["answer"] = {"type": "count", "value": list(new_data[0].values())[0],
                                                         "message": f"共 {list(new_data[0].values())[0]} 条"}
                                    else:
                                        res["answer"] = {"type": "list", "value": new_data,
                                                         "message": f"返回 {len(new_data)} 条记录"}
                                    res["sql"] = editor.value
                                    res["intent"] = new_intent
                                    res["status"] = "success"
                                    _refresh_chat()
                                    try:
                                        ui.notify('SQL 重新执行成功', type='positive')
                                    except RuntimeError:
                                        pass
                                except Exception as e:
                                    try:
                                        ui.notify(f'SQL 执行失败: {e}', type='negative')
                                    except RuntimeError:
                                        pass

                            ui.button('重新执行', icon='refresh', on_click=rerun_sql) \
                                .props('outline color=blue-6 rounded no-caps size=xs').classes('mt-1')

                    # 查询结果
                    answer = result.get("answer")
                    if answer:
                        answer_data = answer.get("value")

                        # ── chat 类型：纯文本回复 ──
                        if answer.get("type") == "chat":
                            ui.markdown(str(answer_data)).classes('text-sm text-slate-700')

                        # ── search 类型：向量检索结果（图片卡片网格） ──
                        elif answer.get("type") == "search" and isinstance(answer_data, list) and len(answer_data) > 0:
                            ui.label(answer.get("message", "")).classes('text-sm text-blue-600 mb-1')
                            _render_search_results(answer_data, question)

                        # ── list 类型：表格 + 媒体 ──
                        elif isinstance(answer_data, list) and len(answer_data) > 0 and isinstance(answer_data[0], dict):
                            # 语义融合信息
                            _sem_scores = answer.get("semantic_scores") or {}
                            _vec_only = answer.get("vector_only_results") or []
                            with ui.row().classes('gap-2 items-center'):
                                ui.label(f'共 {len(answer_data)} 条记录').classes('text-sm text-blue-600')
                                if _sem_scores:
                                    _matched = sum(1 for r in answer_data
                                                   if r.get("file_path") and _Path(r["file_path"]).name in _sem_scores)
                                    ui.badge(f'语义匹配 {_matched}/{len(answer_data)}',
                                             color='purple').props('outline')
                            cols_raw = list(answer_data[0].keys())
                            # 默认隐藏的列：路径类长字段、内部ID、编码类字段
                            _HIDDEN_COLS = {
                                'extra_json', 'file_path', 'video_path',
                                'img_src_path', 'img_icon_path',
                                'event_id', 'warning_order_id', 'warning_type_id',
                                'channel_code', 'algorithm_code', 'town_code',
                                'device_code', 'tenant_name',
                                'province_name', 'city_name',
                            }
                            tbl_cols_all = [c for c in cols_raw if c != 'extra_json']
                            tbl_cols = [{"name": c, "label": c.replace('_', ' ').title(), "field": c, "sortable": True} for c in tbl_cols_all]
                            visible_cols = [c for c in tbl_cols_all if c not in _HIDDEN_COLS]
                            tbl_rows = [{k: v for k, v in row.items() if k != 'extra_json'} for row in answer_data[:50]]
                            with ui.element('div').classes('w-full overflow-x-auto'):
                                ui.table(columns=tbl_cols, rows=tbl_rows,
                                         pagination={"rowsPerPage": 5}).classes('w-full text-xs').props(
                                    f'dense wrap-cells visible-columns={json.dumps(visible_cols)}'
                                )

                            # 媒体预览
                            img_cols, video_col = _detect_media_cols(cols_raw)
                            if img_cols or video_col is not None:
                                ui.label('媒体预览').classes('text-xs font-semibold text-slate-600 mt-2')
                                with ui.row().classes('flex-wrap gap-2'):
                                    for ri, row in enumerate(answer_data[:9]):
                                        shown = False
                                        with ui.element('div').classes('w-32'):
                                            for ic in img_cols:
                                                if shown:
                                                    break
                                                iv = row.get(cols_raw[ic], "")
                                                if iv:
                                                    ui.image(f'/warning_img/{_Path(str(iv)).name}') \
                                                        .classes('w-32 h-24 object-cover rounded cursor-pointer')
                                                    shown = True
                                            if video_col is not None:
                                                vv = row.get(cols_raw[video_col], "")
                                                if vv:
                                                    vn = _Path(str(vv).split(",")[0].strip()).name
                                                    ui.video(f'/warning_file/{vn}').classes('w-32 rounded')
                                                    shown = True
                                            if not shown:
                                                with ui.element('div').classes('w-32 h-24 bg-slate-100 rounded flex items-center justify-center'):
                                                    ui.icon('image_not_supported').classes('text-slate-300')

                            # 详情展开：每条记录可展开查看完整字段 + 图片 + 视频
                            with ui.expansion('查看详情', icon='info').classes('w-full').props('dense'):
                                for ri, row in enumerate(answer_data[:20]):
                                    # 标题：取事件类型+时间做摘要
                                    title_parts = []
                                    if row.get('event_type'):
                                        title_parts.append(str(row['event_type'])[:15])
                                    if row.get('alarm_time'):
                                        title_parts.append(str(row['alarm_time'])[:19])
                                    # 语义匹配分数
                                    _row_fp = row.get('file_path', '')
                                    _row_fname = _Path(_row_fp).name if _row_fp else ''
                                    _row_score = _sem_scores.get(_row_fname)
                                    _score_tag = f' [语义 {_row_score:.0%}]' if _row_score else ''
                                    title = ' | '.join(title_parts) if title_parts else f'记录 {ri+1}'
                                    with ui.expansion(f'第 {ri+1} 条 — {title}{_score_tag}', icon='description').classes('w-full').props('dense'):
                                        # VL 图像理解摘要
                                        _summary = row.get('summary', '')
                                        if _summary and str(_summary).strip():
                                            with ui.row().classes('w-full gap-2 items-start mb-1 bg-purple-50 rounded p-2'):
                                                ui.icon('visibility').classes('text-purple-400 text-sm mt-0.5')
                                                ui.label(str(_summary)).classes('text-xs text-purple-700 italic')
                                        with ui.row().classes('w-full gap-4 items-start'):
                                            # 左侧：完整字段
                                            with ui.column().classes('flex-1 gap-0.5 min-w-0'):
                                                _render_detail_fields(row, cols_raw, img_cols, video_col)
                                            # 右侧：媒体增强预览（tabs）
                                            # 收集可用媒体
                                            _file_path = ""
                                            for ic in img_cols:
                                                iv = row.get(cols_raw[ic], "")
                                                if iv:
                                                    _file_path = str(iv)
                                                    break
                                            _img_src = row.get('img_src_path', '') or ''
                                            _img_icon = row.get('img_icon_path', '') or ''
                                            _video_path = ''
                                            if video_col is not None:
                                                _video_path = row.get(cols_raw[video_col], '') or ''
                                            _detections = _parse_detections(row)
                                            # 关联图片改为懒加载，不在渲染时查询
                                            _has_video = bool(_video_path)

                                            # 判断 img_src 和 file_path 是否同一张图
                                            _fp_name = _Path(_file_path).name if _file_path else ''
                                            _src_name = _Path(_img_src).name if _img_src else ''
                                            _icon_name = _Path(str(_img_icon).split(',')[0].strip()).name if _img_icon else ''
                                            _src_is_same = (_src_name == _fp_name)
                                            _icon_is_same = (_icon_name == _fp_name) or (_icon_name == _src_name)

                                            has_media = bool(_file_path or _img_src or _video_path)
                                            if has_media or _detections or _has_video or (_img_icon and not _icon_is_same):
                                                with ui.column().classes('gap-1 flex-shrink-0').style('width:400px'):
                                                    # 构建动态 tabs
                                                    tab_defs = []
                                                    if _file_path:
                                                        tab_defs.append(('alert_img', 'photo', '原图'))
                                                    if _img_icon and not _icon_is_same:
                                                        tab_defs.append(('icon_img', 'crop_square', '标注框图'))
                                                    if _video_path:
                                                        tab_defs.append(('video', 'videocam', '视频'))
                                                    if _detections and _file_path:
                                                        tab_defs.append(('yolo', 'auto_fix_high', 'YOLO'))
                                                    # 关联 tab 始终添加（有视频时），内容懒加载
                                                    if _has_video:
                                                        tab_defs.append(('related', 'collections', '关联'))

                                                    if len(tab_defs) == 1:
                                                        _tid, _, _ = tab_defs[0]
                                                        _render_media_panel(_tid, _file_path, _img_src, _img_icon, _video_path, _detections, [], ri)
                                                    elif tab_defs:
                                                        with ui.tabs().classes('w-full').props('dense no-caps') as tabs:
                                                            tab_objs = {}
                                                            for _tid, _icon_i, _label in tab_defs:
                                                                tab_objs[_tid] = ui.tab(_tid, label=_label, icon=_icon_i)
                                                        with ui.tab_panels(tabs, value=tab_defs[0][0]).classes('w-full'):
                                                            for _tid, _, _ in tab_defs:
                                                                with ui.tab_panel(_tid):
                                                                    if _tid == 'related':
                                                                        # 懒加载关联图片
                                                                        _lazy_container = ui.column().classes('w-full')
                                                                        _lazy_loaded = {'done': False}
                                                                        _cur_row = row

                                                                        def _load_related(container=_lazy_container, r=_cur_row, loaded=_lazy_loaded):
                                                                            if loaded['done']:
                                                                                return
                                                                            loaded['done'] = True
                                                                            siblings = _find_sibling_images(r)
                                                                            container.clear()
                                                                            with container:
                                                                                if siblings:
                                                                                    ui.label(f'找到 {len(siblings)} 张关联图片').classes('text-xs text-slate-500 mb-1')
                                                                                    with ui.row().classes('flex-wrap gap-1'):
                                                                                        for sib_name in siblings[:12]:
                                                                                            sib_url = f'/warning_img/{sib_name}'
                                                                                            sib_el = ui.image(sib_url).classes('w-16 h-12 object-cover rounded cursor-pointer')
                                                                                            with ui.dialog() as dlg:
                                                                                                with ui.card().classes('p-2'):
                                                                                                    ui.image(sib_url).classes('max-w-[80vw] max-h-[80vh]')
                                                                                                    ui.button('关闭', on_click=dlg.close).props('flat color=grey')
                                                                                            sib_el.on('click', dlg.open)
                                                                                else:
                                                                                    ui.label('无关联图片').classes('text-xs text-slate-400')

                                                                        # tab 切换时触发加载
                                                                        tabs.on('update:model-value',
                                                                                lambda e, fn=_load_related, tid='related': fn() if (isinstance(e.args, str) and e.args == tid) or (hasattr(e, 'value') and e.value == tid) else None)
                                                                    else:
                                                                        _render_media_panel(_tid, _file_path, _img_src, _img_icon, _video_path, _detections, [], ri)

                            # 语义融合：向量检索独有结果推荐
                            if _vec_only:
                                with ui.expansion(f'您可能还感兴趣 ({len(_vec_only)})', icon='auto_awesome').classes('w-full').props('dense'):
                                    ui.label('以下结果来自图像语义检索，与您的查询在视觉内容上相关').classes('text-xs text-purple-500 mb-1')
                                    for vi, vr in enumerate(_vec_only):
                                        _vr_fp = vr.get('file_path', '')
                                        _vr_fname = _Path(_vr_fp).name if _vr_fp else ''
                                        _vr_score = vr.get('hybrid_score', 0)
                                        _vr_summary = vr.get('summary', '')
                                        _vr_etype = vr.get('event_type', '')
                                        _vr_time = str(vr.get('alarm_time', ''))[:19]
                                        _vr_title = f'{_vr_etype} | {_vr_time}' if _vr_etype else f'推荐 {vi+1}'
                                        with ui.row().classes('w-full gap-3 items-start p-2 bg-purple-50 rounded mb-1'):
                                            if _vr_fname:
                                                _vr_url = f'/warning_img/{_vr_fname}'
                                                vr_el = ui.image(_vr_url).classes('w-24 h-18 object-cover rounded cursor-pointer flex-shrink-0')
                                                with ui.dialog() as vr_dlg:
                                                    with ui.card().classes('p-2'):
                                                        ui.image(_vr_url).classes('max-w-[80vw] max-h-[80vh]')
                                                        ui.button('关闭', on_click=vr_dlg.close).props('flat color=grey')
                                                vr_el.on('click', vr_dlg.open)
                                            with ui.column().classes('flex-1 gap-0.5 min-w-0'):
                                                with ui.row().classes('gap-2 items-center'):
                                                    ui.label(_vr_title).classes('text-xs font-semibold text-slate-700')
                                                    if _vr_score:
                                                        ui.badge(f'语义 {_vr_score:.0%}', color='purple').props('outline')
                                                if _vr_summary:
                                                    ui.label(str(_vr_summary)[:100]).classes('text-xs text-slate-500 italic')

                            # count 类型 → 查看明细按钮
                            if result.get("intent") == "count":
                                first_row = answer_data[0]
                                group_key = next((k for k, v in first_row.items() if not isinstance(v, (int, float))), None)
                                if group_key:
                                    time_m = re.search(r'(最近\d+[天小时月年周]|本[月周年日]|今[天年月])', question)
                                    time_cond = time_m.group(1) + "内" if time_m else ""
                                    with ui.row().classes('flex-wrap gap-1 mt-1'):
                                        for row in answer_data:
                                            gv = row.get(group_key, "")
                                            cnt_vals = [v for v in row.values() if isinstance(v, (int, float))]
                                            cnt_str = f"({int(cnt_vals[0])})" if cnt_vals else ""
                                            if gv:
                                                ui.button(f'{gv}{cnt_str}',
                                                          on_click=lambda gv=gv: do_ask(f"查询{time_cond}最近20条{gv}的详细信息")) \
                                                    .props('outline size=xs color=blue-6 rounded-lg no-caps')

                        # ── int 类型：KPI 卡片 ──
                        elif isinstance(answer_data, int):
                            with ui.element('div').classes('kpi-card text-center my-2'):
                                ui.label(f'{answer_data:,}').classes('text-2xl font-bold text-blue-600')
                                ui.label('统计结果').classes('text-xs text-slate-500')

                        # ── 其他类型 ──
                        elif answer_data is not None:
                            ui.code(json.dumps(answer, ensure_ascii=False, indent=2), language='json').classes('w-full text-xs')

                    # 追问建议
                    suggestions = _build_suggestions(result, answer.get("value") if answer else None)
                    if suggestions:
                        ui.separator().classes('my-1')
                        ui.label('追问建议').classes('text-xs text-slate-500')
                        with ui.row().classes('flex-wrap gap-1'):
                            for s in suggestions[:4]:
                                ui.button(f'{s[:18]}{"..." if len(s)>18 else ""}',
                                          on_click=lambda s=s: do_ask(s)) \
                                    .props('outline size=xs color=teal-6 rounded-lg no-caps')

        def _render_thinking_bubble(thinking_lines: List[str] = None):
            """渲染 Agent 思考中的气泡，带实时日志"""
            with ui.row().classes('w-full justify-start items-start gap-2'):
                ui.icon('smart_toy').classes('text-blue-500 text-2xl mt-1 flex-shrink-0')
                with ui.column().classes(
                    'bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm gap-2 flex-1 min-w-0'
                ):
                    with ui.row().classes('items-center gap-2'):
                        ui.spinner('dots', size='sm', color='blue')
                        ui.label('Agent 正在思考...').classes('text-sm text-slate-400')
                    # 实时日志区
                    lines = thinking_lines or []
                    if lines:
                        with ui.element('div').classes(
                            'w-full bg-slate-900 rounded-lg p-3 font-mono text-xs '
                            'leading-relaxed max-h-64 overflow-y-auto'
                        ).style('scrollbar-width:thin'):
                            for line in lines:
                                _render_log_line(line)

        def _render_log_line(line: str):
            """根据日志内容着色"""
            if '成功' in line or 'success' in line.lower():
                color = 'text-green-400'
            elif '失败' in line or 'error' in line.lower() or 'Error' in line:
                color = 'text-red-400'
            elif line.startswith('[') and ']' in line:
                color = 'text-blue-300'
            elif line.startswith('==='):
                color = 'text-slate-500'
            else:
                color = 'text-slate-300'
            ui.label(line).classes(f'{color} whitespace-pre-wrap break-all')

        def _render_welcome():
            """渲染欢迎页"""
            with ui.row().classes('w-full justify-start items-start gap-2'):
                ui.icon('smart_toy').classes('text-blue-500 text-2xl mt-1 flex-shrink-0')
                with ui.column().classes(
                    'bg-white rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm gap-3 min-w-0'
                ).style('max-width:calc(100% - 48px)'):
                    ui.label('你好！我是多模态检索 Agent 助手 👋').classes('text-base font-semibold text-slate-800')
                    ui.label(
                        '我可以帮你用自然语言查询告警数据，支持统计分析、条件筛选、图片视频预览。'
                        '直接输入问题即可，我会自动生成 SQL 并执行。'
                    ).classes('text-sm text-slate-500 leading-relaxed')

                    # 用法示例
                    ui.separator().classes('my-1 opacity-30')
                    ui.label('💡 我能做什么').classes('text-xs font-semibold text-slate-600')
                    examples = [
                        ('📊 统计分析', '按街道统计告警数量、按设备统计TOP10、按类型分布...'),
                        ('🔍 条件查询', '查询某设备/某时间段/某类型的告警详情'),
                        ('🖼️ 媒体预览', '查询结果自动展示对应的图片和视频'),
                        ('🔄 自动纠错', '如果 SQL 执行失败，我会自动修正重试'),
                    ]
                    with ui.column().classes('gap-1.5'):
                        for icon_label, desc in examples:
                            with ui.row().classes('items-start gap-2'):
                                ui.label(icon_label).classes('text-xs font-medium text-slate-700 flex-shrink-0 w-20')
                                ui.label(desc).classes('text-xs text-slate-500')

                    # 猜你想问
                    ui.separator().classes('my-1 opacity-30')
                    ui.label('🎯 猜你想问').classes('text-xs font-semibold text-slate-600')
                    guesses = [
                        "按街道统计最近30天各类告警数量",
                        "查询最近20条车辆闯入告警的详细信息",
                        "统计各设备触发告警次数最多的TOP10",
                        "查询置信度大于0.9的高置信告警",
                        "按告警类型统计本月告警分布",
                        "查询最近10条有视频的告警记录",
                    ]
                    with ui.row().classes('flex-wrap gap-2'):
                        for g in guesses:
                            ui.button(g, on_click=lambda g=g: do_ask(g)) \
                                .props('outline size=sm color=blue-6 rounded-lg no-caps')

        def _refresh_chat():
            """重新渲染整个聊天区"""
            chat_container.clear()
            with chat_container:
                if not chat_history:
                    _render_welcome()
                    return
                for msg in chat_history:
                    if msg['role'] == 'user':
                        _render_user_bubble(msg['content'])
                    elif msg['role'] == 'thinking':
                        _render_thinking_bubble(msg.get('lines'))
                    else:
                        _render_agent_bubble(msg['result'], msg.get('question', ''))
            # 滚动到底部
            chat_scroll.scroll_to(percent=1.0)

        async def do_ask(question: str = ''):
            q = question or question_input.value
            if not q or not q.strip():
                ui.notify('请输入问题', type='warning')
                return
            question_input.value = ''

            # 高级筛选：前置注入到问题中（Agent/NL2SQL 会看到筛选上下文）
            qa_f = collect_qa_filters()
            filter_ctx = _build_filter_context(qa_f)
            agent_question = filter_ctx + q if filter_ctx else q

            # 添加用户消息 + 思考占位（带 lines 列表）
            chat_history.append({'role': 'user', 'content': q})
            thinking_msg = {'role': 'thinking', 'content': '', 'lines': []}
            chat_history.append(thinking_msg)
            _refresh_chat()

            try:
                agent = get_agent()
                if not agent:
                    chat_history.pop()
                    chat_history.append({
                        'role': 'agent', 'question': q,
                        'result': {'status': 'error', 'error': 'Agent 未初始化'}
                    })
                    _refresh_chat()
                    return

                # 用 queue 捕获 agent 线程的 print 输出
                log_q: queue.Queue = queue.Queue()
                result_holder: List = []
                error_holder: List = []

                # 生成 trace_id
                from poc.qa.trace import get_trace_manager
                trace_mgr = get_trace_manager()
                trace_id = None
                if trace_mgr:
                    from poc.qa.trace import QueryTrace
                    trace = QueryTrace(question=agent_question, user_id="nicegui_user")
                    trace_id = trace.trace_id

                def _run_agent():
                    old_stdout = sys.stdout
                    sys.stdout = _StdoutCapture(old_stdout, log_q)
                    try:
                        r = agent.query(agent_question, user_id="nicegui_user", trace_id=trace_id)
                        result_holder.append(r)
                    except Exception as e:
                        error_holder.append(e)
                    finally:
                        sys.stdout = old_stdout
                    log_q.put(None)  # sentinel

                t = threading.Thread(target=_run_agent, daemon=True)
                t.start()

                # 轮询 queue，实时刷新思考气泡
                while True:
                    try:
                        line = log_q.get_nowait()
                        if line is None:
                            break
                        thinking_msg['lines'].append(line)
                        _refresh_chat()
                    except queue.Empty:
                        pass
                    if not t.is_alive() and log_q.empty():
                        break
                    await asyncio.sleep(0.15)

                # 排空剩余
                while not log_q.empty():
                    line = log_q.get_nowait()
                    if line is not None:
                        thinking_msg['lines'].append(line)

                t.join(timeout=2)

                if error_holder:
                    raise error_holder[0]

                result = result_holder[0]

                # 高级筛选后置注入（仅对 SQL 查询生效，作为前置 prompt 注入的补充保障）
                if qa_f and result.get("status") == "success" and result.get("sql") and result.get("intent") != "search":
                    try:
                        injected = result["sql"]
                        for p in (result.get("sql_params") or []):
                            injected = injected.replace("?", f"'{p}'" if isinstance(p, str) else str(p), 1)
                        injected = _inject_sql_filters(injected, qa_f)
                        engine = _get_engine()
                        new_data = engine.execute(injected)
                        sql_upper = injected.upper()
                        has_agg = any(fn in sql_upper for fn in ("COUNT(", "SUM(", "AVG("))
                        new_intent = "count" if has_agg and "GROUP BY" in sql_upper else result.get("intent", "list")
                        if new_intent == "count" and len(new_data) == 1 and len(new_data[0]) == 1:
                            result["answer"] = {"type": "count", "value": list(new_data[0].values())[0],
                                                "message": f"共 {list(new_data[0].values())[0]} 条"}
                        else:
                            result["answer"] = {"type": "list", "value": new_data,
                                                "message": f"返回 {len(new_data)} 条记录"}
                        result["sql"] = injected
                        result["sql_params"] = []
                        result["intent"] = new_intent
                    except Exception as fe:
                        print(f"Filter inject failed: {fe}")

                # 保存追踪
                try:
                    tm = get_trace_manager()
                    if tm:
                        t2 = QueryTrace(question=q)
                        t2.intent = result.get("intent")
                        t2.sql = result.get("sql")
                        t2.sql_params = result.get("sql_params")
                        t2.status = result.get("status", "error")
                        t2.error_message = result.get("error")
                        ans = result.get("answer")
                        if isinstance(ans, dict) and isinstance(ans.get("value"), list):
                            t2.result_count = len(ans["value"])
                        step = t2.add_step("agent_query")
                        step.finish("success" if result.get("status") == "success" else "error")
                        t2.finish(status=t2.status)
                        tm.save_trace(t2)
                except Exception:
                    pass

                # 保留思考日志到 result 中，完成后也能查看
                result['_thinking_lines'] = thinking_msg['lines']

                # 替换 thinking → agent 回复
                chat_history.pop()
                chat_history.append({
                    'role': 'agent', 'question': q, 'result': result
                })
                _refresh_chat()

            except Exception as e:
                chat_history.pop()
                chat_history.append({
                    'role': 'agent', 'question': q,
                    'result': {'status': 'error', 'error': str(e)}
                })
                _refresh_chat()
                traceback.print_exc()

        # ── 图片上传搜索 ──
        async def handle_image_upload(e: events.UploadEventArguments):
            """上传图片后执行向量检索"""
            try:
                name = e.name if hasattr(e, 'name') else e.file.name
                # NiceGUI 兼容：优先 e.content（同步），fallback await e.file.read()
                if hasattr(e, 'content') and e.content:
                    content = e.content.read() if hasattr(e.content, 'read') else e.content
                else:
                    content = await e.file.read()
                suffix = _Path(name).suffix.lower()

                if not content or len(content) < 100:
                    ui.notify('上传文件为空或过小', type='warning')
                    return

                # 保存临时文件
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix,
                                                   dir=str(resolve_path('poc/data')))
                tmp.write(content)
                tmp.close()
                tmp_path = tmp.name

                # 视频抽帧
                is_video = suffix in ('.mp4', '.avi', '.mov')
                if is_video:
                    frame_ok = False
                    try:
                        import cv2
                        cap = cv2.VideoCapture(tmp_path)
                        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        cap.set(cv2.CAP_PROP_POS_FRAMES, max(total // 2, 0))
                        ret, frame = cap.read()
                        cap.release()
                        if ret:
                            frame_tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg',
                                                                     dir=str(resolve_path('poc/data')))
                            # cv2.imwrite 不支持中文路径，改用 imencode + 手动写入
                            _ok, _buf = cv2.imencode('.jpg', frame)
                            if _ok:
                                frame_tmp.write(_buf.tobytes())
                            frame_tmp.close()
                            _Path(tmp_path).unlink(missing_ok=True)  # 删除原始视频临时文件
                            tmp_path = frame_tmp.name
                            frame_ok = True
                    except Exception as vex:
                        print(f"[handle_image_upload] video frame extraction failed: {vex}")
                    if not frame_ok:
                        ui.notify('视频抽帧失败，请上传图片文件', type='warning')
                        _Path(tmp_path).unlink(missing_ok=True)
                        return

                # 添加用户消息
                chat_history.append({'role': 'user', 'content': f'[上传图片搜索] {name}'})
                thinking_msg = {'role': 'thinking', 'content': '', 'lines': ['正在编码图片并检索...']}
                chat_history.append(thinking_msg)
                _refresh_chat()

                # 编码 + 检索
                import lancedb as _ldb
                lancedb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))
                db = _ldb.connect(str(lancedb_dir))
                table = db.open_table("embeddings")
                mgr = get_model_manager()

                # 确认文件存在且非空
                if not _Path(tmp_path).exists() or _Path(tmp_path).stat().st_size < 100:
                    raise FileNotFoundError(f"临时文件不存在或为空: {tmp_path}")

                print(f"[handle_image_upload] encoding image: {tmp_path}, size={_Path(tmp_path).stat().st_size}")
                query_vec = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: mgr.encode_image(tmp_path).astype("float32"))

                results_df = hybrid_search(table, query_vec, top_k=10)

                # 转为 list[dict]
                search_results = []
                for _, row in results_df.iterrows():
                    item = {}
                    for col in results_df.columns:
                        if col == "vector" or (col.startswith("_") and col != "_distance"):
                            continue
                        val = row[col]
                        if hasattr(val, 'item'):
                            val = val.item()
                        item[col] = val
                    search_results.append(item)

                result = {
                    'status': 'success',
                    'intent': 'search',
                    'sql': '',
                    'sql_params': [],
                    'answer': {
                        'type': 'search',
                        'value': search_results,
                        'message': f'为您找到 {len(search_results)} 张相似图片',
                    },
                    '_thinking_lines': thinking_msg['lines'],
                }

                chat_history.pop()
                chat_history.append({
                    'role': 'agent', 'question': f'[图片搜索] {name}', 'result': result
                })
                _refresh_chat()
                ui.notify(f'找到 {len(search_results)} 张相似图片', type='positive')

            except Exception as ex:
                chat_history.pop()
                chat_history.append({
                    'role': 'agent', 'question': f'[图片搜索] {name}',
                    'result': {'status': 'error', 'error': str(ex), 'intent': 'search'}
                })
                _refresh_chat()
                traceback.print_exc()

        # ── 底部输入区 ──
        with ui.row().classes('w-full gap-2 items-center mt-2'):
            question_input = ui.input(placeholder='输入问题，如：按街道统计最近30天各类告警数量 / 找红色挖掘机的图片') \
                .classes('flex-1').props('outlined dense rounded')
            question_input.on('keydown.enter', lambda: do_ask())
            ui.upload(on_upload=handle_image_upload, auto_upload=True, max_files=1) \
                .props('accept=".jpg,.jpeg,.png,.bmp,.mp4,.avi" flat dense icon=image color=blue-6') \
                .classes('w-10 h-10')
            ui.button(icon='send', on_click=lambda: do_ask()) \
                .props('unelevated color=blue-6 round').classes('ml-1')

        # 初始渲染空聊天区
        _refresh_chat()

