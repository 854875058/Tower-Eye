"""Unified workspace entry for QA-first and multimodal search workflows."""

from typing import Dict

from nicegui import ui

from poc.app.pages.qa import render_qa_view
from poc.app.pages.search import render_search_view
from poc.app.pages.shared import create_layout, page_header


DEFAULT_MODE = "qa"

VIEW_META: Dict[str, Dict[str, str]] = {
    "qa": {
        "label": "\u667a\u80fd\u95ee\u7b54",
        "icon": "forum",
        "title": "\u5f53\u524d\u6a21\u5f0f\uff1a\u667a\u80fd\u95ee\u7b54",
        "description": (
            "\u9002\u5408\u6309\u65f6\u95f4\u3001\u533a\u57df\u3001\u8bbe\u5907\u3001\u544a\u8b66\u7c7b\u578b\u505a"
            "\u7edf\u8ba1\u5206\u6790\u548c\u660e\u7ec6\u67e5\u8be2\uff0c\u7ed3\u679c\u53ef\u8054\u52a8\u67e5\u770b\u56fe\u7247\u3001\u89c6\u9891\u4e0e\u5173\u8054\u8bb0\u5f55\u3002"
        ),
    },
    "search": {
        "label": "\u591a\u6a21\u6001\u68c0\u7d22",
        "icon": "image_search",
        "title": "\u5f53\u524d\u6a21\u5f0f\uff1a\u591a\u6a21\u6001\u68c0\u7d22",
        "description": (
            "\u9002\u5408\u6839\u636e\u6587\u672c\u3001\u56fe\u7247\u6216\u89c6\u9891\u5e27\u67e5\u627e\u76f8\u4f3c\u544a\u8b66\uff0c"
            "\u5e76\u7ed3\u5408\u65f6\u95f4\u3001\u533a\u57df\u3001\u8bbe\u5907\u7b49\u6761\u4ef6\u5feb\u901f\u7f29\u5c0f\u7ed3\u679c\u8303\u56f4\u3002"
        ),
    },
}


def _mode_button(mode: str, current: str) -> None:
    meta = VIEW_META[mode]
    active = mode == current
    button = ui.button(meta["label"], icon=meta["icon"])
    if active:
        button.props("unelevated color=blue-6 no-caps rounded")
        button.classes("shadow-md shadow-blue-200")
    else:
        button.props("outline color=grey-7 no-caps rounded")
    button.on("click", lambda m=mode: ui.navigate.to(f"/workspace?mode={m}"))


def _render_toolbar(current: str) -> None:
    current_meta = VIEW_META[current]

    with ui.card().classes("w-full rounded-2xl border border-slate-200 shadow-sm"):
        with ui.column().classes("w-full gap-4 p-5"):
            with ui.row().classes("w-full items-start justify-between gap-4 flex-wrap"):
                with ui.column().classes("gap-1"):
                    ui.label("\u6838\u5fc3\u80fd\u529b").classes(
                        "text-lg font-semibold text-slate-800"
                    )
                    ui.label(
                        "\u9762\u5411\u544a\u8b66\u6570\u636e\u5206\u6790\u4e0e\u5a92\u4f53\u56de\u6eaf\uff0c"
                        "\u652f\u6301\u95ee\u6570\u3001\u67e5\u660e\u7ec6\u3001\u627e\u76f8\u4f3c\u548c\u770b\u5a92\u4f53\u3002"
                    ).classes("text-sm text-slate-500")
                with ui.row().classes("gap-2 flex-wrap"):
                    for candidate in ("qa", "search"):
                        _mode_button(candidate, current)

            with ui.row().classes("w-full gap-3 flex-wrap"):
                for text in (
                    "\u544a\u8b66\u7edf\u8ba1\u5206\u6790",
                    "\u544a\u8b66\u660e\u7ec6\u67e5\u8be2",
                    "\u56fe\u6587\u89c6\u9891\u68c0\u7d22",
                    "\u5173\u8054\u5a92\u4f53\u67e5\u770b",
                ):
                    ui.label(text).classes(
                        "px-3 py-1 rounded-full bg-slate-100 text-slate-600 text-xs"
                    )

            with ui.element("div").classes(
                "w-full rounded-xl bg-blue-50 border border-blue-100 px-4 py-3"
            ):
                ui.label(current_meta["title"]).classes("text-sm font-semibold text-blue-700")
                ui.label(current_meta["description"]).classes("text-sm text-slate-600")


@ui.page("/workspace")
def workspace_page() -> None:
    query_mode = str(ui.context.client.request.query_params.get("mode", DEFAULT_MODE)).lower()
    mode = query_mode if query_mode in VIEW_META else DEFAULT_MODE

    with create_layout("/workspace"):
        page_header(
            "\u667a\u80fd\u95ee\u7b54\u4e0e\u591a\u6a21\u6001\u68c0\u7d22",
            "\u9762\u5411\u544a\u8b66\u6570\u636e\u7684\u7edf\u4e00\u5206\u6790\u754c\u9762\uff0c\u652f\u6301\u81ea\u7136\u8bed\u8a00\u95ee\u6570\u3001"
            "\u544a\u8b66\u660e\u7ec6\u8ffd\u6eaf\u3001\u56fe\u6587\u89c6\u9891\u76f8\u4f3c\u68c0\u7d22\u548c\u5a92\u4f53\u8054\u52a8\u6d4f\u89c8\u3002",
        )

        _render_toolbar(mode)

        with ui.column().classes("w-full mt-6"):
            if mode == "qa":
                render_qa_view(embedded=True, active_path="/workspace")
            else:
                render_search_view(embedded=True, active_path="/workspace")
