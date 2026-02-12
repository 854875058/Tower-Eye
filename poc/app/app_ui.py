#!/usr/bin/env python3
"""
多模态数据底座 - NiceGUI 前端入口
页面实现已拆分到 poc/app/pages/ 下各模块
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import ui, app
from poc.app.pages.shared import ensure_systems

# 导入各页面模块（触发 @ui.page 注册）
import poc.app.pages.dashboard   # noqa: F401  /
import poc.app.pages.qa          # noqa: F401  /qa
import poc.app.pages.search      # noqa: F401  /search
import poc.app.pages.label       # noqa: F401  /label
import poc.app.pages.monitor     # noqa: F401  /monitor


if __name__ in {"__main__", "__mp_main__"}:
    @app.on_startup
    async def _startup_init():
        ensure_systems()

    ui.run(
        host="0.0.0.0",
        port=8080,
        title="多模态数据底座",
        favicon="🏗️",
        storage_secret="Tower-Eye",
        reload=False,
    )
