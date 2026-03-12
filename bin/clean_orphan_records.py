"""
数据清洗脚本：删除缺失媒体文件的脏数据记录。

默认行为：
1. 扫描配置中的图片目录（默认 `data/warning_img`），获取实际存在的图片文件名集合
2. 从 SQLite 中删除没有对应原图的 assets + events 记录
3. 更新 assets.file_path 为本地实际路径
4. 从 LanceDB 中删除已被清理的 asset_id 对应的向量记录（重建表）

可选严格模式（适合演示）：
- 校验 video_path 对应视频是否存在
- 校验 img_icon_path 对应标注图是否存在
- 校验 img_src_path 对应原图序列是否存在

用法：
    python bin/clean_orphan_records.py --dry-run
    python bin/clean_orphan_records.py --strict-demo
    python bin/clean_orphan_records.py --require-video --require-icon --require-img-src
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from poc.pipeline.utils import load_yaml, resolve_path, connect_db

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".mpeg", ".mpg"}


def scan_disk_files(media_dir: Path, exts: set) -> set:
    """扫描磁盘上实际存在的媒体文件名。"""
    if not media_dir.exists():
        return set()
    return {f.name for f in media_dir.rglob("*") if f.is_file() and f.suffix.lower() in exts}


def _split_media_names(value: str) -> list[str]:
    parts = []
    for raw in str(value or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        parts.append(Path(raw).name)
    return parts


def _missing_required_media(names: list[str], disk_names: set) -> bool:
    if not names:
        return True
    return any(name not in disk_names for name in names)


def find_orphan_assets(
    db_path: str,
    disk_images: set,
    disk_videos: set,
    require_video: bool = False,
    require_icon: bool = False,
    require_img_src: bool = False,
):
    """找出数据库中缺失必需媒体文件的 asset 记录。"""
    conn = connect_db(db_path)
    orphans = []
    rows = conn.execute(
        """
        SELECT a.asset_id, a.file_name, a.file_path,
               e.video_path, e.img_icon_path, e.img_src_path
        FROM assets a
        LEFT JOIN events e ON e.asset_id = a.asset_id
        """
    ).fetchall()

    for row in rows:
        reasons = []
        image_names = _split_media_names(row["file_name"] or row["file_path"] or "")
        if _missing_required_media(image_names[:1], disk_images):
            reasons.append("image")

        if require_video:
            video_names = _split_media_names(row["video_path"])
            if _missing_required_media(video_names[:1], disk_videos):
                reasons.append("video")

        if require_icon:
            icon_names = _split_media_names(row["img_icon_path"])
            if _missing_required_media(icon_names, disk_images):
                reasons.append("icon")

        if require_img_src:
            img_src_names = _split_media_names(row["img_src_path"])
            if _missing_required_media(img_src_names, disk_images):
                reasons.append("img_src")

        if reasons:
            orphans.append(
                {
                    "asset_id": row["asset_id"],
                    "file_name": row["file_name"],
                    "reasons": reasons,
                }
            )
    conn.close()
    return orphans


def clean_sqlite(db_path: str, orphan_ids: list, img_dir: Path, dry_run: bool):
    """清理 SQLite 中的脏记录，并修复 file_path。"""
    conn = connect_db(db_path)
    current_total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]

    if not dry_run:
        conn.execute("BEGIN")
        for aid in orphan_ids:
            conn.execute("DELETE FROM events WHERE asset_id = ?", (aid,))
            conn.execute("DELETE FROM assets WHERE asset_id = ?", (aid,))
        conn.commit()
        print(f"  已删除 {len(orphan_ids)} 条脏记录（events + assets）")

        # 修复 file_path 为本地实际路径
        updated = 0
        for row in conn.execute("SELECT asset_id, file_name FROM assets").fetchall():
            matches = list(img_dir.rglob(row["file_name"]))
            if matches:
                fixed_path = matches[0].resolve()
                try:
                    stored_path = fixed_path.relative_to(ROOT.resolve()).as_posix()
                except ValueError:
                    stored_path = str(fixed_path)
                conn.execute("UPDATE assets SET file_path = ? WHERE asset_id = ?",
                             (stored_path, row["asset_id"]))
                updated += 1
        conn.commit()
        print(f"  已更新 {updated} 条 file_path 为本地路径")
    else:
        print(f"  [DRY-RUN] 将删除 {len(orphan_ids)} 条脏记录")

    # 统计
    remaining = current_total - len(orphan_ids) if dry_run else conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    print(f"  清理后 assets/events 剩余: {remaining} 条")
    conn.close()


def clean_lancedb(lancedb_dir: str, valid_ids: set, dry_run: bool):
    """清理 LanceDB 中的孤儿向量记录"""
    try:
        import lancedb
    except ImportError:
        print("  [SKIP] lancedb 未安装，跳过向量库清理")
        return

    db = lancedb.connect(lancedb_dir)
    try:
        table = db.open_table("embeddings")
    except Exception as e:
        print(f"  [SKIP] 无法打开 LanceDB embeddings 表: {e}")
        return

    df = table.to_pandas()
    before = len(df)
    lance_ids = set(df["asset_id"].tolist())
    orphan_lance = lance_ids - valid_ids
    keep_df = df[df["asset_id"].isin(valid_ids)]
    after = len(keep_df)

    print(f"  LanceDB 原有: {before} 条")
    print(f"  需要删除: {len(orphan_lance)} 条（SQLite 中已不存在）")
    print(f"  保留: {after} 条")

    if not dry_run and len(orphan_lance) > 0:
        # LanceDB 不支持行级删除，需要重建表
        db.drop_table("embeddings")
        if len(keep_df) > 0:
            db.create_table("embeddings", data=keep_df)
            print(f"  已重建 LanceDB embeddings 表（{after} 条）")

            # 重建索引
            new_table = db.open_table("embeddings")
            n = len(keep_df)
            if n >= 256:
                np_ = min(256, max(n // 4, 16))
                new_table.create_index(metric="cosine", num_partitions=np_, num_sub_vectors=64)
                print(f"  已重建向量索引（{np_} 分区）")
            else:
                print(f"  数据量较少（{n}条），跳过索引创建")
        else:
            print("  [WARNING] 清理后无数据，未重建表")
    elif dry_run:
        print(f"  [DRY-RUN] 将从 LanceDB 删除 {len(orphan_lance)} 条")


def main():
    parser = argparse.ArgumentParser(description="清洗缺失媒体文件的告警记录")
    parser.add_argument("--config", default="poc/config/poc.yaml", help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计不删除")
    parser.add_argument("--require-video", action="store_true", help="视频缺失也视为脏数据")
    parser.add_argument("--require-icon", action="store_true", help="标注图缺失也视为脏数据")
    parser.add_argument("--require-img-src", action="store_true", help="img_src_path 缺失也视为脏数据")
    parser.add_argument(
        "--strict-demo",
        action="store_true",
        help="演示严格模式：原图/视频/标注图/img_src 任一缺失都清洗",
    )
    args = parser.parse_args()

    if args.strict_demo:
        args.require_video = True
        args.require_icon = True
        args.require_img_src = True

    config = load_yaml(args.config)
    paths_cfg = config.get("paths", {})

    img_dir = resolve_path(paths_cfg.get("raw_images_dir", "data/warning_img"))
    video_dir = resolve_path(paths_cfg.get("raw_videos_dir", "data/warning_file"))
    db_path = resolve_path(paths_cfg.get("db_path", "data/metadata.db"))
    lancedb_dir = str(resolve_path(paths_cfg.get("lancedb_dir", "data/lancedb")))

    print("=" * 60)
    print("数据清洗：删除缺失媒体文件的告警记录")
    print("=" * 60)
    if args.dry_run:
        print(">>> DRY-RUN 模式：只统计不删除 <<<\n")
    active_rules = ["image"]
    if args.require_video:
        active_rules.append("video")
    if args.require_icon:
        active_rules.append("icon")
    if args.require_img_src:
        active_rules.append("img_src")
    print(f"校验规则: {', '.join(active_rules)}")

    # Step 1: 扫描磁盘媒体
    print(f"[1/3] 扫描图片目录: {img_dir}")
    disk_images = scan_disk_files(img_dir, IMAGE_EXTS)
    print(f"  磁盘图片文件数: {len(disk_images)}")
    if args.require_video:
        print(f"  扫描视频目录: {video_dir}")
        disk_videos = scan_disk_files(video_dir, VIDEO_EXTS)
        print(f"  磁盘视频文件数: {len(disk_videos)}")
    else:
        disk_videos = set()

    # Step 2: 找出孤儿记录
    print(f"\n[2/3] 检查 SQLite: {db_path}")
    orphans = find_orphan_assets(
        db_path,
        disk_images,
        disk_videos,
        require_video=args.require_video,
        require_icon=args.require_icon,
        require_img_src=args.require_img_src,
    )
    orphan_ids = [o["asset_id"] for o in orphans]
    print(f"  脏记录数: {len(orphans)}")
    reason_counter = Counter(reason for row in orphans for reason in row["reasons"])
    if reason_counter:
        print(f"  脏数据原因统计: {dict(reason_counter)}")
    if orphans:
        print("  示例:")
        for o in orphans[:5]:
            print(f"    {o['file_name']} | reasons={','.join(o['reasons'])}")
        if len(orphans) > 5:
            print(f"    ... 还有 {len(orphans) - 5} 条")

    # Step 3: 清理
    if orphans:
        clean_sqlite(db_path, orphan_ids, img_dir, args.dry_run)
    else:
        print("  无需清理，所有记录都满足当前校验规则")

    # Step 4: 清理 LanceDB
    print(f"\n[3/3] 检查 LanceDB: {lancedb_dir}")
    conn = connect_db(db_path)
    valid_ids = set(r[0] for r in conn.execute("SELECT asset_id FROM assets").fetchall())
    conn.close()
    clean_lancedb(lancedb_dir, valid_ids, args.dry_run)

    print("\n" + "=" * 60)
    if args.dry_run:
        print("DRY-RUN 完成。确认无误后去掉 --dry-run 参数重新执行。")
    else:
        print("清洗完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()

