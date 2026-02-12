"""Page 2: 智能问答 — Agent 聊天助手"""
import re
import json
import asyncio
import traceback
from pathlib import Path as _Path
from typing import Any, Dict, List

from nicegui import ui
from poc.app.pages.shared import (
    create_layout, page_header, config, resolve_path, connect_db,
    ensure_systems, get_agent, get_trace_manager, QueryTrace,
    get_area_hierarchy, _inject_sql_filters,
)


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
            with ui.row().classes('w-full justify-start items-start gap-2'):
                ui.icon('smart_toy').classes('text-blue-500 text-2xl mt-1 flex-shrink-0')
                with ui.column().classes(
                    'bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm gap-2 flex-1 min-w-0'
                ):
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

                    # 思考过程时间线
                    exec_hist = result.get("execution_history") or []
                    if exec_hist or result.get("intent"):
                        with ui.expansion('思考过程', icon='psychology').classes('w-full').props('dense default-opened'):
                            with ui.element('div').classes('pl-3 border-l-2 border-blue-200 space-y-1'):
                                # Step 1: 意图识别
                                intent = result.get("intent", "未知")
                                with ui.row().classes('items-center gap-1'):
                                    ui.icon('search').classes('text-blue-400 text-sm')
                                    ui.label(f'意图识别 → {intent}').classes('text-xs text-slate-600')
                                # Step 2+: 执行历史
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
                                            # 可展开的完整 SQL
                                            sql_short = str(rec.get("sql", ""))
                                            if sql_short:
                                                with ui.expansion(sql_short[:50] + ('...' if len(sql_short) > 50 else '')).classes('w-full').props('dense'):
                                                    ui.code(sql_short, language='sql').classes('w-full text-xs')

                    # SQL 折叠（最终 SQL，可编辑）
                    sql_text = _expand_sql_params(result.get("sql", ""), result.get("sql_params"))
                    if sql_text:
                        with ui.expansion('SQL', icon='code').classes('w-full').props('dense'):
                            ui.code(sql_text, language='sql').classes('w-full text-xs')
                            # SQL 编辑 + 重新执行
                            sql_editor = ui.textarea(value=sql_text).classes('w-full font-mono text-xs mt-1').props('outlined dense rows=3')

                            async def rerun_sql(editor=sql_editor, res=result):
                                try:
                                    conn = connect_db(_db_path)
                                    rows = conn.execute(editor.value).fetchall()
                                    conn.close()
                                    new_data = [dict(r) for r in rows]
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
                                    ui.notify('SQL 重新执行成功', type='positive')
                                except Exception as e:
                                    ui.notify(f'SQL 执行失败: {e}', type='negative')

                            ui.button('重新执行', icon='refresh', on_click=rerun_sql) \
                                .props('outline color=blue-6 rounded no-caps size=xs').classes('mt-1')

                    # 查询结果
                    answer = result.get("answer")
                    if answer:
                        answer_data = answer.get("value")

                        # ── list 类型：表格 + 媒体 ──
                        if isinstance(answer_data, list) and len(answer_data) > 0 and isinstance(answer_data[0], dict):
                            ui.label(f'共 {len(answer_data)} 条记录').classes('text-sm text-blue-600')
                            cols_raw = list(answer_data[0].keys())
                            tbl_cols = [{"name": c, "label": c.replace('_', ' ').title(), "field": c, "sortable": True} for c in cols_raw]
                            ui.table(columns=tbl_cols, rows=answer_data[:50],
                                     pagination={"rowsPerPage": 5}).classes('w-full text-xs').props('dense wrap-cells')

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

                            # 详情展开：每条记录可展开查看完整 JSON
                            with ui.expansion('查看详情', icon='info').classes('w-full').props('dense'):
                                for ri, row in enumerate(answer_data[:20]):
                                    with ui.expansion(f'第 {ri+1} 条', icon='description').classes('w-full').props('dense'):
                                        # 关键字段
                                        for lbl, key in [('事件类型', 'event_type'), ('告警等级', 'alarm_level'),
                                                         ('时间', 'alarm_time'), ('地址', 'address'),
                                                         ('设备', 'device_name'), ('算法', 'algorithm_name'),
                                                         ('工单状态', 'order_status'), ('置信度', 'confidence_level')]:
                                            v = row.get(key)
                                            if v:
                                                val_str = f'{v:.2f}' if isinstance(v, float) else str(v)
                                                with ui.row().classes('gap-2'):
                                                    ui.label(f'{lbl}:').classes('text-xs text-slate-400 w-16')
                                                    ui.label(val_str).classes('text-xs text-slate-700')
                                        # 图片预览
                                        for ic in img_cols:
                                            iv = row.get(cols_raw[ic], "")
                                            if iv:
                                                ui.image(f'/warning_img/{_Path(str(iv)).name}') \
                                                    .classes('w-full max-w-md rounded mt-1')
                                                break
                                        # 视频预览
                                        if video_col is not None:
                                            vv = row.get(cols_raw[video_col], "")
                                            if vv:
                                                vn = _Path(str(vv).split(",")[0].strip()).name
                                                ui.video(f'/warning_file/{vn}').classes('w-full max-w-md rounded mt-1')

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

        def _render_thinking_bubble():
            """渲染 Agent 思考中的占位气泡"""
            with ui.row().classes('w-full justify-start'):
                ui.icon('smart_toy').classes('text-blue-500 text-2xl mt-1')
                with ui.element('div').classes(
                    'bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm'
                ):
                    ui.spinner('dots', size='sm', color='blue')
                    ui.label('Agent 正在思考...').classes('text-sm text-slate-400 ml-2')

        def _refresh_chat():
            """重新渲染整个聊天区"""
            chat_container.clear()
            with chat_container:
                if not chat_history:
                    with ui.column().classes('w-full items-center py-12'):
                        ui.icon('chat').classes('text-6xl text-slate-200')
                        ui.label('输入问题开始对话').classes('text-slate-400 mt-2')
                    return
                for msg in chat_history:
                    if msg['role'] == 'user':
                        _render_user_bubble(msg['content'])
                    elif msg['role'] == 'thinking':
                        _render_thinking_bubble()
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

            # 添加用户消息 + 思考占位
            chat_history.append({'role': 'user', 'content': q})
            chat_history.append({'role': 'thinking', 'content': ''})
            _refresh_chat()

            try:
                agent = get_agent()
                if not agent:
                    chat_history.pop()  # 移除 thinking
                    chat_history.append({
                        'role': 'agent', 'question': q,
                        'result': {'status': 'error', 'error': 'Agent 未初始化'}
                    })
                    _refresh_chat()
                    return

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
                        rows = conn.execute(injected).fetchall()
                        conn.close()
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
                        result["sql"] = injected
                        result["sql_params"] = []
                        result["intent"] = new_intent
                    except Exception as fe:
                        print(f"Filter inject failed: {fe}")

                # 保存追踪
                try:
                    tm = get_trace_manager()
                    if tm:
                        t = QueryTrace(question=q)
                        t.intent = result.get("intent")
                        t.sql = result.get("sql")
                        t.sql_params = result.get("sql_params")
                        t.status = result.get("status", "error")
                        t.error_message = result.get("error")
                        ans = result.get("answer")
                        if isinstance(ans, dict) and isinstance(ans.get("value"), list):
                            t.result_count = len(ans["value"])
                        step = t.add_step("agent_query")
                        step.finish("success" if result.get("status") == "success" else "error")
                        t.finish(status=t.status)
                        tm.save_trace(t)
                except Exception:
                    pass

                # 替换 thinking → agent 回复
                chat_history.pop()  # 移除 thinking
                chat_history.append({
                    'role': 'agent', 'question': q, 'result': result
                })
                _refresh_chat()

            except Exception as e:
                chat_history.pop()  # 移除 thinking
                chat_history.append({
                    'role': 'agent', 'question': q,
                    'result': {'status': 'error', 'error': str(e)}
                })
                _refresh_chat()
                traceback.print_exc()

        # ── 底部输入区 ──
        with ui.row().classes('w-full gap-2 items-center mt-2'):
            question_input = ui.input(placeholder='输入问题，如：按街道统计最近30天各类告警数量') \
                .classes('flex-1').props('outlined dense rounded')
            question_input.on('keydown.enter', lambda: do_ask())
            ui.button(icon='send', on_click=lambda: do_ask()) \
                .props('unelevated color=blue-6 round').classes('ml-1')

        # 初始渲染空聊天区
        _refresh_chat()

