#!/usr/bin/env python3
"""
多模态数据底座 - NiceGUI 前端入口
页面实现已拆分到 poc/app/pages/ 下各模块
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import ui, app
from poc.app.pages.shared import ensure_systems

# 导入各页面模块（触发 @ui.page 注册）
import poc.app.pages.dashboard   # noqa: F401  /
import poc.app.pages.workspace   # noqa: F401  /workspace
import poc.app.pages.qa          # noqa: F401  /qa
import poc.app.pages.search      # noqa: F401  /search
import poc.app.pages.label       # noqa: F401  /label
import poc.app.pages.monitor     # noqa: F401  /monitor


if __name__ in {"__main__", "__mp_main__"}:
    @app.on_startup
    async def _startup_init():
        print("[app_ui] 应用启动，初始化系统组件...")
        ensure_systems()
        print("[app_ui] 系统组件初始化完成")

    ui.run(
        host=os.environ.get("APP_HOST", "0.0.0.0"),
        port=int(os.environ.get("APP_PORT", "8080")),
        title="铁塔之眼-多模态数据底座",
        favicon="🏗️",
        storage_secret="Tower-Eye",
        reload=False,
        reconnect_timeout=30.0,  # WebSocket 重连超时（默认3s太短，服务器负载高时容易断）
    )
