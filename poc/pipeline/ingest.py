import argparse
import csv
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .utils import (
    coerce_float,
    coerce_str,
    connect_db,
    init_db,
    json_dumps,
    load_yaml,
    normalize_row_keys,
    pick_first,
    resolve_path,
    sha256_file,
)

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Image = None

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}


def discover_media(dir_path: Path, exts: Iterable[str]) -> List[Path]:
    if not dir_path.exists():
        return []
    return [p for p in dir_path.rglob("*") if p.suffix.lower() in exts]


def image_size(path: Path) -> Tuple[Optional[int], Optional[int]]:
    if Image is None:
        return None, None
    try:
        with Image.open(path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def video_duration(path: Path) -> Optional[float]:
    if cv2 is None:
        return None
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps and frames:
            return float(frames / fps)
    finally:
        cap.release()
    return None


def asset_id_from_path(path: Path, strategy: str) -> str:
    if strategy == "sha256":
        return sha256_file(path)
    if strategy == "filename":
        return path.stem
    return uuid.uuid4().hex


def build_asset_rows(
    paths: List[Path], media_type: str, strategy: str
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in paths:
        asset_id = asset_id_from_path(path, strategy)
        width, height = (None, None)
        duration = None
        if media_type == "image":
            width, height = image_size(path)
        else:
            duration = video_duration(path)
        rows.append(
            {
                "asset_id": asset_id,
                "media_type": media_type,
                "file_path": str(path),
                "file_name": path.name,
                "sha256": sha256_file(path) if strategy != "sha256" else asset_id,
                "width": width,
                "height": height,
                "duration_sec": duration,
                "captured_at": None,
                "lat": None,
                "lon": None,
                "source": None,
            }
        )
    return rows


def read_structured_file(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [normalize_row_keys(row) for row in reader]
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [normalize_row_keys(row) for row in data]
        if isinstance(data, dict):
            records = data.get("records") or data.get("data") or []
            if isinstance(records, list):
                return [normalize_row_keys(row) for row in records]
    return []


def build_event_rows(
    records: List[Dict[str, Any]], file_name_to_id: Dict[str, str]
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records:
        asset_id = pick_first(
            record, ["asset_id", "assetid", "media_id", "file_id"]
        )
        if not asset_id:
            file_name = pick_first(record, ["file_name", "filename", "file"])
            if file_name:
                asset_id = file_name_to_id.get(str(file_name))
        event_id = pick_first(record, ["event_id", "alarm_id", "id"]) or uuid.uuid4().hex
        event_type = pick_first(record, ["event_type", "scene", "alarm_type", "type"])
        alarm_time = pick_first(record, ["alarm_time", "event_time", "time"])
        lat = coerce_float(pick_first(record, ["lat", "latitude"]))
        lon = coerce_float(pick_first(record, ["lon", "longitude"]))
        rows.append(
            {
                "event_id": coerce_str(event_id),
                "asset_id": coerce_str(asset_id),
                "event_type": coerce_str(event_type) or "unknown",
                "alarm_level": coerce_str(pick_first(record, ["alarm_level", "level"])),
                "alarm_source": coerce_str(pick_first(record, ["alarm_source", "source"])),
                "alarm_time": coerce_str(alarm_time),
                "lat": lat,
                "lon": lon,
                "region": coerce_str(pick_first(record, ["region", "area"])),
                "extra_json": json_dumps(record),
            }
        )
    return rows


def insert_assets(conn, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR IGNORE INTO assets (
            asset_id, media_type, file_path, file_name, sha256, width, height,
            duration_sec, captured_at, lat, lon, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["asset_id"],
                row["media_type"],
                row["file_path"],
                row["file_name"],
                row["sha256"],
                row["width"],
                row["height"],
                row["duration_sec"],
                row["captured_at"],
                row["lat"],
                row["lon"],
                row["source"],
            )
            for row in rows
        ],
    )


def insert_events(conn, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO events (
            event_id, asset_id, event_type, alarm_level, alarm_source, alarm_time,
            lat, lon, region, extra_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["event_id"],
                row["asset_id"],
                row["event_type"],
                row["alarm_level"],
                row["alarm_source"],
                row["alarm_time"],
                row["lat"],
                row["lon"],
                row["region"],
                row["extra_json"],
            )
            for row in rows
        ],
    )


def update_asset_location_from_events(conn) -> None:
    conn.execute(
        """
        UPDATE assets
        SET lat = COALESCE(lat, (
            SELECT lat FROM events WHERE events.asset_id = assets.asset_id AND lat IS NOT NULL LIMIT 1
        )),
            lon = COALESCE(lon, (
            SELECT lon FROM events WHERE events.asset_id = assets.asset_id AND lon IS NOT NULL LIMIT 1
        ))
        WHERE asset_id IN (SELECT DISTINCT asset_id FROM events WHERE asset_id IS NOT NULL)
        """
    )


def load_structured_records(structured_dir: Path, file_names: List[str]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for name in file_names:
        path = structured_dir / name
        records.extend(read_structured_file(path))
    return records


def build_file_name_map(conn) -> Dict[str, str]:
    cursor = conn.execute("SELECT asset_id, file_name FROM assets")
    return {row["file_name"]: row["asset_id"] for row in cursor if row["file_name"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="POC ingestion pipeline")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_yaml(args.config)
    paths_cfg = config.get("paths", {})
    ingest_cfg = config.get("ingest", {})

    db_path = resolve_path(paths_cfg.get("db_path", "data/metadata.db"))
    schema_path = resolve_path(paths_cfg.get("schema_path", "poc/schema/metadata.sql"))
    init_db(db_path, schema_path)

    raw_images_dir = resolve_path(paths_cfg.get("raw_images_dir", "data/warning_img"))
    raw_videos_dir = resolve_path(paths_cfg.get("raw_videos_dir", "data/warning_file"))
    structured_dir = resolve_path(paths_cfg.get("structured_dir", "data/structured"))

    strategy = ingest_cfg.get("asset_id_strategy", "sha256")
    images = discover_media(raw_images_dir, IMAGE_EXTS)
    videos = discover_media(raw_videos_dir, VIDEO_EXTS)

    asset_rows = build_asset_rows(images, "image", strategy) + build_asset_rows(
        videos, "video", strategy
    )

    structured_files = ingest_cfg.get("structured_files", [])
    structured_records = load_structured_records(structured_dir, structured_files)

    conn = connect_db(db_path)
    insert_assets(conn, asset_rows)
    file_name_to_id = build_file_name_map(conn)
    event_rows = build_event_rows(structured_records, file_name_to_id)
    insert_events(conn, event_rows)
    update_asset_location_from_events(conn)
    if args.dry_run:
        conn.rollback()
    else:
        conn.commit()
    conn.close()

    print(f"assets: {len(asset_rows)}, events: {len(event_rows)}")


if __name__ == "__main__":
    main()

