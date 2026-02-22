"""
数据迁移脚本 — 将 SQLite 元数据合并到 LanceDB embeddings 表

从现有的 LanceDB（只有 asset_id/file_path/file_name/vector）和 SQLite（events/assets）
合并生成丰富化的 Lance 表，包含所有结构化字段 + 向量。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.pipeline.utils import connect_db, resolve_path, load_yaml


def migrate():
    config = load_yaml("poc/config/poc.yaml")
    paths_cfg = config.get("paths", {})

    db_path = resolve_path(paths_cfg.get("db_path", "poc/data/metadata.db"))
    lancedb_dir = resolve_path(paths_cfg.get("lancedb_dir", "poc/data/lancedb"))

    print(f"SQLite: {db_path}")
    print(f"LanceDB: {lancedb_dir}")

    # 1. 读取现有 LanceDB 向量（用 Arrow 避免 pandas 依赖）
    import lancedb
    lance_db = lancedb.connect(str(lancedb_dir))
    old_table = lance_db.open_table("embeddings")
    arrow_table = old_table.to_arrow()
    print(f"现有 Lance 记录: {arrow_table.num_rows}")
    print(f"现有 Lance 列: {arrow_table.column_names}")

    # 提取 asset_id -> vector 映射
    asset_ids = arrow_table.column("asset_id").to_pylist()
    file_paths = arrow_table.column("file_path").to_pylist()
    file_names = arrow_table.column("file_name").to_pylist()
    vectors = arrow_table.column("vector").to_pylist()
    old_data = {}
    for i in range(len(asset_ids)):
        old_data[asset_ids[i]] = {
            "file_path": file_paths[i],
            "file_name": file_names[i],
            "vector": vectors[i],
        }

    # 2. 读取 SQLite 元数据
    conn = connect_db(db_path)
    meta_rows = {}
    for row in conn.execute("""
        SELECT a.asset_id, a.file_path, a.file_name, a.media_type, a.captured_at,
               a.lat AS asset_lat, a.lon AS asset_lon, a.source,
               e.event_id, e.event_type, e.alarm_level, e.alarm_source, e.alarm_time,
               e.lat, e.lon, e.region, e.extra_json, e.summary, e.description,
               e.address, e.device_name, e.confidence_level,
               e.province_name, e.city_name, e.county_name,
               e.town_code, e.town_name, e.device_code,
               e.channel_code, e.channel_name,
               e.warning_order_id, e.warning_type_id, e.alarm_body,
               e.algorithm_code, e.algorithm_name,
               e.emergency_level, e.importance_level, e.order_status,
               e.confidence_level_max, e.tenant_name,
               e.video_path, e.img_src_path, e.img_icon_path
        FROM assets a
        LEFT JOIN events e ON a.asset_id = e.asset_id
    """).fetchall():
        meta_rows[row["asset_id"]] = dict(row)
    conn.close()
    print(f"SQLite 元数据: {len(meta_rows)} 条")

    # 3. 合并：向量 + 元数据
    lance_data = []
    matched = 0
    unmatched = 0
    for aid, vec_info in old_data.items():
        meta = meta_rows.get(aid)
        if not meta:
            unmatched += 1
            continue
        matched += 1
        m = meta
        vec = vec_info["vector"]
        lance_data.append({
            "asset_id": aid,
            "file_path": vec_info["file_path"],
            "file_name": vec_info.get("file_name") or m.get("file_name") or "",
            "vector": list(vec) if not isinstance(vec, list) else vec,
            "media_type": m.get("media_type") or "",
            "captured_at": m.get("captured_at") or "",
            "source": m.get("source") or "",
            "event_id": m.get("event_id") or "",
            "event_type": m.get("event_type") or "",
            "alarm_level": m.get("alarm_level") or "",
            "alarm_source": m.get("alarm_source") or "",
            "alarm_time": m.get("alarm_time") or "",
            "lat": float(m.get("lat") or 0),
            "lon": float(m.get("lon") or 0),
            "region": m.get("region") or "",
            "extra_json": m.get("extra_json") or "",
            "summary": m.get("summary") or "",
            "description": m.get("description") or "",
            "address": m.get("address") or "",
            "device_name": m.get("device_name") or "",
            "confidence_level": float(m.get("confidence_level") or 0),
            "province_name": m.get("province_name") or "",
            "city_name": m.get("city_name") or "",
            "county_name": m.get("county_name") or "",
            "town_code": m.get("town_code") or "",
            "town_name": m.get("town_name") or "",
            "device_code": m.get("device_code") or "",
            "channel_code": m.get("channel_code") or "",
            "channel_name": m.get("channel_name") or "",
            "warning_order_id": m.get("warning_order_id") or "",
            "warning_type_id": m.get("warning_type_id") or "",
            "alarm_body": m.get("alarm_body") or "",
            "algorithm_code": m.get("algorithm_code") or "",
            "algorithm_name": m.get("algorithm_name") or "",
            "emergency_level": m.get("emergency_level") or "",
            "importance_level": m.get("importance_level") or "",
            "order_status": m.get("order_status") or "",
            "confidence_level_max": float(m.get("confidence_level_max") or 0),
            "tenant_name": m.get("tenant_name") or "",
            "video_path": m.get("video_path") or "",
            "img_src_path": m.get("img_src_path") or "",
            "img_icon_path": m.get("img_icon_path") or "",
        })

    print(f"匹配: {matched}, 未匹配: {unmatched}")

    # 4. 重建 Lance 表
    if not lance_data:
        print("[FAIL] 无数据可写入")
        return

    print(f"写入 {len(lance_data)} 条丰富化记录到 LanceDB...")
    tables = lance_db.table_names() if hasattr(lance_db, 'table_names') else lance_db.list_tables()
    if "embeddings" in [str(t) for t in tables]:
        lance_db.drop_table("embeddings")
    table = lance_db.create_table("embeddings", data=lance_data)

    # 创建向量索引
    n = len(lance_data)
    if n >= 256:
        np_ = min(256, n)
        print(f"创建向量索引（{np_}分区）...")
        table.create_index(metric="cosine", num_partitions=np_, num_sub_vectors=64)
    else:
        print(f"数据量较少（{n}条），跳过索引创建")

    print(f"[OK] 迁移完成！{len(lance_data)} 条记录")
    print(f"  新表列数: {len(table.schema)}")
    print(f"  新表列名: {table.schema.names}")


if __name__ == "__main__":
    migrate()
