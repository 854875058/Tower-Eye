"""
自动标注工具界面 - 简洁美观版
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from streamlit_image_coordinates import streamlit_image_coordinates

from pipeline.utils import resolve_path, ensure_parent_dir
from pipeline.label_auto import save_yolo_label
from pipeline.auto_label_engine import (
    AutoLabelEngine, CLASS_NAMES_CN, TARGET_CLASSES,
    get_track_color, TRACK_COLORS
)

# 配置
VIDEO_EXTS = ['.mp4', '.avi', '.mov', '.mkv', '.webp']
DEFAULT_IMAGES_DIR = "data/warning_img"
DEFAULT_VIDEOS_DIR = "data/warning_file"


def init_state():
    defaults = {
        "files": [],
        "idx": 0,
        "anns": {},
        "is_video": False,
        "draw_start": {},
        "cls_sel": "car",
        "show_auto": True,
        "show_manual": True,
        "show_conf": False,
        "conf_threshold": 0.25,
        "zoom": 1.0,
        "box_thickness": 2,
        "class_filter": "全部",
        "draw_enabled": True,
        "img_dir": DEFAULT_IMAGES_DIR,
        "vid_dir": DEFAULT_VIDEOS_DIR,
        "out_dir": "data/labels/auto",
        "want_tracking": True,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


@st.cache_resource
def get_engine() -> AutoLabelEngine:
    return AutoLabelEngine()


def summarize_anns(anns: List[Dict]) -> Tuple[int, int, int, Dict[str, int]]:
    total = len(anns)
    auto_cnt = sum(1 for a in anns if not a.get("manual"))
    manual_cnt = total - auto_cnt
    by_class: Dict[str, int] = {}
    for a in anns:
        cls = a.get("class", "unknown")
        by_class[cls] = by_class.get(cls, 0) + 1
    return total, auto_cnt, manual_cnt, by_class


def filter_anns(
    anns: List[Dict],
    show_auto: bool,
    show_manual: bool,
    conf_threshold: float,
    cls_filter: str,
) -> List[Dict]:
    res = []
    for a in anns:
        manual = a.get("manual", False)
        if manual and not show_manual:
            continue
        if (not manual) and not show_auto:
            continue
        if (not manual) and a.get("confidence", 1.0) < conf_threshold:
            continue
        if cls_filter != "全部" and a.get("class") != cls_filter:
            continue
        res.append(a)
    return res


def ensure_ann_list(key: str) -> List[Dict]:
    anns = st.session_state.anns.get(key)
    if not isinstance(anns, list):
        st.session_state.anns[key] = []
    return st.session_state.anns[key]


def draw(
    img: np.ndarray,
    anns: List[Dict],
    show_conf: bool = False,
    thickness: int = 2,
    font_size: int = 14,
) -> np.ndarray:
    """绘制标注"""
    colors = {
        'person': (0, 255, 0), 'car': (0, 128, 255), 'truck': (255, 128, 0), 'bus': (128, 0, 255),
        'van': (135, 206, 250), 'motorcycle': (255, 0, 128), 'bicycle': (0, 255, 255),
        'excavator': (255, 165, 0), 'bulldozer': (0, 206, 209), 'dump truck': (255, 20, 147),
        'tractor': (147, 112, 219), 'trailer': (255, 215, 0)
    }

    thickness = max(1, int(thickness))
    font_size = max(10, int(font_size))
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_pil = Image.fromarray(img_rgb)
    draw_obj = ImageDraw.Draw(img_pil, "RGBA")
    ih, iw = img.shape[:2]

    # 加载字体 - 尝试多个系统字体路径
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/PingFangSC.ttc",
        "/System/Library/Fonts/Hiragino Sans GB W3.otf",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    font = None
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    for ann in anns:
        print(f"[Draw-Debug] ann: {ann}")
        if "bbox" not in ann or "class" not in ann:
            print(f"[Draw-Debug] 跳过: 缺少 bbox 或 class")
            continue
        x1, y1, x2, y2 = ann['bbox']
        # 检查是否是归一化坐标（所有值 <= 1.0），如果是则转换为像素坐标
        if max(x1, y1, x2, y2) <= 1.0:
            x1 = int(x1 * iw)
            y1 = int(y1 * ih)
            x2 = int(x2 * iw)
            y2 = int(y2 * ih)
        else:
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        x1 = max(0, min(iw - 1, x1))
        x2 = max(0, min(iw - 1, x2))
        y1 = max(0, min(ih - 1, y1))
        y2 = max(0, min(ih - 1, y2))
        if x2 <= x1 or y2 <= y1:
            print(f"[Draw-Debug] 跳过: 无效 bbox ({x1}, {y1}, {x2}, {y2})")
            continue
        c = colors.get(ann['class'], (255, 128, 0))
        print(f"[Draw-Debug] 绘制: class={ann['class']}, bbox=({x1}, {y1}, {x2}, {y2})")
        tag = "手" if ann.get("manual") else "自"
        label = CLASS_NAMES_CN.get(ann['class'], ann['class'])
        label = f"[{tag}] {label}"
        if show_conf:
            label = f"{label} {ann.get('confidence', 1.0):.2f}"

        draw_obj.rectangle([x1, y1, x2, y2], outline=(*c, 255), width=thickness)
        try:
            text_bbox = draw_obj.textbbox((0, 0), label, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
        except Exception:
            text_w, text_h = draw_obj.textsize(label, font=font)
        pad = 2
        tx1 = x1
        ty1 = max(0, y1 - text_h - pad * 2)
        tx2 = min(iw - 1, x1 + text_w + pad * 2)
        ty2 = min(ih - 1, ty1 + text_h + pad * 2)
        draw_obj.rectangle([tx1, ty1, tx2, ty2], fill=(*c, 200))
        draw_obj.text((tx1 + pad, ty1 + pad), label, font=font, fill=(255, 255, 255, 255))

    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def draw_tracking(
    img: np.ndarray,
    tracks: List[Dict],
    show_conf: bool = False,
    thickness: int = 3,
    font_size: int = 16,
) -> np.ndarray:
    """绘制带跟踪ID的标注"""
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_pil = Image.fromarray(img_rgb)
    draw_obj = ImageDraw.Draw(img_pil, "RGBA")
    ih, iw = img.shape[:2]

    # 加载字体 - 尝试多个系统字体路径
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/PingFangSC.ttc",
        "/System/Library/Fonts/Hiragino Sans GB W3.otf",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    font = None
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    for trk in tracks:
        if "bbox" not in trk or "track_id" not in trk:
            continue
        x1, y1, x2, y2 = trk['bbox']
        # 检查是否是归一化坐标（所有值 <= 1.0），如果是则转换为像素坐标
        if max(x1, y1, x2, y2) <= 1.0:
            x1 = int(x1 * iw)
            y1 = int(y1 * ih)
            x2 = int(x2 * iw)
            y2 = int(y2 * ih)
        else:
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        track_id = trk.get('track_id', 0)
        cls = trk.get('class', 'unknown')
        conf = trk.get('confidence', 0.0)

        # 边界检查
        x1 = max(0, min(iw - 1, x1))
        x2 = max(0, min(iw - 1, x2))
        y1 = max(0, min(ih - 1, y1))
        y2 = max(0, min(ih - 1, y2))

        if x2 <= x1 or y2 <= y1:
            continue

        # 颜色基于跟踪ID
        color = get_track_color(track_id)
        label_color = (*color, 200)

        # 类别中文名
        cls_cn = CLASS_NAMES_CN.get(cls, cls)

        # 标签文本
        label = f"#{track_id} {cls_cn}"
        if show_conf and conf > 0:
            label = f"{label} {conf:.2f}"

        # 绘制边界框
        draw_obj.rectangle([x1, y1, x2, y2], outline=(*color, 255), width=thickness)

        # 计算标签尺寸
        try:
            text_bbox = draw_obj.textbbox((0, 0), label, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
        except Exception:
            text_w, text_h = 120, 20

        pad = 4
        tx1 = x1
        ty1 = max(0, y1 - text_h - pad * 2)
        tx2 = min(iw - 1, tx1 + text_w + pad * 2)
        ty2 = min(ih - 1, ty1 + text_h + pad * 2)

        # 绘制标签背景
        draw_obj.rectangle([tx1, ty1, tx2, ty2], fill=label_color)
        # 绘制标签文字
        draw_obj.text((tx1 + pad, ty1 + pad), label, font=font, fill=(255, 255, 255, 255))

        # 绘制中心点
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        draw_obj.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=(*color, 255), outline=(255, 255, 255, 255))

    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def save_labels(path: Path, anns: List[Dict], w: int, h: int):
    """保存YOLO格式标签"""
    path.parent.mkdir(parents=True, exist_ok=True)
    labels = []
    for ann in anns:
        x1, y1, x2, y2 = ann['bbox']
        cls_id = ann.get("class_id")
        if cls_id is None:
            cls_id = TARGET_CLASSES.get(ann.get("class", ""), 0)
        labels.append((
            cls_id,
            ann.get('class', 'unknown'),
            ((x1 + x2) / 2) / w,
            ((y1 + y2) / 2) / h,
            (x2 - x1) / w,
            (y2 - y1) / h,
            ann.get('confidence', 1.0)
        ))
    save_yolo_label(path, labels)


def render_labeling_interface():
    init_state()

    engine = get_engine()
    engine_ready = engine.is_available()

    st.markdown(
        """
        <style>
        .main-header {
            text-align: center;
            padding: 1rem;
            background: linear-gradient(90deg, #5B8FF9 0%, #61DDAA 100%);
            color: white;
            border-radius: 12px;
            margin-bottom: 1rem;
        }
        .sub-note {
            color: #f2f2f2;
            font-size: 0.9rem;
            margin-top: -0.2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="main-header"><h1>🏷️ 自动标注工具</h1><div class="sub-note">自动预标注 · 手动修正 · YOLO 导出</div></div>',
        unsafe_allow_html=True,
    )

    # ===== 侧边栏 =====
    with st.sidebar:
        st.header("📁 数据源")
        mtype = st.radio(
            "文件类型",
            ["图片", "视频"],
            horizontal=True,
            index=1 if st.session_state.is_video else 0,
        )
        st.session_state.is_video = (mtype == "视频")
        st.session_state.idx = 0  # 重置索引

        if st.session_state.is_video:
            st.text_input("视频目录", value=st.session_state.get("vid_dir", DEFAULT_VIDEOS_DIR), key="vid_dir")
        else:
            st.text_input("图片目录", value=st.session_state.get("img_dir", DEFAULT_IMAGES_DIR), key="img_dir")

        # 自动检查是否有保存的状态
        if not st.session_state.get('files'):
            cur_dir = st.session_state.vid_dir if st.session_state.is_video else st.session_state.img_dir
            cur_dir_name = Path(cur_dir).name
            state_dir = ROOT / "data" / "tmp" / ("videos" if st.session_state.is_video else "images")
            state_dir.mkdir(parents=True, exist_ok=True)
            state_file = state_dir / f"{cur_dir_name}_state.json"
            if state_file.exists():
                try:
                    with open(state_file, 'r', encoding='utf-8') as f:
                        state_data = json.load(f)
                    saved_files = state_data.get('files', [])
                    # 验证文件是否还存在
                    if saved_files and all(Path(f).exists() for f in saved_files):
                        st.session_state.files = saved_files
                        st.session_state.anns = state_data.get('anns', {})
                        st.session_state.idx = 0
                        # 清除旧的场景描述缓存
                        for k in list(st.session_state.keys()):
                            if k.startswith('img_desc_') or k.startswith('video_desc_'):
                                del st.session_state[k]
                        st.rerun()
                except Exception as e:
                    print(f"[UI] 自动恢复状态失败: {e}")

        st.text_input("输出目录", value=st.session_state.get("out_dir", "data/labels/auto"), key="out_dir")
        ensure_parent_dir(resolve_path(st.session_state.out_dir) / ".placeholder")

        if st.session_state.is_video:
            st.session_state.want_tracking = True
            st.session_state.frame_interval = 1
            st.session_state.detect_size = 640
            if not st.session_state.want_tracking:
                num_workers = st.selectbox("并行进程数", [1, 2, 4, 8], index=2,
                    help="不跟踪时可启用多进程并行检测。CPU核心数建议设为最大")
                st.session_state.num_workers = num_workers

        st.divider()

        # 统一的扫描标注按钮
        if st.button("🚀 扫描并开始标注", type="primary", use_container_width=True, disabled=not engine_ready):
            if not engine_ready:
                st.error("自动标注引擎不可用，请检查 API 配置")
            else:
                odir = resolve_path(st.session_state.out_dir)
                odir.mkdir(parents=True, exist_ok=True)

                # 扫描文件
                if st.session_state.is_video:
                    d = resolve_path(st.session_state.vid_dir)
                    if d.exists():
                        files = sorted({str(f) for ext in VIDEO_EXTS for f in d.glob(f"*{ext}")})
                    else:
                        st.error("❌ 视频目录不存在")
                        files = []
                else:
                    d = resolve_path(st.session_state.img_dir)
                    if d.exists():
                        files = sorted([str(f) for f in d.glob("*") if f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.bmp', '.webp']])
                    else:
                        st.error("❌ 图片目录不存在")
                        files = []

                if not files:
                    st.error("未找到任何文件")
                else:
                    st.session_state.files = files
                    st.session_state.idx = 0
                    st.session_state.anns = {}
                    st.session_state.draw_start = {}
                    st.session_state.use_tracking = st.session_state.get('want_tracking', False)

                    # 显示设置默认值
                    if 'show_auto' not in st.session_state:
                        st.session_state.show_auto = True
                    if 'show_manual' not in st.session_state:
                        st.session_state.show_manual = True
                    if 'show_conf' not in st.session_state:
                        st.session_state.show_conf = True
                    if 'conf_threshold' not in st.session_state:
                        st.session_state.conf_threshold = 0.1
                    if 'box_thickness' not in st.session_state:
                        st.session_state.box_thickness = 2
                    if 'class_filter' not in st.session_state:
                        st.session_state.class_filter = "全部"

                    # 准备临时目录
                    if st.session_state.is_video:
                        tmp_dir = ROOT / "data" / "tmp" / "videos"
                    else:
                        tmp_dir = ROOT / "data" / "tmp" / "images"
                    tmp_dir.mkdir(parents=True, exist_ok=True)

                    # 检查是否已有保存的状态
                    dir_name = Path(st.session_state.img_dir if not st.session_state.is_video else st.session_state.vid_dir).name
                    state_file = tmp_dir / f"{dir_name}_state.json"

                    loaded_state = None
                    if state_file.exists():
                        try:
                            with open(state_file, 'r', encoding='utf-8') as f:
                                loaded_state = json.load(f)
                            # 验证状态中的文件列表是否匹配
                            if loaded_state.get('files') == files:
                                st.info("✅ 检测到已保存的标注状态，正在恢复...")
                                st.session_state.files = loaded_state.get('files', files)
                                st.session_state.anns = loaded_state.get('anns', {})
                                st.session_state.idx = loaded_state.get('idx', 0)
                                # 恢复场景描述缓存
                                for k in list(st.session_state.keys()):
                                    if k.startswith('img_desc_') or k.startswith('video_desc_'):
                                        del st.session_state[k]
                                st.rerun()
                                return
                            else:
                                st.info("检测到旧状态文件，将重新处理")
                        except Exception as e:
                            print(f"[UI] 加载状态失败: {e}")

                    # 开始标注
                    progress = st.progress(0)
                    progress_text = st.empty()
                    all_res = {}
                    if st.session_state.is_video:
                        interval = st.session_state.get('frame_interval', 3)
                        detect_size = st.session_state.get('detect_size', 320)
                        num_workers = st.session_state.get('num_workers', 4)
                        for i, vf in enumerate(files):
                            progress.progress((i + 1) / len(files))
                            progress_text.text(f"处理中: {i + 1}/{len(files)}")
                            if st.session_state.use_tracking:
                                with st.spinner(f"处理视频: {Path(vf).name} (间隔{interval}帧, 分辨率{detect_size})"):
                                    result = engine.detect_video_with_tracking(vf, frame_interval=interval, detect_size=detect_size, preview_dir=str(tmp_dir))
                                    all_res[vf] = result
                            else:
                                # 多进程并行检测（不带跟踪）
                                with st.spinner(f"处理视频: {Path(vf).name} (多进程{num_workers}核, 分辨率{detect_size})"):
                                    frames = engine.detect_video_parallel(vf, num_workers=num_workers, frame_interval=interval, detect_size=detect_size)
                                    all_res[vf] = frames
                        st.session_state.anns = all_res
                    else:
                        for i, f in enumerate(files):
                            progress.progress((i + 1) / len(files))
                            progress_text.text(f"处理中: {i + 1}/{len(files)}")
                            with st.spinner(f"YOLO+VL检测: {Path(f).name}"):
                                auto_res = engine.detect_image_yolo_then_vl(f, preview_dir=str(tmp_dir))
                                all_res[f] = auto_res
                        st.session_state.anns = all_res
                    # 保存状态到文件
                    dir_name = Path(st.session_state.img_dir if not st.session_state.is_video else st.session_state.vid_dir).name
                    if st.session_state.is_video:
                        state_dir = ROOT / "data" / "tmp" / "videos"
                    else:
                        state_dir = ROOT / "data" / "tmp" / "images"
                    state_dir.mkdir(parents=True, exist_ok=True)
                    state_file = state_dir / f"{dir_name}_state.json"
                    state_data = {
                        'files': files,
                        'anns': st.session_state.anns,
                        'idx': st.session_state.idx,
                        'is_video': st.session_state.is_video,
                        'dir_name': dir_name,
                    }
                    with open(state_file, 'w', encoding='utf-8') as f:
                        json.dump(state_data, f, ensure_ascii=False)
                    progress.empty()
                    progress_text.empty()

        # 预览视频下载按钮
        if st.session_state.get('use_tracking') and st.session_state.is_video:
            cur = st.session_state.files[st.session_state.idx] if st.session_state.files else None
            if cur:
                video_p = Path(cur)
                tmp_dir = ROOT / "data" / "tmp" / "videos"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                preview_path = tmp_dir / (video_p.name.replace(video_p.suffix, '') + '_tracked.mp4')
                print(f"[UI] 下载按钮检查预览视频: {preview_path}")
                if preview_path.exists():
                    print(f"[UI] 预览视频存在，大小: {preview_path.stat().st_size / 1024 / 1024:.2f} MB")
                    with open(preview_path, 'rb') as f:
                        st.download_button(
                            label="📥 下载预览视频",
                            data=f.read(),
                            file_name=preview_path.name,
                            mime='video/mp4'
                        )
                else:
                    print(f"[UI] 预览视频不存在，无法下载")

        st.divider()
        if st.button("💾 保存全部", use_container_width=True, disabled=not st.session_state.anns):
            if st.session_state.is_video:
                st.warning("视频暂不支持保存为 YOLO 标签")
            else:
                for f in st.session_state.files:
                    ia = st.session_state.anns.get(f, [])
                    fi = cv2.imread(f)
                    if fi is not None:
                        save_labels(
                            resolve_path(st.session_state.out_dir) / f"{Path(f).stem}.txt",
                            ia,
                            fi.shape[1],
                            fi.shape[0],
                        )
                st.success("✅ 已保存到 " + st.session_state.out_dir)

        st.caption("保存格式：YOLO txt（class x y w h）")

        if not engine_ready:
            st.warning("自动标注引擎不可用，请检查 API 配置")

        st.divider()
        st.subheader("📋 类别")
        for cls in TARGET_CLASSES.keys():
            cn = CLASS_NAMES_CN.get(cls, cls)
            st.caption(f"• {cn} ({cls})")

    # ===== 主界面 =====
    files = st.session_state.files
    if not files:
        st.info("👈 请在左侧设置目录并扫描文件")
        st.caption("支持自动标注预览、手动修正，并保存为 YOLO 格式")
        return

    # 文件导航栏
    st.markdown("### 📂 文件导航")
    col_nav1, col_nav2, col_nav3 = st.columns([1, 4, 1])
    with col_nav1:
        if st.button("◀ 上一张", disabled=st.session_state.idx == 0):
            st.session_state.idx = max(0, st.session_state.idx - 1)
    with col_nav2:
        cur_file = files[st.session_state.idx]
        file_name = Path(cur_file).name
        total = len(files)
        current = st.session_state.idx + 1
        st.markdown(
            f"""
            <div style="text-align: center; padding: 10px; background: #f0f2f6; border-radius: 10px;">
                <strong>{file_name}</strong> <span style="color: #666;">({current}/{total})</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_nav3:
        if st.button("下一张 ▶", disabled=st.session_state.idx >= len(files) - 1):
            st.session_state.idx = min(len(files) - 1, st.session_state.idx + 1)

    cur = files[st.session_state.idx]
    class_keys = list(TARGET_CLASSES.keys())

    # 图片预览
    if not st.session_state.is_video:
        img = cv2.imread(cur)
        if img is None:
            st.error("图片读取失败")
            return
        h, w = img.shape[:2]
        img_anns = ensure_ann_list(cur)

        total_cnt, auto_cnt, manual_cnt, by_class = summarize_anns(img_anns)
        col_stat1, col_stat2, col_stat3 = st.columns(3)
        col_stat1.metric("标注总数", total_cnt)
        col_stat2.metric("自动标注", auto_cnt)
        col_stat3.metric("手动标注", manual_cnt)

        st.divider()

        # 结果预览区域
        st.subheader("📷 结果预览")

        # 获取标注数据
        img_anns = ensure_ann_list(cur)
        visible_anns = filter_anns(
            img_anns,
            show_auto=st.session_state.show_auto,
            show_manual=st.session_state.show_manual,
            conf_threshold=st.session_state.conf_threshold,
            cls_filter=st.session_state.class_filter,
        )

        # 初始化点击状态（必须在使用前定义）
        draw_start_key = f"draw_start_{cur}"
        draw_end_key = f"draw_end_{cur}"
        last_click_key = f"last_click_{cur}"

        if draw_start_key not in st.session_state:
            st.session_state[draw_start_key] = None
        if draw_end_key not in st.session_state:
            st.session_state[draw_end_key] = None
        if last_click_key not in st.session_state:
            st.session_state[last_click_key] = None

        # 绘制标注框到图片
        disp = img.copy()
        disp = draw(
            disp,
            visible_anns,
            show_conf=st.session_state.show_conf,
            thickness=max(1, int(st.session_state.box_thickness)),
            font_size=14,
        )

        # 绘制正在画的框（绿色）
        if st.session_state[draw_start_key] and st.session_state[draw_end_key]:
            x1 = min(st.session_state[draw_start_key][0], st.session_state[draw_end_key][0])
            y1 = min(st.session_state[draw_start_key][1], st.session_state[draw_end_key][1])
            x2 = max(st.session_state[draw_start_key][0], st.session_state[draw_end_key][0])
            y2 = max(st.session_state[draw_start_key][1], st.session_state[draw_end_key][1])
            cv2.rectangle(disp, (x1, y1), (x2, y2), (0, 255, 0), 4)

        disp_rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)

        # 计算显示尺寸
        max_display_width = 800
        display_width = min(w, max_display_width)
        display_height = int(h * display_width / w) if w > 0 else h
        scale_x = w / display_width
        scale_y = h / display_height

        # 缩放到显示尺寸
        disp_rgb_resized = cv2.resize(disp_rgb, (display_width, display_height), interpolation=cv2.INTER_AREA)

        # 获取点击坐标（在 col_img 块外部，避免作用域问题）
        coords_value = streamlit_image_coordinates(
            disp_rgb_resized,
            key=f"draw_coords_{cur}",
            height=display_height,
            width=display_width,
        )

        # 处理点击坐标（在任何 with 块外部）
        if coords_value is not None:
            click_x = coords_value['x']
            click_y = coords_value['y']

            if not (click_x == 0 and click_y == 0):
                last_click = st.session_state.get(last_click_key)
                if last_click != coords_value:
                    st.session_state[last_click_key] = coords_value
                    orig_x = int(click_x * (w / display_width))
                    orig_y = int(click_y * (h / display_height))

                    if st.session_state[draw_start_key] is None:
                        st.session_state[draw_start_key] = (orig_x, orig_y)
                        st.session_state[draw_end_key] = None
                    elif st.session_state[draw_end_key] is None:
                        if st.session_state[draw_start_key] == (orig_x, orig_y):
                            st.toast("请点击不同的位置")
                        else:
                            st.session_state[draw_end_key] = (orig_x, orig_y)
                            x1 = min(st.session_state[draw_start_key][0], st.session_state[draw_end_key][0])
                            y1 = min(st.session_state[draw_start_key][1], st.session_state[draw_end_key][1])
                            x2 = max(st.session_state[draw_start_key][0], st.session_state[draw_end_key][0])
                            y2 = max(st.session_state[draw_start_key][1], st.session_state[draw_end_key][1])

                            if x2 > x1 and y2 > y1 and (x2 - x1) > 5 and (y2 - y1) > 5:
                                # 临时 selected_class 用于处理点击
                                if 'cls_sel' not in st.session_state:
                                    st.session_state.cls_sel = class_keys[0]
                                img_anns.append({
                                    "class": st.session_state.cls_sel,
                                    "class_id": TARGET_CLASSES[st.session_state.cls_sel],
                                    "confidence": 1.0,
                                    "bbox": [x1 / w, y1 / h, x2 / w, y2 / h],
                                    "manual": True,
                                })
                                st.toast(f"已添加: {CLASS_NAMES_CN.get(st.session_state.cls_sel, st.session_state.cls_sel)}")
                                st.session_state[draw_start_key] = None
                                st.session_state[draw_end_key] = None
                                st.session_state[last_click_key] = None
                                st.rerun()
                            else:
                                st.warning("框太小")
                                st.session_state[draw_start_key] = None
                                st.session_state[draw_end_key] = None
                                st.session_state[last_click_key] = None
                    else:
                        st.session_state[draw_start_key] = (orig_x, orig_y)
                        st.session_state[draw_end_key] = None

        # 图片 + 右侧标注列表布局
        col_img, col_tool = st.columns([4, 2], gap="large")

        with col_img:
            # 显示图片和状态提示
            if st.session_state[draw_start_key]:
                sx, sy = st.session_state[draw_start_key]
                st.info(f"👆 起点: ({sx}, {sy})，请点击右下角完成画框")
            else:
                st.info("👆 点击图片左上角和右下角绘制标注框")

            # 场景描述
            img_desc_key = f"img_desc_{cur}"
            if img_desc_key not in st.session_state:
                st.session_state[img_desc_key] = None
            if st.session_state[img_desc_key] is None:
                with st.spinner("正在分析场景..."):
                    tmp_dir = ROOT / "data" / "tmp" / "images"
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    desc = engine.describe_image(cur, preview_dir=str(tmp_dir))
                    st.session_state[img_desc_key] = desc
            if st.session_state[img_desc_key]:
                st.markdown(f"""
                <div style="padding: 10px; background: #e8f4f8; border-radius: 8px; margin: 10px 0;">
                    <strong style="color: #1a73e8;">📝 场景描述</strong>
                    <p style="margin: 5px 0 0 0; color: #333;">{st.session_state[img_desc_key]}</p>
                </div>
                """, unsafe_allow_html=True)

            # 手动标注设置（图片下方）
            st.caption(f"图片尺寸: {w}×{h}")
            col_manual, col_cancel, col_stats = st.columns([2, 1, 2])
            with col_manual:
                st.markdown("**手动标注**")
                selected_class = st.selectbox(
                    "选择类别",
                    class_keys,
                    key="cls_sel",
                    format_func=lambda x: CLASS_NAMES_CN.get(x, x),
                )
            with col_cancel:
                if st.session_state[draw_start_key] or st.session_state[draw_end_key]:
                    if st.button("取消画框", type="secondary"):
                        st.session_state[draw_start_key] = None
                        st.session_state[draw_end_key] = None
                        st.session_state[last_click_key] = None
                        # 清除 streamlit_image_coordinates 的缓存
                        del st.session_state[f"draw_coords_{cur}"]
                        st.rerun()
            with col_stats:
                st.caption(f"显示 {len(visible_anns)}/{len(img_anns)} 个标注")

        with col_tool:
            # 标注列表
            st.subheader("📋 标注列表")

            if not img_anns:
                st.info("暂无标注")
            else:
                # 类别统计
                if by_class:
                    summary = " / ".join(
                        f"{CLASS_NAMES_CN.get(k, k)} {v}"
                        for k, v in sorted(by_class.items(), key=lambda x: -x[1])
                    )
                    st.caption(f"类别统计：{summary}")

                # 显示所有标注
                for i, a in enumerate(img_anns):
                    tag = "手动" if a.get("manual") else "自动"
                    label = CLASS_NAMES_CN.get(a.get("class", ""), a.get("class", "unknown"))

                    cols = st.columns([1, 2, 2, 1, 1])
                    cols[0].write(f"**{i + 1}**")
                    cols[1].write(f"{tag} · {label}")

                    cls_key = f"ann_cls_{cur}_{i}"
                    if cls_key not in st.session_state:
                        st.session_state[cls_key] = a.get("class", class_keys[0])
                    new_cls = cols[2].selectbox(
                        "选择类别",
                        class_keys,
                        key=cls_key,
                        index=class_keys.index(a.get("class", class_keys[0])) if a.get("class") in class_keys else 0,
                        format_func=lambda x: CLASS_NAMES_CN.get(x, x),
                    )
                    if new_cls != a.get("class"):
                        a["class"] = new_cls
                        a["class_id"] = TARGET_CLASSES[new_cls]

                    bbox = a.get("bbox", [0, 0, 0, 0])
                    if max(bbox) <= 1.0:
                        px1, py1, px2, py2 = int(bbox[0] * w), int(bbox[1] * h), int(bbox[2] * w), int(bbox[3] * h)
                        cols[3].caption(f"{px1},{py1},{px2},{py2}")
                    else:
                        cols[3].caption(f"{int(bbox[0])},{int(bbox[1])},{int(bbox[2])},{int(bbox[3])}")

                    if cols[4].button("删除", key=f"del_{cur}_{i}", type="secondary"):
                        st.session_state.anns[cur].pop(i)
                        st.rerun()

                # 操作按钮
                st.divider()
                col_save, col_clear = st.columns(2)
                with col_save:
                    if st.button("💾 保存", use_container_width=True):
                        save_labels(resolve_path(st.session_state.out_dir) / f"{Path(cur).stem}.txt", img_anns, w, h)
                        st.success("✅ 已保存")
                with col_clear:
                    if st.button("🗑️ 清空", type="secondary", use_container_width=True):
                        st.session_state.anns[cur] = []
                        st.rerun()

    # 视频预览
    else:
        data = st.session_state.anns.get(cur, {})
        frames = data if isinstance(data, dict) else {}
        if not frames:
            st.info("当前视频暂无标注结果")
            return

        # 判断是否为跟踪模式
        first_frame_data = list(frames.values())[0] if frames else {}
        is_tracking_mode = 'tracks' in first_frame_data or 'track_id' in (first_frame_data[0] if first_frame_data else {})

        fidxs = sorted(frames.keys())
        col_img, col_tool = st.columns([4, 2], gap="large")

        with col_tool:
            # 视频场景描述
            video_desc_key = f"video_desc_{cur}"
            if video_desc_key not in st.session_state:
                st.session_state[video_desc_key] = None
            if st.session_state[video_desc_key] is None:
                with st.spinner("正在分析视频场景..."):
                    tmp_dir = ROOT / "data" / "tmp" / "videos"
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    desc = engine.describe_video(cur, preview_dir=str(tmp_dir))
                    st.session_state[video_desc_key] = desc
            if st.session_state[video_desc_key]:
                st.markdown(f"""
                <div style="padding: 10px; background: #e8f4f8; border-radius: 8px; margin-bottom: 10px;">
                    <strong style="color: #1a73e8;">📝 视频场景描述</strong>
                    <p style="margin: 5px 0 0 0; color: #333;">{st.session_state[video_desc_key]}</p>
                </div>
                """, unsafe_allow_html=True)

            # 视频信息
            st.subheader("📊 视频信息")
            total_tracks = sum(f.get('total_tracks', 0) for f in frames.values())
            st.metric("总跟踪帧数", len(frames))
            st.metric("同时跟踪目标峰值", max((f.get('total_tracks', 0) for f in frames.values()), default=0))

        with col_img:
            st.subheader("🎬 视频预览")

            if is_tracking_mode:
                video_p = Path(cur)
                tmp_dir = ROOT / "data" / "tmp" / "videos"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                preview_path = tmp_dir / (video_p.name.replace(video_p.suffix, '') + '_tracked.mp4')
                print(f"[UI] 预览视频路径: {preview_path}")
                print(f"[UI] 预览视频存在: {preview_path.exists()}")

                if preview_path.exists():
                    try:
                        file_size = preview_path.stat().st_size
                        print(f"[UI] 预览视频大小: {file_size / 1024 / 1024:.2f} MB")

                        with open(preview_path, 'rb') as f:
                            video_bytes = f.read()
                        print(f"[UI] 读取视频字节数: {len(video_bytes)}")

                        st.video(video_bytes)
                        print(f"[UI] 视频已渲染")
                    except Exception as e:
                        print(f"[UI] 视频加载失败: {e}")
                        st.error(f"视频加载失败: {e}")
                else:
                    print(f"[UI] 预览视频不存在")
                    st.warning("预览视频未生成，请重新运行带跟踪的标注")

            else:
                # 普通模式
                fidx = st.selectbox("选择帧", range(len(fidxs)), format_func=lambda i: f"帧 {fidxs[i]}", key="fidx_select")
                frame_data = frames.get(fidxs[fidx], {})
                fanns = frame_data if isinstance(frame_data, list) else []
                visible = filter_anns(
                    fanns,
                    show_auto=st.session_state.show_auto,
                    show_manual=st.session_state.show_manual,
                    conf_threshold=st.session_state.conf_threshold,
                    cls_filter=st.session_state.class_filter,
                )

                col_stat1, col_stat2 = st.columns(2)
                col_stat1.metric("当前帧", fidxs[fidx])
                col_stat2.metric("目标数量", len(visible))

                st.divider()
                cap = cv2.VideoCapture(cur)
                cap.set(cv2.CAP_PROP_POS_FRAMES, fidxs[fidx])
                ret, frame = cap.read()
                cap.release()
                if ret:
                    st.image(
                        draw(
                            frame,
                            visible,
                            show_conf=st.session_state.show_conf,
                            thickness=st.session_state.box_thickness,
                            font_size=14,
                        ),
                        channels="BGR",
                        width=900,
                    )


if __name__ == "__main__":
    st.set_page_config(page_title="自动标注工具", layout="wide", page_icon="🏷️")
    render_labeling_interface()


def render_interface():
    """兼容旧版本的入口函数"""
    render_labeling_interface()

