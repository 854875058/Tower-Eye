import argparse
import math
import random
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .utils import connect_db, load_yaml, resolve_path


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def haversine_km(lat1, lon1, lat2, lon2) -> Optional[float]:
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_assets(conn) -> List[dict]:
    rows = conn.execute(
        """
        SELECT asset_id, file_path, file_name, lat, lon, captured_at, media_type
        FROM assets
        """
    ).fetchall()
    return [dict(row) for row in rows]


def load_labels(conn) -> Dict[str, List[dict]]:
    labels = {}
    ann_rows = conn.execute(
        "SELECT asset_id, label, bbox_x, bbox_y, bbox_w, bbox_h FROM annotations"
    ).fetchall()
    if ann_rows:
        for row in ann_rows:
            labels.setdefault(row["asset_id"], []).append(
                {
                    "label": row["label"],
                    "bbox": [row["bbox_x"], row["bbox_y"], row["bbox_w"], row["bbox_h"]],
                }
            )
        return labels

    det_rows = conn.execute(
        "SELECT asset_id, label, bbox_x, bbox_y, bbox_w, bbox_h FROM detections"
    ).fetchall()
    for row in det_rows:
        labels.setdefault(row["asset_id"], []).append(
            {
                "label": row["label"],
                "bbox": [row["bbox_x"], row["bbox_y"], row["bbox_w"], row["bbox_h"]],
            }
        )
    return labels


def split_assets(
    positive_ids: List[str], val_ratio: float, seed: int
) -> Tuple[List[str], List[str]]:
    rng = random.Random(seed)
    ids = positive_ids[:]
    rng.shuffle(ids)
    val_count = max(1, int(len(ids) * val_ratio)) if ids else 0
    return ids[val_count:], ids[:val_count]


def pick_negatives(
    assets: List[dict],
    positive_ids: List[str],
    ratio: float,
    min_km: float,
    min_hours: float,
    seed: int,
) -> List[dict]:
    rng = random.Random(seed)
    positives = {asset["asset_id"]: asset for asset in assets if asset["asset_id"] in positive_ids}
    candidates = [a for a in assets if a["asset_id"] not in positives]
    rng.shuffle(candidates)

    negatives = []
    target = int(len(positive_ids) * ratio)
    for cand in candidates:
        if len(negatives) >= target:
            break
        ok = False
        for pos in positives.values():
            distance = haversine_km(
                cand.get("lat"), cand.get("lon"), pos.get("lat"), pos.get("lon")
            )
            if distance is not None and distance < min_km:
                continue
            t1 = parse_time(cand.get("captured_at"))
            t2 = parse_time(pos.get("captured_at"))
            if t1 and t2:
                hours = abs((t1 - t2).total_seconds()) / 3600.0
                if hours < min_hours:
                    continue
            ok = True
            break
        if ok:
            negatives.append(cand)
    return negatives


def write_label_file(path: Path, label_items: List[dict], label_map: Dict[str, int]) -> None:
    if not label_items:
        path.write_text("", encoding="utf-8")
        return
    lines = []
    for item in label_items:
        label = item["label"]
        if label not in label_map:
            continue
        x, y, w, h = item["bbox"]
        lines.append(f"{label_map[label]} {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
    path.write_text("\n".join(lines), encoding="utf-8")


def copy_asset(asset: dict, dst_dir: Path) -> Optional[Path]:
    src = Path(asset["file_path"])
    if not src.exists() or src.suffix.lower() not in IMAGE_EXTS:
        return None
    dst = dst_dir / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def build_dataset(output_dir: Path, assets: List[dict], labels: Dict[str, List[dict]],
                  val_ratio: float, negative_ratio: float, min_km: float, min_hours: float, seed: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    images_train = output_dir / "images/train"
    images_val = output_dir / "images/val"
    labels_train = output_dir / "labels/train"
    labels_val = output_dir / "labels/val"
    for dir_path in [images_train, images_val, labels_train, labels_val]:
        dir_path.mkdir(parents=True, exist_ok=True)

    positive_ids = [asset_id for asset_id in labels.keys()]
    train_ids, val_ids = split_assets(positive_ids, val_ratio, seed)

    label_names = sorted({item["label"] for items in labels.values() for item in items if item["label"]})
    label_map = {name: idx for idx, name in enumerate(label_names)}

    negatives = pick_negatives(assets, positive_ids, negative_ratio, min_km, min_hours, seed)

    def write_split(ids: List[str], images_dir: Path, labels_dir: Path):
        for asset_id in ids:
            asset = next((a for a in assets if a["asset_id"] == asset_id), None)
            if not asset:
                continue
            copied = copy_asset(asset, images_dir)
            if not copied:
                continue
            label_path = labels_dir / f"{copied.stem}.txt"
            write_label_file(label_path, labels.get(asset_id, []), label_map)

    def write_negatives(items: List[dict], images_dir: Path, labels_dir: Path):
        for asset in items:
            copied = copy_asset(asset, images_dir)
            if not copied:
                continue
            label_path = labels_dir / f"{copied.stem}.txt"
            label_path.write_text("", encoding="utf-8")

    write_split(train_ids, images_train, labels_train)
    write_split(val_ids, images_val, labels_val)

    neg_train, neg_val = split_assets(
        [a["asset_id"] for a in negatives], val_ratio, seed
    )
    neg_train_assets = [a for a in negatives if a["asset_id"] in neg_train]
    neg_val_assets = [a for a in negatives if a["asset_id"] in neg_val]

    write_negatives(neg_train_assets, images_train, labels_train)
    write_negatives(neg_val_assets, images_val, labels_val)

    dataset_yaml = output_dir / "dataset.yaml"
    dataset_yaml.write_text(
        "\n".join(
            [
                f"path: {output_dir}",
                "train: images/train",
                "val: images/val",
                "names:",
            ]
            + [f"  {idx}: {name}" for name, idx in label_map.items()]
        ),
        encoding="utf-8",
    )
    return dataset_yaml


def main() -> None:
    parser = argparse.ArgumentParser(description="POC dataset builder")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    parser.add_argument("--output-dir", default="data/datasets/yolo")
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--negative-ratio", type=float, default=0.5)
    parser.add_argument("--min-km", type=float, default=2.0)
    parser.add_argument("--min-hours", type=float, default=6.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    config = load_yaml(args.config)
    db_path = resolve_path(config.get("paths", {}).get("db_path", "data/metadata.db"))

    conn = connect_db(db_path)
    assets = load_assets(conn)
    labels = load_labels(conn)
    conn.close()

    dataset_yaml = build_dataset(
        resolve_path(args.output_dir),
        assets,
        labels,
        args.val_ratio,
        args.negative_ratio,
        args.min_km,
        args.min_hours,
        args.seed,
    )
    print(f"dataset ready: {dataset_yaml}")


if __name__ == "__main__":
    main()

