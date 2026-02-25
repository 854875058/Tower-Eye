"""Page 4: 自动标注 - 嵌入 Streamlit 版本"""
import urllib.request
import urllib.error
import socket
from nicegui import ui, app
from poc.app.pages.shared import create_layout, page_header

# Streamlit 页面端口
STREAMLIT_PORT = 8055


def get_server_ip() -> str:
    """获取服务器 IP 地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


SERVER_IP = get_server_ip()
STREAMLIT_URL = f'http://{SERVER_IP}:{STREAMLIT_PORT}'


def check_streamlit_status() -> bool:
    """检查 Streamlit 服务是否可用"""
    try:
        req = urllib.request.Request(f'http://localhost:{STREAMLIT_PORT}')
        urllib.request.urlopen(req, timeout=2)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, Exception):
        return False


def go_to_streamlit():
    """当前窗口跳转到 Streamlit 页面"""
    ui.run_javascript(f'window.location.href = "{STREAMLIT_URL}"')


def render():
    """主渲染函数 - 跳转方式"""
    with create_layout('/label'):
        page_header('自动标注', 'YOLOv26x + VL 语义双引擎自动检测与标注')

        # 检查 Streamlit 服务状态
        streamlit_available = check_streamlit_status()

        if not streamlit_available:
            # 服务未启动
            with ui.card().classes('w-full mb-4 p-6'):
                ui.icon('warning', size='xl').classes('text-orange-500')
                ui.label('Streamlit 自动标注服务未启动').classes('text-lg font-bold mt-2')
                ui.label('请确保已通过 app_ui.py 启动服务').classes('text-sm text-gray-600 mt-1')
                ui.separator()
                with ui.column().classes('gap-2 mt-4'):
                    ui.label('启动命令:').classes('text-sm font-bold')
                    ui.code('streamlit run poc/pipeline/labeling_interface.py --server.port 8055').classes('text-sm')
                with ui.row().classes('mt-4 gap-2'):
                    ui.button('刷新状态', on_click=lambda: ui.refresh()).props('flat')
            return

        # 服务已启动，显示跳转界面
        with ui.card().classes('w-full'):
            with ui.column().classes('items-center gap-6 py-12'):
                ui.icon('label', size='xl').classes('text-blue-600')
                ui.label('自动标注服务已就绪').classes('text-xl font-bold')
                ui.label('点击下方按钮进入自动标注界面').classes('text-gray-600')

                ui.separator().classes('w-full')

                with ui.row().classes('gap-4 mt-4'):
                    ui.button(
                        '🏷️ 进入自动标注',
                        on_click=go_to_streamlit,
                    ).props('color=primary size=large')

                ui.separator().classes('w-full mt-6')

                with ui.column().classes('text-sm text-gray-500 gap-2'):
                    ui.label('功能说明：')
                    ui.label('• 支持图片批量自动标注')
                    ui.label('• 支持视频逐帧标注与跟踪')
                    ui.label('• 支持手动画框修正')
                    ui.label('• 导出 YOLO 格式标签')


@ui.page('/label')
def label_page():
    render()
