#!/usr/bin/env python3
"""
多模态数据底座 - NiceGUI 前端 (Luxury Edition)
灵感来源: 极智-automl-平台 (React + Tailwind)
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextlib import contextmanager
from nicegui import ui, app, events
import asyncio
import json
from typing import List, Dict, Optional

# 导入后端逻辑
try:
    from poc.pipeline.utils import load_yaml, connect_db
    from poc.search.query import hybrid_search, build_asset_id_filter
    from poc.search.model_manager import ModelManager
    config = load_yaml("poc/config/poc.yaml")
except ImportError:
    config = {}
    print("Warning: Could not load backend modules. Running in UI-only mode.")

# ============================================================================
# 辅助函数 (从 app_v2.py 移植)
# ============================================================================
def fetch_events_by_asset_ids(db_path, asset_ids: List[str]) -> Dict[str, dict]:
    """根据 asset_id 列表从 SQLite 批量获取完整事件信息"""
    if not asset_ids:
        return {}
    try:
        conn = connect_db(db_path)
        placeholders = ", ".join("?" for _ in asset_ids)
        sql = (
            "SELECT e.*, a.file_path, a.file_name "
            "FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id "
            f"WHERE a.asset_id IN ({placeholders})"
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

def _build_result_item_from_sqlite(rd: dict, score: float = 0.0) -> dict:
    """从 SQLite 行数据构建统一的结果 dict"""
    extra = rd.get("_extra", {})
    return {
        "asset_id": rd.get("asset_id", ""),
        "score": score,
        "file_path": rd.get("file_path", ""),
        "file_name": rd.get("file_name", ""),
        "captured_at": rd.get("alarm_time", ""),
        "lat": rd.get("lat") or 0.0,
        "lon": rd.get("lon") or 0.0,
        "event_type": rd.get("event_type", ""),
        "alarm_time": rd.get("alarm_time", ""),
        "alarm_level": rd.get("alarm_level") or extra.get("emergency_level", ""),
        "summary": rd.get("summary", ""),
        "description": rd.get("description", ""),
        "address": rd.get("address", ""),
        "device_name": rd.get("device_name", ""),
        "confidence_level": rd.get("confidence_level"),
        "province_name": extra.get("province_name", ""),
        "city_name": extra.get("city_name", ""),
        "county_name": extra.get("county_name", ""),
        "town_name": extra.get("town_name", ""),
        "device_code": extra.get("device_code", ""),
        "algorithm_name": extra.get("algorithm_name", ""),
        "order_status": extra.get("order_status", ""),
        "video_url": f"warning_file/{Path(extra.get('video_url', '').split(',')[0].strip()).name}" if extra.get("video_url") else "",
        "file_img_url_src": rd.get("file_path", ""),
        "file_img_url_icon": "",
    }

# Global Model Manager (Lazy load)
_model_manager = None

def get_model_manager():
    global _model_manager
    if _model_manager is None and config:
        print("Loading Model Manager...")
        _model_manager = ModelManager(config)
    return _model_manager

# ============================================================================
# Luxury Design Components
# ============================================================================

def luxury_card():
    # 圆角更大(rounded-3xl)，阴影更柔和(shadow-sm)，边框更淡(border-slate-200)
    return ui.card().classes('bg-white rounded-[24px] shadow-sm border border-slate-200 p-6 hover:shadow-md transition-all duration-300')

def page_header(title: str, subtitle: str):
    with ui.row().classes('w-full justify-between items-start mb-8'):
        with ui.column().classes('gap-1'):
            ui.label(title).classes('text-2xl font-bold text-slate-900 flex items-center gap-2')
            ui.label(subtitle).classes('text-slate-500 text-sm')
        
        # Admin Profile (Consistent with reference)
        with ui.row().classes('bg-white px-4 py-2 rounded-xl border border-slate-200 shadow-sm items-center gap-3'):
            with ui.element('div').classes('w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 font-bold text-xs'):
                ui.label('AD')
            with ui.column().classes('hidden sm:block gap-0'):
                ui.label('管理员').classes('text-xs font-bold text-slate-800')
                ui.label('admin@automl.com').classes('text-[10px] text-slate-400')

def sidebar_item(label: str, icon: str, target: str, current_path: str):
    is_active = current_path == target
    # Active: Blue bg, white text, blue shadow
    # Inactive: Text slate-600, hover slate-100
    base_classes = 'w-full flex items-center gap-3 p-3 rounded-xl transition-all font-medium cursor-pointer'
    active_classes = 'bg-blue-600 text-white shadow-lg shadow-blue-200'
    inactive_classes = 'text-slate-600 hover:bg-slate-100'
    
    classes = f"{base_classes} {active_classes if is_active else inactive_classes}"
    
    with ui.link(target=target).classes('no-underline w-full'):
         with ui.element('div').classes(classes):
            ui.icon(icon).classes('text-xl')
            ui.label(label).classes('text-sm')
            if is_active:
                ui.icon('chevron_right').classes('ml-auto text-sm opacity-80')

# ============================================================================
# Main Layout
# ============================================================================
@contextmanager
def create_layout(active_path: str):
    # Global Style Override for "Inter" font and slate-50 background
    ui.add_head_html('''
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
            body { 
                font-family: 'Inter', sans-serif; 
                background-color: #f8fafc; 
            }
            .nicegui-content {
                padding: 0 !important;
                margin: 0 !important;
                max-width: none !important;
            }
        </style>
    ''')
    
    with ui.row().classes('h-screen w-full gap-0 overflow-hidden'):
        # Floating Sidebar (Left)
        # Using a variable to control visibility directly
        sidebar = ui.column().classes(
            'h-full bg-white border-r border-slate-200 flex flex-col z-50 transition-all duration-300'
        ).style('width: 256px')
        
        with sidebar:
             
            # Brand
            with ui.row().classes('items-center gap-2 px-6 py-6 mb-2'):
                ui.icon('smart_toy').classes('text-3xl text-blue-600')
                ui.label('Multimodal AI').classes('text-xl font-bold text-slate-800')
            
            # Nav Menu
            with ui.column().classes('flex-1 w-full gap-2 px-3'):
                sidebar_item('架构概览', 'dashboard', '/', active_path)
                sidebar_item('多模态检索', 'search', '/search', active_path)
                sidebar_item('数据分析', 'analytics', '/analysis', active_path)
                sidebar_item('Agent 对话', 'chat', '/chat', active_path)
            
            # Bottom Logout
            ui.separator().classes('my-4 opacity-50')
            with ui.row().classes('w-full flex items-center gap-3 p-4 mx-3 mb-4 text-red-500 hover:bg-red-50 rounded-xl transition-all cursor-pointer'):
                ui.icon('logout').classes('text-xl')
                ui.label('退出登录').classes('text-sm font-medium')

        # Main Content (Right)
        with ui.column().classes('flex-1 h-full bg-slate-50 relative'):
            # Top Bar (Hamburger Menu)
            def toggle_sidebar():
                sidebar.set_visibility(not sidebar.visible)

            with ui.row().classes('w-full h-16 items-center px-4 bg-white/50 backdrop-blur-md border-b border-slate-100 z-40'):
                 ui.button(icon='menu', on_click=toggle_sidebar)\
                   .props('flat round color=slate-500')
                 ui.space()
                 ui.button(icon='notifications').props('flat round color=slate-400')
            
            # Scrollable Area
            with ui.column().classes('w-full flex-1 overflow-y-auto p-8'):
                with ui.column().classes('max-w-7xl mx-auto w-full'):
                    yield

# ============================================================================
# Pages
# ============================================================================

@ui.page('/')
def dashboard_page():
    with create_layout('/'):
        page_header("架构概览", "生产级 RAG + Agent + 多模态检索架构概览。")

        # KPI Grid
        with ui.grid(columns=4).classes('w-full gap-6 mb-8'):
            def kpi_card(title, value, sub, icon, color_cls):
                with luxury_card().classes('flex items-center justify-between'):
                    with ui.column().classes('gap-1'):
                        ui.label(title).classes('text-slate-500 text-sm font-medium')
                        ui.label(value).classes('text-2xl font-bold text-slate-800')
                        ui.label(sub).classes('text-xs text-slate-400')
                    # Circle Icon Bg
                    with ui.element('div').classes(f'w-12 h-12 rounded-full {color_cls} bg-opacity-10 flex items-center justify-center'):
                        ui.icon(icon).classes(f'{color_cls.replace("bg-", "text-")} text-xl')

            kpi_card("Agent 引擎", "LangGraph", "状态机编排", "psychology", "bg-blue-600")
            kpi_card("向量数据库", "LanceDB", "GPU 加速检索", "storage", "bg-purple-600")
            kpi_card("多模态模型", "Qwen3-VL", "Embedding + Rerank", "image", "bg-amber-500")
            kpi_card("目标检测", "YOLOv26x", "VL 语义双引擎", "videocam", "bg-emerald-500")

        # Architecture Diagram (Container)
        with luxury_card().classes('w-full mb-8'):
            with ui.row().classes('items-center gap-2 mb-6'):
                ui.icon('account_tree').classes('text-slate-400')
                ui.label('系统架构图').classes('font-bold text-lg text-slate-800')

            ui.mermaid("""
            graph TD
                User[用户交互层 User Interface] --> Agent
                subgraph "前端 Frontend"
                    UI[NiceGUI Modern UI]
                end

                subgraph "Agent 层 (LangGraph)"
                    Agent[Agent Orchestrator]
                    State[State Machine: Parse -> Execute -> Refine]
                    Agent --> State
                end

                subgraph "模型层 (Model Inference)"
                    Qwen[Qwen3-VL Embedding]
                    Rerank[Qwen3-VL Reranker]
                    YOLO[YOLOv26x + VLLM]
                end

                subgraph "数据层 (Storage)"
                    LDB[(LanceDB 向量库)]
                    SQL[(SQLite 结构化库)]
                end

                State --> LDB
                State --> SQL
                LDB <--> Qwen
            """).classes('w-full flex justify-center bg-slate-50 rounded-2xl p-6')

@ui.page('/search')
def search_page():
    with create_layout('/search'):
        page_header("多模态检索", "基于 Qwen3-VL 的图文视频混合检索。")

        # State (Simple Dict)
        state = {
            'query_text': "",
            'search_results': [],
            'is_searching': False
        }

        async def perform_search():
            if not state['query_text']:
                ui.notify("请输入关键词", type="warning")
                return
            state['is_searching'] = True
            ui.update()
            await asyncio.sleep(0.1)
            try:
                mgr = get_model_manager()
                if mgr:
                    results = hybrid_search(
                        query_text=state['query_text'],
                        model_manager=mgr,
                        lancedb_dir=Path(config.get("paths", {}).get("lancedb_dir", "poc/data/lancedb")),
                        top_k=9,
                        filters={},
                        vector_weight=0.7
                    )

                    # Fetch Details
                    asset_ids = [r["asset_id"] for r in results]
                    details = fetch_events_by_asset_ids(
                        Path(config.get("paths", {}).get("db_path", "poc/data/metadata.db")),
                        asset_ids
                    )
                    formatted = []
                    for r in results:
                        if r["asset_id"] in details:
                            formatted.append(_build_result_item_from_sqlite(details[r["asset_id"]], r["score"]))
                    state['search_results'] = formatted
                    ui.notify(f"找到 {len(formatted)} 条结果", type="positive")

                    render_grid.refresh()
                else:
                    ui.notify("后端未连接", type="negative")
            except Exception as e:
                ui.notify(f"搜索失败: {e}", type="negative")
                print(e)
            finally:
                state['is_searching'] = False

        # Search Bar Section
        with luxury_card().classes('w-full mb-8 flex flex-row gap-4 items-center'):
            ui.icon('search').classes('text-slate-400 text-xl')
            ui.input(placeholder='输入关键词搜索，例如：车辆闯入...').bind_value(state, 'query_text').classes('flex-1 text-lg border-none focus:ring-0').props('borderless').on('keydown.enter', perform_search)

            ui.separator().props('vertical').classes('h-8 mx-2')
            ui.button('搜索', on_click=perform_search).props('unelevated color=blue-600 text-color=white rounded').classes('px-8 font-bold shadow-md shadow-blue-200')

        # Results Grid
        with ui.grid(columns=3).classes('w-full gap-6'):
            @ui.refreshable
            def render_grid():
                if not state['search_results']:
                    return

                for item in state['search_results']:
                    with luxury_card().classes('p-0 overflow-hidden flex flex-col h-full group'):
                        # Image Area
                        with ui.element('div').classes('w-full h-48 bg-slate-100 relative overflow-hidden'):
                            img_src = item.get('file_img_url_src')
                            if img_src:
                                ui.image(img_src).classes('w-full h-full object-cover transform group-hover:scale-110 transition-transform duration-500')

                            if item.get('video_url'):
                                with ui.element('div').classes('absolute inset-0 flex items-center justify-center bg-black bg-opacity-20'):
                                    ui.icon('play_circle').classes('text-white text-5xl opacity-80 shadow-lg')

                        # Content Area
                        with ui.column().classes('p-5 gap-2 flex-1'):
                            with ui.row().classes('w-full justify-between items-start'):
                                ui.label(item.get('event_type')).classes('font-bold text-slate-800 line-clamp-1')
                                ui.badge(f"{item.get('score', 0):.2f}").props('color=blue-100 text-color=blue-700 rounded-md')

                            ui.label(item.get('description') or '暂无描述').classes('text-sm text-slate-500 line-clamp-2')

                            ui.space()
                            with ui.row().classes('gap-2 mt-2'):
                                ui.chip(item.get('city_name'), icon='place').props('size=sm color=slate-100 text-color=slate-600')
                                ui.label(str(item.get('captured_at'))[:10]).classes('text-xs text-slate-400 ml-auto mt-1')

            render_grid()

@ui.page('/analysis')
def analysis_page():
    with create_layout('/analysis'):
        page_header("数据分析", "深入探索数据分布与特征关联。")
        with luxury_card().classes('h-96 flex items-center justify-center'):
            ui.label('ECharts 图表区域 (Placeholder)').classes('text-slate-400 font-bold')

@ui.page('/chat')
def chat_page():
    with create_layout('/chat'):
        page_header("Agent 对话", "与 AI 助手进行自然语言交互，支持 SQL 生成与数据查询。")

        # Message History State (Simple Dict)
        chat_state = {
            'messages': [
                {"text": "你好！我是多模态智能助手。我可以帮你查询告警事件、分析趋势或检索视频。", "sent": False, "avatar": "https://cdn.quasar.dev/img/avatar2.jpg"},
            ],
            'input_text': "",
            'is_typing': False
        }

        async def send_message():
            if not chat_state['input_text']: return

            # User Message
            user_msg = chat_state['input_text']
            chat_state['messages'].append({"text": user_msg, "sent": True, "avatar": "https://cdn.quasar.dev/img/boy-avatar.png"})
            chat_state['input_text'] = ""
            chat_state['is_typing'] = True

            render_messages.refresh()

            await asyncio.sleep(1.5)

            response_text = "收到您的请求。正在查询相关数据..."
            if "告警" in user_msg:
                response_text = "根据查询，昨天共有 **23 起** 告警事件，其中 **3 起** 为紧急告警（等级 1），主要集中在 **监测点 A**。"
            elif "视频" in user_msg:
                response_text = "已为您检索到相关视频片段。请查看下方的多模态搜索结果。"

            chat_state['messages'].append({"text": response_text, "sent": False, "avatar": "https://cdn.quasar.dev/img/avatar2.jpg"})
            chat_state['is_typing'] = False
            render_messages.refresh()

        with luxury_card().classes('h-[calc(100vh-240px)] flex flex-col p-0 overflow-hidden'):
            # Chat History Scroll Area
            with ui.scroll_area().classes('flex-1 bg-slate-50 p-6'):
                @ui.refreshable
                def render_messages():
                    for msg in chat_state['messages']:
                        with ui.row().classes('w-full ' + ('justify-end' if msg['sent'] else 'justify-start') + ' mb-4'):
                            if not msg['sent']:
                                ui.avatar(msg['avatar']).classes('mr-2 shadow-sm')

                            bubble_cls = 'px-6 py-4 max-w-[70%] shadow-md '
                            if msg['sent']:
                                bubble_cls += 'bg-blue-600 text-white rounded-[24px] rounded-tr-none'
                            else:
                                bubble_cls += 'bg-white text-slate-700 rounded-[24px] rounded-tl-none border border-slate-100'

                            with ui.element('div').classes(bubble_cls):
                                ui.markdown(msg['text']).classes('text-sm leading-relaxed')

                            if msg['sent']:
                                ui.avatar(msg['avatar']).classes('ml-2 shadow-sm')

                    # Typing Indicator
                    if chat_state['is_typing']:
                        with ui.row().classes('w-full justify-start mb-4'):
                            ui.avatar('https://cdn.quasar.dev/img/avatar2.jpg').classes('mr-2 opacity-50')
                            with ui.element('div').classes('bg-slate-100 px-4 py-2 rounded-full'):
                                ui.spinner('dots', size='sm', color='slate-400')

                render_messages()

            # Input Area
            with ui.row().classes('p-4 border-t border-slate-100 gap-4 bg-white items-center'):
                ui.button(icon='add_circle').props('round flat color=slate-400')
                ui.input(placeholder='输入消息...').bind_value(chat_state, 'input_text').classes('flex-1 text-lg').props('outlined rounded-lg bg-slate-50 border-none').on('keydown.enter', send_message)
                ui.button(icon='send', on_click=send_message).props('round color=blue-600 unelevated shadow-md')

# ============================================================================
# 启动
# ============================================================================
if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="0.0.0.0", 
        port=8080, 
        title="多模态数据底座", 
        favicon="🏗️", 
        storage_secret="secret",
        reload=False
    )
