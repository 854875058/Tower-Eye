"""Page 4: 自动标注"""
import asyncio
from pathlib import Path

from nicegui import ui
from poc.app.pages.shared import create_layout, page_header, resolve_path


@ui.page('/label')
def label_page():
    with create_layout('/label'):
        page_header('自动标注', 'YOLOv26x + VL 语义双引擎自动检测与标注')

        ls = {'files': [], 'idx': 0, 'dets': [], 'engine': None,
              'stats': {'total': 0, 'auto': 0, 'by_class': {}}}
        preview = ui.column().classes('w-full')
        stats_row = ui.row().classes('w-full gap-4 mb-4')

        def init_engine():
            if ls['engine']: return ls['engine']
            try:
                from poc.pipeline.auto_label_engine import AutoLabelEngine
                ls['engine'] = AutoLabelEngine(); return ls['engine']
            except Exception as e:
                ui.notify(f'标注引擎初始化失败: {e}', type='negative'); return None

        def scan(directory: str):
            p = resolve_path(directory)
            if not p.exists():
                ui.notify(f'目录不存在: {p}', type='warning'); return
            exts = {'.jpg', '.jpeg', '.png', '.bmp'}
            ls['files'] = sorted([f for f in p.iterdir() if f.suffix.lower() in exts])
            ls['idx'] = 0; ls['dets'] = []
            ui.notify(f'扫描到 {len(ls["files"])} 个文件', type='positive')
            show()

        def show():
            preview.clear()
            if not ls['files']:
                with preview: ui.label('暂无文件，请先扫描目录').classes('text-slate-400')
                return
            fp = ls['files'][ls['idx']]
            with preview:
                ui.label(f'{fp.name}  ({ls["idx"]+1}/{len(ls["files"])})').classes('font-bold text-slate-700 mb-2')
                if ls['dets']:
                    try:
                        import cv2, base64
                        img = cv2.imread(str(fp)); h, w = img.shape[:2]
                        for d in ls['dets']:
                            bbox = d['bbox']
                            if all(0 <= v <= 1.0 for v in bbox):
                                x1, y1, x2, y2 = int(bbox[0]*w), int(bbox[1]*h), int(bbox[2]*w), int(bbox[3]*h)
                            else:
                                x1, y1, x2, y2 = [int(v) for v in bbox]
                            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(img, f"{d.get('class','?')} {d.get('confidence',0):.2f}",
                                        (x1, max(y1-8, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                        _, buf = cv2.imencode('.jpg', img)
                        ui.image(f'data:image/jpeg;base64,{base64.b64encode(buf).decode()}').classes('w-full max-w-2xl rounded-xl')
                    except Exception:
                        ui.image(f'/warning_img/{fp.name}').classes('w-full max-w-2xl rounded-xl')
                else:
                    ui.image(f'/warning_img/{fp.name}').classes('w-full max-w-2xl rounded-xl')
                if ls['dets']:
                    ui.label(f'检测到 {len(ls["dets"])} 个目标').classes('font-semibold text-slate-700 mt-3 mb-1')
                    rows = [{"类别": d.get("class", ""), "置信度": f"{d.get('confidence',0):.2f}",
                             "边界框": str(d.get("bbox", []))} for d in ls['dets']]
                    ui.table(columns=[{"name": c, "label": c, "field": c} for c in ["类别", "置信度", "边界框"]],
                             rows=rows).classes('w-full')

        def update_stats():
            stats_row.clear()
            with stats_row:
                for lbl, val in [("总检测数", ls['stats']['total']), ("自动标注", ls['stats']['auto'])]:
                    with ui.element('div').classes('kpi-card text-center flex-1'):
                        ui.label(str(val)).classes('text-2xl font-bold text-blue-600')
                        ui.label(lbl).classes('text-sm text-slate-500')
                if ls['stats']['by_class']:
                    with ui.element('div').classes('kpi-card flex-1'):
                        ui.label('按类别').classes('text-sm text-slate-500 mb-1')
                        for cls, cnt in ls['stats']['by_class'].items():
                            ui.label(f'{cls}: {cnt}').classes('text-sm text-slate-700')

        async def detect():
            engine = init_engine()
            if not engine or not ls['files']:
                ui.notify('请先扫描目录', type='warning'); return
            fp = ls['files'][ls['idx']]
            ui.notify(f'正在检测 {fp.name}...', type='info')
            try:
                dets = await asyncio.get_event_loop().run_in_executor(None, lambda: engine.detect_image(str(fp)))
                ls['dets'] = dets
                ls['stats']['total'] += len(dets); ls['stats']['auto'] += len(dets)
                for d in dets:
                    cls = d.get('class', 'unknown')
                    ls['stats']['by_class'][cls] = ls['stats']['by_class'].get(cls, 0) + 1
                ui.notify(f'检测到 {len(dets)} 个目标', type='positive')
                show(); update_stats()
            except Exception as e:
                ui.notify(f'检测失败: {e}', type='negative')

        async def detect_all():
            engine = init_engine()
            if not engine or not ls['files']:
                ui.notify('请先扫描目录', type='warning'); return
            ui.notify(f'批量检测 {len(ls["files"])} 张图片...', type='info')
            for i, fp in enumerate(ls['files']):
                try:
                    dets = await asyncio.get_event_loop().run_in_executor(None, lambda fp=fp: engine.detect_image(str(fp)))
                    ls['stats']['total'] += len(dets); ls['stats']['auto'] += len(dets)
                    for d in dets:
                        cls = d.get('class', 'unknown')
                        ls['stats']['by_class'][cls] = ls['stats']['by_class'].get(cls, 0) + 1
                except Exception: pass
            update_stats()
            ui.notify(f'批量检测完成', type='positive')

        def nav(delta):
            if not ls['files']: return
            ls['idx'] = max(0, min(len(ls['files'])-1, ls['idx']+delta))
            ls['dets'] = []; show()

        # 控制面板
        with ui.element('div').classes('kpi-card mb-6 w-full'):
            with ui.row().classes('items-center gap-4 w-full'):
                dir_input = ui.input('图片目录', value='warning_img').classes('flex-1').props('outlined dense')
                ui.button('扫描目录', on_click=lambda: scan(dir_input.value)).props('unelevated color=blue-6 rounded no-caps')
                ui.button('自动检测', on_click=detect).props('unelevated color=teal-6 rounded no-caps')
                ui.button('批量检测', on_click=detect_all).props('outline color=amber-8 rounded no-caps')
            with ui.row().classes('items-center gap-2 mt-3'):
                ui.button(icon='navigate_before', on_click=lambda: nav(-1)).props('flat round')
                ui.button(icon='navigate_next', on_click=lambda: nav(1)).props('flat round')

        update_stats()
        show()
