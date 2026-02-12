"""Page 3: 多模态检索"""
import json
import asyncio
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List

from nicegui import ui, events
from poc.app.pages.shared import (
    create_layout, page_header, config, resolve_path, connect_db,
    get_model_manager, get_dropdown_options, get_area_hierarchy,
    geocode_address, build_sqlite_filter, build_asset_id_filter,
    fetch_events_by_asset_ids, build_result_item, hybrid_search,
)


@ui.page('/search')
def search_page():
    with create_layout('/search'):
        page_header('多模态检索 · 图文视频互搜',
                     '基于 Qwen3-VL + LanceDB 的向量检索，支持图片/文本/视频统一入口互搜')

        _db_path = resolve_path(config.get("paths", {}).get("db_path", "poc/data/metadata.db"))
        lancedb_dir = resolve_path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb"))

        # 检查 LanceDB
        _lancedb_ready = False
        _lance_err = ""
        try:
            import lancedb as _ldb
            _lance_db = _ldb.connect(str(lancedb_dir))
            if hasattr(_lance_db, 'table_names'):
                _lance_tables = _lance_db.table_names()
            elif hasattr(_lance_db, 'list_tables'):
                _lance_tables = _lance_db.list_tables()
            else:
                _lance_tables = []
            # table_names() 返回 List[str]，list_tables() 可能返回对象列表
            _table_names = [str(t) for t in _lance_tables]
            _lancedb_ready = "embeddings" in _table_names
            if not _lancedb_ready:
                _lance_err = f"表列表: {_table_names}，不含 'embeddings'"
        except Exception as e:
            _lancedb_ready = False
            _lance_err = str(e)

        if not _lancedb_ready:
            ui.label('向量数据库未初始化，请在服务器上运行 bash 重新入库.sh').classes('text-red-600 font-semibold')
            if _lance_err:
                ui.label(f'诊断信息: {_lance_err}').classes('text-slate-400 text-xs mt-1')
            return

        state: Dict[str, Any] = {
            'results': [], 'query_text': '', 'top_k': 10,
            'vector_weight': 0.7, 'enable_hybrid': True, 'show_related': True,
            'uploaded_path': None, 'uploaded_is_video': False,
        }
        f_state: Dict[str, Any] = {
            'event_type': '', 'alarm_level': '', 'order_status': '',
            'importance': '', 'warning_source': '', 'alarm_body': '',
            'city': '', 'county': '', 'town': '',
            'tenant': '', 'device': '', 'device_code': '',
            'channel': '', 'algorithm': '', 'algorithm_code': '',
            'confidence_min': 0.0, 'confidence_max': 1.0,
            'enable_time': False,
            'start_date_val': '', 'start_time_val': '00:00',
            'end_date_val': '', 'end_time_val': '23:59',
            'enable_geo': False, 'lat': '', 'lon': '', 'radius_km': 5.0,
        }
        # 用列表包装上传路径，避免闭包引用问题
        _upload_ref: List[str] = []

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
                    print(f"[handle_upload] name={name}, suffix={suffix}, content_len={len(content)}")
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=str(resolve_path('poc/data')))
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
                                frame_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg", dir=str(resolve_path('poc/data')))
                                cv2.imwrite(frame_tmp.name, frame); frame_tmp.close()
                                state['uploaded_path'] = frame_tmp.name
                                _upload_ref.clear(); _upload_ref.append(frame_tmp.name)
                                print(f"[handle_upload] 视频关键帧已保存: {frame_tmp.name}")
                                import base64
                                _, buf = cv2.imencode('.jpg', cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                                with upload_preview:
                                    ui.image(f'data:image/jpeg;base64,{base64.b64encode(buf).decode()}') \
                                        .classes('w-full max-h-48 object-contain rounded-lg')
                                    ui.label(f'视频关键帧（第 {total//2}/{total} 帧）').classes('text-xs text-slate-400')
                            else:
                                with upload_preview:
                                    ui.label('视频抽帧失败：无法读取帧').classes('text-red-500 text-sm')
                        except Exception as ex:
                            with upload_preview:
                                ui.label(f'视频抽帧失败: {ex}').classes('text-red-500 text-sm')
                            traceback.print_exc()
                        finally:
                            Path(tmp.name).unlink(missing_ok=True)
                    else:
                        state['uploaded_is_video'] = False
                        state['uploaded_path'] = tmp.name
                        _upload_ref.clear(); _upload_ref.append(tmp.name)
                        print(f"[handle_upload] 图片已保存: {tmp.name}, size={Path(tmp.name).stat().st_size}")
                        import base64
                        with upload_preview:
                            ui.image(f'data:image/{suffix[1:]};base64,{base64.b64encode(content).decode()}') \
                                .classes('w-full max-h-48 object-contain rounded-lg')
                            ui.label('上传的图片').classes('text-xs text-slate-400')
                    # 上传完成后自动触发检索（强制文件模式）
                    if state.get('uploaded_path'):
                        await do_search(force_file=True)

                with ui.row().classes('w-full gap-2 items-end'):
                    ui.upload(label='上传图片或视频', auto_upload=True, on_upload=handle_upload,
                              max_file_size=50_000_000) \
                        .props('accept=".jpg,.jpeg,.png,.bmp,.mp4"').classes('flex-1')

                    def clear_upload():
                        old = state.get('uploaded_path') or (_upload_ref[0] if _upload_ref else None)
                        if old and Path(old).exists():
                            Path(old).unlink(missing_ok=True)
                        state['uploaded_path'] = None
                        state['uploaded_is_video'] = False
                        _upload_ref.clear()
                        upload_preview.clear()
                        ui.notify('已清除上传', type='info')

                    ui.button(icon='clear', on_click=clear_upload) \
                        .props('flat round color=grey-6').tooltip('清除上传')

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
            with ui.grid(columns=3).classes('w-full gap-3 p-4'):
                _wt = {'': '全部'}; _wt.update({v: v for v in dd_opts.get("warning_type_name", [])})
                ui.select(_wt, label='告警类型').bind_value(f_state, 'event_type').props('outlined dense')
                ui.select({'': '全部', '1': '等级1(高)', '2': '等级2(中)', '3': '等级3(低)'}, label='紧急等级') \
                    .bind_value(f_state, 'alarm_level').props('outlined dense')
                ui.select({'': '全部', '1': '待处理', '2': '处理中', '4': '已完成', '6': '已关闭'}, label='工单状态') \
                    .bind_value(f_state, 'order_status').props('outlined dense')
            with ui.grid(columns=3).classes('w-full gap-3 px-4'):
                _imp = {'': '全部'}; _imp.update({v: f'等级 {v}' for v in dd_opts.get("importance_level", [])})
                ui.select(_imp, label='重要等级').bind_value(f_state, 'importance').props('outlined dense')
                _ws = {'': '全部'}; _ws.update({v: v for v in dd_opts.get("warning_source_name", [])})
                ui.select(_ws, label='告警来源').bind_value(f_state, 'warning_source').props('outlined dense')
                _ab = {'': '全部'}; _ab.update({v: v for v in dd_opts.get("alarm_body", [])})
                ui.select(_ab, label='告警主体').bind_value(f_state, 'alarm_body').props('outlined dense')
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
            with ui.grid(columns=3).classes('w-full gap-3 px-4'):
                _tn = {'': '全部'}; _tn.update({v: v for v in dd_opts.get("tenant_name", [])})
                ui.select(_tn, label='租户').bind_value(f_state, 'tenant').props('outlined dense')
                _dn = {'': '全部'}; _dn.update({v: v for v in dd_opts.get("device_name", [])})
                ui.select(_dn, label='设备名称').bind_value(f_state, 'device').props('outlined dense')
                _dc = {'': '全部'}; _dc.update({v: v for v in dd_opts.get("device_code", [])})
                ui.select(_dc, label='设备编码').bind_value(f_state, 'device_code').props('outlined dense')
            with ui.grid(columns=3).classes('w-full gap-3 px-4'):
                _cn = {'': '全部'}; _cn.update({v: v for v in dd_opts.get("channel_name", [])})
                ui.select(_cn, label='通道名称').bind_value(f_state, 'channel').props('outlined dense')
                _an = {'': '全部'}; _an.update({v: v for v in dd_opts.get("algorithm_name", [])})
                ui.select(_an, label='算法名称').bind_value(f_state, 'algorithm').props('outlined dense')
                _ac = {'': '全部'}; _ac.update({v: v for v in dd_opts.get("algorithm_code", [])})
                ui.select(_ac, label='算法编码').bind_value(f_state, 'algorithm_code').props('outlined dense')

            with ui.row().classes('w-full gap-4 px-4'):
                ui.label('置信度范围').classes('text-sm text-slate-500 self-center')
                ui.number(min=0, max=1, step=0.05, value=0).bind_value(f_state, 'confidence_min').props('outlined dense').classes('w-24')
                ui.label('~').classes('self-center')
                ui.number(min=0, max=1, step=0.05, value=1).bind_value(f_state, 'confidence_max').props('outlined dense').classes('w-24')
            with ui.column().classes('w-full px-4 gap-2'):
                ui.switch('启用时间过滤').bind_value(f_state, 'enable_time')
                with ui.row().classes('gap-4 items-center'):
                    # 开始日期
                    with ui.input('开始日期').bind_value(f_state, 'start_date_val').props('outlined dense').classes('w-40') as sd_input:
                        with sd_input.add_slot('append'):
                            ui.icon('event').classes('cursor-pointer')
                        with ui.menu() as sd_menu:
                            ui.date().bind_value(f_state, 'start_date_val').on('update:model-value', sd_menu.close)
                    # 开始时间
                    with ui.input('开始时间').bind_value(f_state, 'start_time_val').props('outlined dense').classes('w-32') as st_input:
                        with st_input.add_slot('append'):
                            ui.icon('access_time').classes('cursor-pointer')
                        with ui.menu() as st_menu:
                            ui.time().bind_value(f_state, 'start_time_val').on('update:model-value', st_menu.close)
                    ui.label('~').classes('text-slate-400 self-center')
                    # 结束日期
                    with ui.input('结束日期').bind_value(f_state, 'end_date_val').props('outlined dense').classes('w-40') as ed_input:
                        with ed_input.add_slot('append'):
                            ui.icon('event').classes('cursor-pointer')
                        with ui.menu() as ed_menu:
                            ui.date().bind_value(f_state, 'end_date_val').on('update:model-value', ed_menu.close)
                    # 结束时间
                    with ui.input('结束时间').bind_value(f_state, 'end_time_val').props('outlined dense').classes('w-32') as et_input:
                        with et_input.add_slot('append'):
                            ui.icon('access_time').classes('cursor-pointer')
                        with ui.menu() as et_menu:
                            ui.time().bind_value(f_state, 'end_time_val').on('update:model-value', et_menu.close)
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
                if f_state.get('start_date_val'):
                    t = f_state.get('start_time_val', '00:00') or '00:00'
                    f['start_time'] = f"{f_state['start_date_val']} {t}:00"
                if f_state.get('end_date_val'):
                    t = f_state.get('end_time_val', '23:59') or '23:59'
                    f['end_time'] = f"{f_state['end_date_val']} {t}:59"
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

        async def do_search(force_file=False):
            q = state.get('query_text', '')
            # 优先从 state 获取，兼容 _upload_ref
            uploaded = state.get('uploaded_path')
            if not uploaded and _upload_ref:
                uploaded = _upload_ref[0]
            filters = collect_search_filters()
            has_query = bool(q and q.strip())
            has_file = bool(uploaded and Path(uploaded).exists())
            has_filter = any(v for v in filters.values() if v)
            # 如果强制文件模式，或者有文件且没文字，则走文件检索
            use_file_search = has_file and (force_file or not has_query)
            print(f"[do_search] q={has_query}, file={has_file}(path={uploaded!r}), filter={has_filter}, force_file={force_file}, use_file_search={use_file_search}")
            if not (has_query or has_file or has_filter):
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
                fetch_k = top_k * 3 if reranker_enabled and has_query else top_k

                query_vec = None
                if use_file_search:
                    # 图片/视频帧检索（优先）
                    print(f"[do_search] 图片检索: uploaded_path={uploaded}, exists={Path(uploaded).exists()}")
                    if not Path(uploaded).exists():
                        ui.notify(f'上传文件已失效，请重新上传', type='warning')
                        return
                    query_vec = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: mgr.encode_image(uploaded).astype("float32"))
                    print(f"[do_search] 图片编码完成, vec shape={query_vec.shape}")
                elif has_query:
                    # 文本检索
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

                if query_vec is None:
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

        # 结果容器 — 放在搜索按钮之后，确保结果出现在筛选条件下方
        results_container = ui.column().classes('w-full')

        render_results()
