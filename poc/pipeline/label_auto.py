import argparse
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .utils import connect_db, load_yaml, resolve_path

try:
    from ultralytics import YOLO  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    YOLO = None

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}


def discover_media(dir_path: Path, exts: set) -> List[Path]:
    if not dir_path.exists():
        return []
    return [p for p in dir_path.rglob("*") if p.suffix.lower() in exts]


def build_asset_map(conn) -> Tuple[Dict[str, str], Dict[str, str]]:
    cursor = conn.execute("SELECT asset_id, file_path, file_name FROM assets")
    by_path = {}
    by_name = {}
    for row in cursor:
        if row["file_path"]:
            by_path[row["file_path"]] = row["asset_id"]
        if row["file_name"]:
            by_name[row["file_name"]] = row["asset_id"]
    return by_path, by_name


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def yolo_labels_from_result(
    result, class_names
) -> List[Tuple[int, str, float, float, float, float, float]]:
    labels: List[Tuple[int, str, float, float, float, float, float]] = []
    if not hasattr(result, "boxes") or result.boxes is None:
        return labels
    h, w = result.orig_shape
    for box in result.boxes:
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        cls_id = int(box.cls[0].item())
        conf = float(box.conf[0].item())
        x_center = ((x1 + x2) / 2.0) / w
        y_center = ((y1 + y2) / 2.0) / h
        width = (x2 - x1) / w
        height = (y2 - y1) / h
        if isinstance(class_names, dict):
            label_name = class_names.get(cls_id, str(cls_id))
        elif isinstance(class_names, (list, tuple)) and cls_id < len(class_names):
            label_name = class_names[cls_id]
        else:
            label_name = str(cls_id)
        labels.append((cls_id, label_name, x_center, y_center, width, height, conf))
    return labels


def save_yolo_label(
    path: Path, labels: List[Tuple[int, str, float, float, float, float, float]]
) -> None:
    if not labels:
        path.write_text("", encoding="utf-8")
        return
    lines = [
        f"{cls_id} {x:.6f} {y:.6f} {w:.6f} {h:.6f}"
        for cls_id, _, x, y, w, h, _ in labels
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def insert_detections(
    conn, asset_id: str, model_name: str, labels, frame_index=None, timestamp=None
):
    rows = []
    for _, label_name, x, y, w, h, conf in labels:
        rows.append(
            (
                uuid.uuid4().hex,
                asset_id,
                model_name,
                label_name,
                conf,
                x,
                y,
                w,
                h,
                frame_index,
                timestamp,
            )
        )
    conn.executemany(
        """
        INSERT OR REPLACE INTO detections (
            detection_id, asset_id, model_name, label, confidence,
            bbox_x, bbox_y, bbox_w, bbox_h, frame_index, timestamp_sec
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def run_on_images(
    model,
    image_paths: List[Path],
    labels_dir: Path,
    asset_map,
    model_name: str,
    confidence: float,
):
    conn = connect_db(asset_map["db_path"])
    by_path, by_name = build_asset_map(conn)
    for path in image_paths:
        result = model(str(path), conf=confidence)[0]
        labels = yolo_labels_from_result(result, model.names)
        label_path = labels_dir / f"{path.stem}.txt"
        save_yolo_label(label_path, labels)
        asset_id = by_path.get(str(path)) or by_name.get(path.name)
        if asset_id:
            insert_detections(conn, asset_id, model_name, labels)
    conn.commit()
    conn.close()


def run_on_videos(
    model,
    video_paths: List[Path],
    asset_map,
    model_name: str,
    frame_step: int,
    confidence: float,
):
    if cv2 is None:
        print("cv2 not available, skipping videos.")
        return
    conn = connect_db(asset_map["db_path"])
    by_path, by_name = build_asset_map(conn)
    for path in video_paths:
        asset_id = by_path.get(str(path)) or by_name.get(path.name)
        if not asset_id:
            continue
        cap = cv2.VideoCapture(str(path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frame_index = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_index % frame_step == 0:
                result = model(frame, conf=confidence)[0]
                labels = yolo_labels_from_result(result, model.names)
                timestamp = frame_index / fps if fps else None
                insert_detections(conn, asset_id, model_name, labels, frame_index, timestamp)
            frame_index += 1
        cap.release()
    conn.commit()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="POC YOLOv8 auto labeling")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    parser.add_argument("--output-dir", default="data/labels/auto")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--frame-step", type=int, default=30)
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()

    config = load_yaml(args.config)
    paths_cfg = config.get("paths", {})
    train_cfg = config.get("train", {})

    db_path = resolve_path(paths_cfg.get("db_path", "data/metadata.db"))
    raw_images_dir = resolve_path(paths_cfg.get("raw_images_dir", "data/warning_img"))
    raw_videos_dir = resolve_path(paths_cfg.get("raw_videos_dir", "data/warning_file"))
    labels_dir = resolve_path(args.output_dir)
    ensure_dir(labels_dir)

    if args.mock:
        print("mock mode: creating empty label files only.")
        for img_path in discover_media(raw_images_dir, IMAGE_EXTS):
            (labels_dir / f"{img_path.stem}.txt").write_text("", encoding="utf-8")
        return

    if YOLO is None:
        raise RuntimeError("ultralytics not installed. Please pip install ultralytics.")

    model_path = train_cfg.get("yolo_model", "yolov8n.pt")
    model = YOLO(model_path)

    image_paths = discover_media(raw_images_dir, IMAGE_EXTS)
    video_paths = discover_media(raw_videos_dir, VIDEO_EXTS)

    asset_map = {"db_path": db_path}
    run_on_images(model, image_paths, labels_dir, asset_map, model_path, args.confidence)
    run_on_videos(
        model, video_paths, asset_map, model_path, args.frame_step, args.confidence
    )

    print(f"labeled images: {len(image_paths)}, videos: {len(video_paths)}")


if __name__ == "__main__":
    main()

