"""
数据清洗脚本：删除没有对应图片的告警记录

功能：
1. 扫描 warning_img 目录，获取实际存在的图片文件名集合
2. 从 SQLite 中删除 file_name 不在图片集合中的 assets + events 记录
3. 更新 assets.file_path 为本地实际路径
4. 从 LanceDB 中删除已被清理的 asset_id 对应的向量记录（重建表）

用法：
    python scripts/clean_orphan_records.py [--config poc/config/poc.yaml] [--dry-run]

    --dry-run  只统计不删除，先看看影响范围
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from poc.pipeline.utils import load_yaml, resolve_path, connect_db

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def scan_disk_images(img_dir: Path) -> set:
    """扫描磁盘上实际存在的图片文件名"""
    return {f.name for f in img_dir.rglob("*") if f.suffix.lower() in IMAGE_EXTS}


def find_orphan_assets(db_path: str, disk_names: set):
    """找出数据库中没有对应图片的 asset 记录"""
    conn = connect_db(db_path)
    orphans = []
    for row in conn.execute("SELECT asset_id, file_name FROM assets WHERE file_name IS NOT NULL").fetchall():
        if row["file_name"] not in disk_names:
            orphans.append({"asset_id": row["asset_id"], "file_name": row["file_name"]})
    conn.close()
    return orphans


def clean_sqlite(db_path: str, orphan_ids: list, img_dir: Path, dry_run: bool):
    """清理 SQLite 中的孤儿记录，并修复 file_path"""
    conn = connect_db(db_path)

    if not dry_run:
        conn.execute("BEGIN")
        for aid in orphan_ids:
            conn.execute("DELETE FROM events WHERE asset_id = ?", (aid,))
            conn.execute("DELETE FROM assets WHERE asset_id = ?", (aid,))
        conn.commit()
        print(f"  已删除 {len(orphan_ids)} 条无图片记录（events + assets）")

        # 修复 file_path 为本地实际路径
        updated = 0
        for row in conn.execute("SELECT asset_id, file_name FROM assets").fetchall():
            matches = list(img_dir.rglob(row["file_name"]))
            if matches:
                conn.execute("UPDATE assets SET file_path = ? WHERE asset_id = ?",
                             (str(matches[0]), row["asset_id"]))
                updated += 1
        conn.commit()
        print(f"  已更新 {updated} 条 file_path 为本地路径")
    else:
        print(f"  [DRY-RUN] 将删除 {len(orphan_ids)} 条无图片记录")

    # 统计
    remaining = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
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
            db.create_table("embeddings", data=keep_df.to_dict("list"))
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
    parser = argparse.ArgumentParser(description="清洗无图片的告警记录")
    parser.add_argument("--config", default="poc/config/poc.yaml", help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计不删除")
    args = parser.parse_args()

    config = load_yaml(args.config)
    paths_cfg = config.get("paths", {})

    img_dir = resolve_path(paths_cfg.get("raw_images_dir", "warning_img"))
    db_path = resolve_path(paths_cfg.get("db_path", "poc/data/metadata.db"))
    lancedb_dir = str(resolve_path(paths_cfg.get("lancedb_dir", "poc/data/lancedb")))

    print("=" * 60)
    print("数据清洗：删除没有对应图片的告警记录")
    print("=" * 60)
    if args.dry_run:
        print(">>> DRY-RUN 模式：只统计不删除 <<<\n")

    # Step 1: 扫描磁盘图片
    print(f"[1/3] 扫描图片目录: {img_dir}")
    disk_names = scan_disk_images(img_dir)
    print(f"  磁盘图片文件数: {len(disk_names)}")

    # Step 2: 找出孤儿记录
    print(f"\n[2/3] 检查 SQLite: {db_path}")
    orphans = find_orphan_assets(db_path, disk_names)
    orphan_ids = [o["asset_id"] for o in orphans]
    print(f"  无图片的记录数: {len(orphans)}")
    if orphans:
        print("  示例:")
        for o in orphans[:5]:
            print(f"    {o['file_name']}")
        if len(orphans) > 5:
            print(f"    ... 还有 {len(orphans) - 5} 条")

    # Step 3: 清理
    if orphans:
        clean_sqlite(db_path, orphan_ids, img_dir, args.dry_run)
    else:
        print("  无需清理，所有记录都有对应图片")

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
