"""Page 5: 系统监控"""
from nicegui import ui
from poc.app.pages.shared import (
    create_layout, page_header, config, resolve_path,
    ensure_systems, db_stats, lance_count,
    get_trace_manager, get_tool_registry,
)


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
                        "SQL": str(r.get("sql", "") or "")[:100],
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

        # 外部服务健康检查
        ui.label('外部服务状态').classes('font-bold text-lg text-slate-800 mb-3 mt-8')
        try:
            from poc.infra.http_utils import check_all_services
            health = check_all_services(config)
            svc_names = {
                "qwen_embedding": "Qwen3-VL Embedding (8010)",
                "qwen_reranker": "Qwen3-VL Reranker (8011)",
                "vllm": "VLLM VL 检测 (50100)",
                "deepseek": "DeepSeek LLM",
            }
            health_rows = []
            for key, info in health.items():
                status = "可用" if info["available"] else "不可用"
                latency = f'{info["latency_ms"]:.0f}ms' if info["available"] else "-"
                error = info.get("error") or ""
                health_rows.append({
                    "服务": svc_names.get(key, key),
                    "状态": status,
                    "延迟": latency,
                    "错误": error,
                })
            if health_rows:
                ui.table(
                    columns=[{"name": c, "label": c, "field": c} for c in ["服务", "状态", "延迟", "错误"]],
                    rows=health_rows,
                ).classes('w-full mb-4')
        except Exception as e:
            ui.label(f'健康检查失败: {e}').classes('text-slate-400')

        # Ray 集群状态
        ui.label('Ray 集群状态').classes('font-bold text-lg text-slate-800 mb-3 mt-8')
        try:
            from poc.infra.ray_init import get_ray_status
            ray_status = get_ray_status()
            if ray_status.get("initialized"):
                with ui.grid(columns=4).classes('w-full gap-4 mb-4'):
                    for lbl, val in [("节点数", ray_status.get("num_nodes", 0)),
                                      ("CPU 核数", ray_status.get("total_cpus", 0)),
                                      ("GPU 数", ray_status.get("total_gpus", 0)),
                                      ("Actor 数", len(ray_status.get("actors", [])))]:
                        with ui.element('div').classes('kpi-card text-center'):
                            ui.label(str(val)).classes('text-xl font-bold text-slate-800')
                            ui.label(lbl).classes('text-sm text-slate-500')

                actors = ray_status.get("actors", [])
                if actors:
                    ui.label('活跃 Actor').classes('font-semibold text-slate-700 mb-2')
                    actor_rows = [{"Actor 名称": a, "状态": "运行中"} for a in actors]
                    ui.table(columns=[{"name": c, "label": c, "field": c} for c in ["Actor 名称", "状态"]],
                             rows=actor_rows).classes('w-full mb-4')

                nodes = ray_status.get("nodes", [])
                if nodes:
                    ui.label('集群节点').classes('font-semibold text-slate-700 mb-2')
                    node_rows = [{"节点ID": n["node_id"], "地址": n["address"],
                                  "CPU": n["cpu"], "GPU": n["gpu"]} for n in nodes]
                    ui.table(columns=[{"name": c, "label": c, "field": c} for c in ["节点ID", "地址", "CPU", "GPU"]],
                             rows=node_rows).classes('w-full')

                if ray_status.get("error"):
                    ui.label(f'查询异常: {ray_status["error"]}').classes('text-amber-600 text-sm')
            else:
                err = ray_status.get("error", "Ray 未启用或未初始化")
                ui.label(err).classes('text-slate-400')
        except ImportError:
            ui.label('Ray 模块未安装').classes('text-slate-400')
        except Exception as e:
            ui.label(f'Ray 状态查询失败: {e}').classes('text-slate-400')
