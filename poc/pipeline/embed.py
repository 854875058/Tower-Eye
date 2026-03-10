import argparse
from pathlib import Path
from typing import List, Optional

from .utils import connect_db, load_yaml, resolve_path

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    np = None

try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Image = None

try:
    import lancedb  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    lancedb = None

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def discover_images(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return [p for p in dir_path.rglob("*") if p.suffix.lower() in IMAGE_EXTS]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def auto_detect_batch_size() -> int:
    """
    根据GPU显存自动检测最优批处理大小

    Returns:
        推荐的批处理大小
    """
    try:
        import torch
        if not torch.cuda.is_available():
            return 16  # CPU模式使用较小批处理

        # 获取GPU显存（GB）
        gpu_memory_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3

        # 根据显存推荐批处理大小
        if gpu_memory_gb < 8:
            return 16
        elif gpu_memory_gb < 12:
            return 32
        elif gpu_memory_gb < 16:
            return 48
        elif gpu_memory_gb < 24:
            return 64
        else:
            return 128  # 24GB+显存
    except Exception:
        return 32  # 默认值


def load_model(model_name: str, cache_dir: Optional[str] = None, hf_mirror: Optional[str] = None):
    """
    加载CLIP模型，支持设置缓存目录和镜像源

    Args:
        model_name: 模型名称
        cache_dir: 模型缓存目录
        hf_mirror: HuggingFace镜像源URL
    """
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        import torch  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "sentence-transformers not installed. Please pip install sentence-transformers."
        ) from exc

    # 设置HuggingFace镜像源（国内加速）
    if hf_mirror:
        import os
        os.environ['HF_ENDPOINT'] = hf_mirror
        os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir if cache_dir else os.path.expanduser('~/.cache/huggingface')
        print(f"使用HuggingFace镜像源: {hf_mirror}")

    # 检测GPU
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"使用设备: {device}")
    if device == 'cuda':
        print(f"GPU型号: {torch.cuda.get_device_name(0)}")
        print(f"GPU显存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")

    # 加载模型
    print(f"正在加载模型: {model_name}")
    if cache_dir:
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        model = SentenceTransformer(model_name, cache_folder=str(cache_path), device=device)
    else:
        model = SentenceTransformer(model_name, device=device)

    # 获取向量维度（通过实际编码获取）
    try:
        dims = model.get_sentence_embedding_dimension()
        if dims is None:
            # 如果返回 None，通过编码一个测试样本获取维度
            test_vec = model.encode("test", convert_to_numpy=True)
            dims = test_vec.shape[0]
    except:
        # 备用方案：编码测试样本
        test_vec = model.encode("test", convert_to_numpy=True)
        dims = test_vec.shape[0]

    print(f"模型加载成功！维度: {dims}")
    return model


def embed_images(model, images: List[Path], batch_size: int = 32) -> List[tuple]:
    """
    批量生成图像向量嵌入（支持GPU加速）

    Args:
        model: SentenceTransformer模型
        images: 图片路径列表
        batch_size: 批量大小（GPU时可以设置更大）

    Returns:
        (图片路径, 向量) 的列表
    """
    if Image is None or np is None:
        raise RuntimeError("Pillow and numpy required for embeddings.")

    print(f"开始批量处理，批量大小: {batch_size}")

    outputs = []
    for i in range(0, len(images), batch_size):
        batch_paths = images[i:i + batch_size]
        batch_images = []

        # 加载批量图片
        for path in batch_paths:
            try:
                image = Image.open(path).convert("RGB")
                batch_images.append(image)
            except Exception as e:
                print(f"  警告: 无法加载图片 {path}: {e}")
                continue

        if not batch_images:
            continue

        # 批量编码
        try:
            batch_vecs = model.encode(
                batch_images,
                convert_to_numpy=True,
                normalize_embeddings=True,
                batch_size=len(batch_images),
                show_progress_bar=False
            )

            # 保存结果
            for j, vec in enumerate(batch_vecs):
                if j < len(batch_paths):
                    outputs.append((batch_paths[j], vec))
        except Exception as e:
            print(f"  警告: 批量编码失败: {e}")
            # 降级为单张处理
            for path in batch_paths:
                try:
                    image = Image.open(path).convert("RGB")
                    vec = model.encode(image, convert_to_numpy=True, normalize_embeddings=True)
                    outputs.append((path, vec))
                except:
                    continue

        # 显示进度
        if (i + batch_size) % 100 == 0 or (i + batch_size) >= len(images):
            print(f"  处理进度: {min(i + batch_size, len(images))}/{len(images)}")

    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="POC image embedding with LanceDB")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--batch-size", type=int, help="批量处理大小（覆盖配置文件，GPU时可设置更大，如64或128）")
    parser.add_argument("--incremental", action="store_true",
                        help="增量模式：只处理 LanceDB 中尚未存在的图片，不清空已有数据")
    args = parser.parse_args()

    if np is None:
        raise RuntimeError("numpy is required. Please pip install numpy.")

    if lancedb is None:
        raise RuntimeError("lancedb is required. Please pip install lancedb.")

    config = load_yaml(args.config)
    paths_cfg = config.get("paths", {})
    search_cfg = config.get("search", {})

    # 获取模型类型
    model_type = search_cfg.get("embedding_model", "clip")

    # 确定批处理大小
    if args.batch_size:
        batch_size = args.batch_size
        print(f"使用命令行指定的批处理大小: {batch_size}")
    elif search_cfg.get("auto_batch_size", False):
        batch_size = auto_detect_batch_size()
        print(f"自动检测批处理大小: {batch_size}")
    else:
        batch_size = search_cfg.get("batch_size", 32)
        print(f"使用配置文件的批处理大小: {batch_size}")

    raw_images_dir = resolve_path(paths_cfg.get("raw_images_dir", "poc/data/raw/images"))
    db_path = resolve_path(paths_cfg.get("db_path", "poc/data/metadata.db"))
    lancedb_dir = resolve_path(paths_cfg.get("lancedb_dir", "poc/data/lancedb"))
    ensure_dir(lancedb_dir)

    # 发现图片
    images = discover_images(raw_images_dir)
    print(f"发现 {len(images)} 张图片")

    # 增量模式：过滤掉 LanceDB 中已存在的图片
    existing_paths = set()
    if args.incremental:
        try:
            db = lancedb.connect(str(lancedb_dir))
            _tables = db.list_tables() if hasattr(db, 'list_tables') else db.table_names()
            if "embeddings" in _tables:
                table = db.open_table("embeddings")
                existing_df = table.to_pandas()
                existing_paths = set(existing_df["file_path"].tolist())
                print(f"增量模式：LanceDB 已有 {len(existing_paths)} 条记录")
        except Exception as e:
            print(f"增量模式：读取已有数据失败（将全量处理）: {e}")

        if existing_paths:
            before = len(images)
            images = [p for p in images if str(p) not in existing_paths]
            print(f"增量模式：跳过 {before - len(images)} 张已处理图片，剩余 {len(images)} 张待处理")
            if not images:
                print("所有图片已向量化，无需处理")
                return

    # 生成向量
    if args.mock:
        embeddings = [(path, np.random.rand(512).astype("float32")) for path in images]
        model_name = "mock"
        dims = 512
    else:
        # 使用 ModelManager 加载模型
        from poc.search.model_manager import ModelManager

        print(f"使用模型类型: {model_type}")
        manager = ModelManager(config)
        dims = manager.get_embedding_dimension()
        model_name = model_type

        print(f"开始生成向量嵌入...")
        import time
        start_time = time.time()

        # 真正的批量处理 — 利用服务端 batch API
        embeddings = []
        processed = 0
        failed = 0
        total = len(images)
        # 服务端 batch 一次不宜太大（显存/请求体限制），用较小的 sub-batch
        sub_batch = min(batch_size, 8)

        for i in range(0, total, sub_batch):
            batch_paths = images[i:i + sub_batch]
            try:
                vecs = manager.encode_images_batch(batch_paths)
                for j, path in enumerate(batch_paths):
                    embeddings.append((path, vecs[j]))
                processed += len(batch_paths)
            except Exception as batch_err:
                # batch 失败，逐张 fallback
                for path in batch_paths:
                    try:
                        vec = manager.encode_image(path)
                        embeddings.append((path, vec))
                        processed += 1
                    except Exception as e:
                        print(f"  警告: 无法处理图片 {path}: {e}")
                        failed += 1

            if processed % 50 == 0 or processed == total:
                elapsed = time.time() - start_time
                speed = processed / elapsed if elapsed > 0 else 0
                eta = (total - processed) / speed if speed > 0 else 0
                print(f"  进度: {processed}/{total}  ({speed:.1f} 张/秒, 预计剩余 {eta:.0f}s, 失败 {failed})")

        print(f"  处理进度: {processed}/{total} (完成, 失败 {failed})")

        elapsed_time = time.time() - start_time
        print(f"向量生成完成，耗时: {elapsed_time:.2f} 秒")
        if processed > 0:
            print(f"平均速度: {processed / elapsed_time:.2f} 张/秒")

    # 从 SQLite 获取资产+事件全量元数据（写入 Lance 表，供 DuckDB 统一查询）
    conn = connect_db(db_path)
    assets_data = {}
    assets_by_filename = {}
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
        row_dict = dict(row)
        assets_data[row["file_path"]] = row_dict
        if row["file_name"]:
            assets_by_filename[row["file_name"]] = row_dict
    conn.close()

    print(f"数据库中的资产数: {len(assets_data)}")
    print(f"通过文件名索引的资产数: {len(assets_by_filename)}")

    # 准备 LanceDB 数据
    lance_data = []
    matched_count = 0
    unmatched_count = 0

    for path, vec in embeddings:
        # 先尝试完整路径匹配
        asset_info = assets_data.get(str(path))

        # 如果路径不匹配，尝试通过文件名匹配
        if not asset_info:
            filename = Path(path).name
            asset_info = assets_by_filename.get(filename)

        if not asset_info:
            unmatched_count += 1
            if unmatched_count <= 5:  # 只打印前5个未匹配的
                print(f"  未匹配: {Path(path).name}")
            continue

        matched_count += 1
        ai = asset_info

        lance_data.append({
            "asset_id": ai["asset_id"],
            "file_path": str(path),
            "file_name": ai["file_name"] or "",
            "vector": vec.tolist(),
            # assets 字段
            "media_type": ai.get("media_type") or "",
            "captured_at": ai.get("captured_at") or "",
            "source": ai.get("source") or "",
            # events 字段
            "event_id": ai.get("event_id") or "",
            "event_type": ai.get("event_type") or "",
            "alarm_level": ai.get("alarm_level") or "",
            "alarm_source": ai.get("alarm_source") or "",
            "alarm_time": ai.get("alarm_time") or "",
            "lat": float(ai.get("lat") or 0),
            "lon": float(ai.get("lon") or 0),
            "region": ai.get("region") or "",
            "extra_json": ai.get("extra_json") or "",
            "summary": ai.get("summary") or "",
            "description": ai.get("description") or "",
            "address": ai.get("address") or "",
            "device_name": ai.get("device_name") or "",
            "confidence_level": float(ai.get("confidence_level") or 0),
            "province_name": ai.get("province_name") or "",
            "city_name": ai.get("city_name") or "",
            "county_name": ai.get("county_name") or "",
            "town_code": ai.get("town_code") or "",
            "town_name": ai.get("town_name") or "",
            "device_code": ai.get("device_code") or "",
            "channel_code": ai.get("channel_code") or "",
            "channel_name": ai.get("channel_name") or "",
            "warning_order_id": ai.get("warning_order_id") or "",
            "warning_type_id": ai.get("warning_type_id") or "",
            "alarm_body": ai.get("alarm_body") or "",
            "algorithm_code": ai.get("algorithm_code") or "",
            "algorithm_name": ai.get("algorithm_name") or "",
            "emergency_level": ai.get("emergency_level") or "",
            "importance_level": ai.get("importance_level") or "",
            "order_status": ai.get("order_status") or "",
            "confidence_level_max": float(ai.get("confidence_level_max") or 0),
            "tenant_name": ai.get("tenant_name") or "",
            "video_path": ai.get("video_path") or "",
            "img_src_path": ai.get("img_src_path") or "",
            "img_icon_path": ai.get("img_icon_path") or "",
        })

    # 写入 LanceDB
    print(f"\n匹配统计:")
    print(f"  - 成功匹配: {matched_count} 条")
    print(f"  - 未匹配: {unmatched_count} 条")
    print(f"写入 LanceDB: {len(lance_data)} 条记录")
    db = lancedb.connect(str(lancedb_dir))

    table_name = "embeddings"
    # 兼容不同 LanceDB 版本：list_tables() 可能返回字符串列表或对象列表
    def _table_exists(db, name):
        try:
            names = db.table_names() if hasattr(db, 'table_names') else db.list_tables()
            # table_names() 返回 [str]，list_tables() 可能返回 [str] 或 [Table]
            return name in [str(t) for t in names]
        except Exception:
            return False

    if args.incremental and _table_exists(db, table_name):
        # 增量模式：追加到已有表
        table = db.open_table(table_name)
        if lance_data:
            table.add(lance_data)
            print(f"增量追加 {len(lance_data)} 条记录")
        n = table.count_rows()
    else:
        # 全量模式：删除重建（强制 try drop，防止版本差异导致检测遗漏）
        try:
            db.drop_table(table_name)
            print(f"已删除旧表 '{table_name}'")
        except Exception:
            pass
        table = db.create_table(table_name, data=lance_data)
        n = len(lance_data)

    # 创建向量索引（提升查询性能）
    # num_sub_vectors 必须能整除向量维度（如 4096 → 可用 64/128/256）
    # num_partitions 不能超过数据行数
    n = len(lance_data)
    if n >= 1000:
        np_ = min(256, n)
        print(f"创建向量索引（{np_}分区）...")
        table.create_index(metric="cosine", num_partitions=np_, num_sub_vectors=64)
    elif n >= 256:
        np_ = max(n // 4, 16)
        print(f"创建向量索引（{np_}分区，数据量较少）...")
        table.create_index(metric="cosine", num_partitions=np_, num_sub_vectors=64)
    else:
        print(f"数据量较少（{n}条），跳过索引创建（建议至少256条）")

    print(f"[OK] 完成！共处理 {len(lance_data)} 条记录")
    print(f"  - 模型: {model_name}")
    print(f"  - 维度: {dims}")
    print(f"  - 存储路径: {lancedb_dir}")


if __name__ == "__main__":
    main()
