"""Page 2: 智能问答"""
import re
import json
import asyncio
import traceback
from typing import Any, Dict, List

from nicegui import ui
from poc.app.pages.shared import (
    create_layout, page_header, config, resolve_path, connect_db,
    ensure_systems, get_agent, get_trace_manager, QueryTrace,
    get_area_hierarchy, _inject_sql_filters,
)


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
                        from pathlib import Path as _Path
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
                                                ui.image(f'/warning_img/{_Path(str(iv)).name}').classes('w-full h-32 object-cover rounded')
                                                shown = True
                                        if video_col_idx is not None:
                                            vv = row.get(cols_raw[video_col_idx], "")
                                            if vv:
                                                vn = _Path(str(vv).split(",")[0].strip()).name
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
