"""
Daft on Ray 批量数据管线
替代 embed.py 的 for 循环处理，用 Daft DataFrame 实现 TB 级图片批量入库。

用法:
    python -m poc.pipeline.daft_pipeline --config poc/config/poc.yaml --image-dir data/warning_img
"""
import argparse
import time
from pathlib import Path
from typing import List

import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def discover_images(dir_path: Path) -> List[str]:
    if not dir_path.exists():
        return []
    return [str(p) for p in dir_path.rglob("*") if p.suffix.lower() in IMAGE_EXTS]


def run_batch_ingest(config: dict, image_dir: str):
    """TB 级图片批量入库管线（Daft on Ray）"""
    import ray
    import daft

    if not ray.is_initialized():
        from poc.infra.ray_init import init_ray
        init_ray(config)

    # 配置 Daft 使用 Ray runner
    daft.context.set_runner_ray()

    paths_cfg = config.get("paths", {})
    from poc.pipeline.utils import resolve_path, connect_db

    raw_images_dir = resolve_path(image_dir)
    db_path = resolve_path(paths_cfg.get("db_path", "data/metadata.db"))
    lancedb_dir = resolve_path(paths_cfg.get("lancedb_dir", "data/lancedb"))
    lancedb_dir.mkdir(parents=True, exist_ok=True)

    # 发现图片
    image_paths = discover_images(raw_images_dir)
    if not image_paths:
        print(f"[DaftPipeline] 未发现图片: {raw_images_dir}")
        return
    print(f"[DaftPipeline] 发现 {len(image_paths)} 张图片")

    # 构建 Daft DataFrame
    df = daft.from_pydict({"path": image_paths})

    # ── UDF: YOLO 检测 ──────────────────────────────────────────────────
    @daft.udf(return_dtype=daft.DataType.python())
    def yolo_detect(paths):
        actor = ray.get_actor("yolo_detector")
        futures = [actor.detect_image.remote(p) for p in paths.to_pylist()]
        return ray.get(futures)

    # ── UDF: VL 场景描述 ────────────────────────────────────────────────
    @daft.udf(return_dtype=daft.DataType.string())
    def vl_describe(paths):
        actor = ray.get_actor("vl_analyzer")
        futures = [actor.describe_image.remote(p) for p in paths.to_pylist()]
        return ray.get(futures)

    # ── UDF: Embedding 编码 ─────────────────────────────────────────────
    @daft.udf(return_dtype=daft.DataType.python())
    def embed(paths):
        actor = ray.get_actor("embedding")
        return ray.get(actor.encode_batch.remote(paths.to_pylist()))

    # ── 链式执行 ────────────────────────────────────────────────────────
    print("[DaftPipeline] 开始执行管线: YOLO检测 → VL描述 → Embedding")
    start_time = time.time()

    df = df.with_column("detections", yolo_detect(df["path"]))
    df = df.with_column("description", vl_describe(df["path"]))
    df = df.with_column("embedding", embed(df["path"]))

    # 收集结果
    results = df.collect()
    elapsed = time.time() - start_time
    n_rows = len(results)
    print(f"[DaftPipeline] 管线执行完成: {n_rows} 条, 耗时 {elapsed:.1f}s")

    # ── 写入 SQLite detections ──────────────────────────────────────────
    paths_list = results.get_column("path").to_pylist()
    detections_list = results.get_column("detections").to_pylist()
    descriptions_list = results.get_column("description").to_pylist()
    embeddings_list = results.get_column("embedding").to_pylist()

    conn = connect_db(db_path)
    # 获取 asset 映射
    assets_data = {}
    assets_by_filename = {}
    for row in conn.execute("SELECT asset_id, file_path, file_name FROM assets").fetchall():
        row_dict = dict(row)
        assets_data[row["file_path"]] = row_dict
        if row["file_name"]:
            assets_by_filename[row["file_name"]] = row_dict

    # 准备 LanceDB 数据
    import lancedb
    lance_data = []
    matched = 0

    for i, path in enumerate(paths_list):
        asset_info = assets_data.get(str(path))
        if not asset_info:
            asset_info = assets_by_filename.get(Path(path).name)
        if not asset_info:
            continue

        matched += 1
        vec = embeddings_list[i]
        if isinstance(vec, np.ndarray):
            vec = vec.tolist()

        lance_data.append({
            "asset_id": asset_info["asset_id"],
            "file_path": str(path),
            "file_name": asset_info["file_name"],
            "vector": vec,
        })

    conn.close()

    # ── 写入 LanceDB ───────────────────────────────────────────────────
    if lance_data:
        db = lancedb.connect(str(lancedb_dir))
        table_name = "embeddings"
        try:
            existing = db.table_names()
        except AttributeError:
            existing = db.list_tables()
        if table_name in existing:
            db.drop_table(table_name)

        table = db.create_table(table_name, data=lance_data)

        n = len(lance_data)
        if n >= 1000:
            np_ = min(256, n)
            table.create_index(metric="cosine", num_partitions=np_, num_sub_vectors=64)
        elif n >= 256:
            np_ = max(n // 4, 16)
            table.create_index(metric="cosine", num_partitions=np_, num_sub_vectors=64)

        print(f"[DaftPipeline] LanceDB 写入完成: {n} 条记录")
    else:
        print("[DaftPipeline] 无匹配数据，跳过 LanceDB 写入")

    print(f"[DaftPipeline] 完成! 匹配 {matched}/{n_rows} 条")


def main():
    parser = argparse.ArgumentParser(description="Daft on Ray 批量入库管线")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    parser.add_argument("--image-dir", default="data/warning_img")
    args = parser.parse_args()

    from poc.pipeline.utils import load_yaml
    config = load_yaml(args.config)

    # 初始化 Ray + 创建 Actor
    from poc.infra.ray_init import init_ray, create_actors
    if init_ray(config):
        create_actors(config)
        run_batch_ingest(config, args.image_dir)
    else:
        print("[DaftPipeline] Ray 初始化失败，请检查配置")


if __name__ == "__main__":
    main()

