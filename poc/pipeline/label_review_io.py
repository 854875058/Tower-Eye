import argparse
import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from .utils import connect_db, load_yaml, resolve_path


def export_review_manifest(db_path: Path, output_path: Path, limit: int = 0) -> None:
    conn = connect_db(db_path)
    assets = conn.execute(
        """
        SELECT asset_id, media_type, file_path, file_name, lat, lon, captured_at
        FROM assets
        """
    ).fetchall()
    if limit > 0:
        assets = assets[:limit]

    asset_ids = [row["asset_id"] for row in assets]
    detections = defaultdict(list)
    if asset_ids:
        placeholders = ",".join(["?"] * len(asset_ids))
        rows = conn.execute(
            f"""
            SELECT asset_id, label, confidence, bbox_x, bbox_y, bbox_w, bbox_h, frame_index, timestamp_sec
            FROM detections
            WHERE asset_id IN ({placeholders})
            """,
            asset_ids,
        ).fetchall()
        for row in rows:
            detections[row["asset_id"]].append(
                {
                    "label": row["label"],
                    "confidence": row["confidence"],
                    "bbox": [row["bbox_x"], row["bbox_y"], row["bbox_w"], row["bbox_h"]],
                    "frame_index": row["frame_index"],
                    "timestamp_sec": row["timestamp_sec"],
                }
            )

    with output_path.open("w", encoding="utf-8") as f:
        for row in assets:
            record = {
                "asset_id": row["asset_id"],
                "media_type": row["media_type"],
                "file_path": row["file_path"],
                "file_name": row["file_name"],
                "lat": row["lat"],
                "lon": row["lon"],
                "captured_at": row["captured_at"],
                "predictions": detections.get(row["asset_id"], []),
            }
            f.write(json.dumps(record, ensure_ascii=True) + "\n")

    conn.close()


def import_review_manifest(
    db_path: Path, input_path: Path, reviewer: str, origin: str
) -> None:
    conn = connect_db(db_path)
    rows: List[Dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            asset_id = record.get("asset_id")
            annotations = record.get("annotations") or []
            for ann in annotations:
                bbox = ann.get("bbox") or [None, None, None, None]
                rows.append(
                    {
                        "annotation_id": uuid.uuid4().hex,
                        "asset_id": asset_id,
                        "label": ann.get("label"),
                        "bbox_x": bbox[0],
                        "bbox_y": bbox[1],
                        "bbox_w": bbox[2],
                        "bbox_h": bbox[3],
                        "origin": origin,
                        "reviewer": reviewer,
                    }
                )

    conn.executemany(
        """
        INSERT OR REPLACE INTO annotations (
            annotation_id, asset_id, label, bbox_x, bbox_y, bbox_w, bbox_h,
            origin, reviewer, reviewed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        [
            (
                row["annotation_id"],
                row["asset_id"],
                row["label"],
                row["bbox_x"],
                row["bbox_y"],
                row["bbox_w"],
                row["bbox_h"],
                row["origin"],
                row["reviewer"],
            )
            for row in rows
        ],
    )
    conn.commit()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="POC label review import/export")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--import-file")
    parser.add_argument("--output", default="data/review/review_tasks.jsonl")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--reviewer", default="reviewer")
    parser.add_argument("--origin", default="review")
    args = parser.parse_args()

    config = load_yaml(args.config)
    db_path = resolve_path(config.get("paths", {}).get("db_path", "data/metadata.db"))

    if args.export:
        output_path = resolve_path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        export_review_manifest(db_path, output_path, args.limit)
        print(f"exported: {output_path}")
        return

    if args.import_file:
        input_path = resolve_path(args.import_file)
        import_review_manifest(db_path, input_path, args.reviewer, args.origin)
        print(f"imported: {input_path}")
        return

    raise SystemExit("Specify --export or --import-file")


if __name__ == "__main__":
    main()

