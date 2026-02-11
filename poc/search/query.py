import argparse
import json
import math
from pathlib import Path
from typing import Optional

from poc.pipeline.utils import load_yaml, resolve_path

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
        raise RuntimeError("sentence-transformers not installed.") from exc

    # 设置HuggingFace镜像源（国内加速）
    if hf_mirror:
        import os
        # 设置多个环境变量以确保兼容性
        os.environ['HF_ENDPOINT'] = hf_mirror
        os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir if cache_dir else os.path.expanduser('~/.cache/huggingface')
        print(f"使用HuggingFace镜像源: {hf_mirror}")

    # 检测GPU
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"使用设备: {device}")
    if device == 'cuda':
        print(f"GPU型号: {torch.cuda.get_device_name(0)}")

    # 加载模型
    if cache_dir:
        from pathlib import Path
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        model = SentenceTransformer(model_name, cache_folder=str(cache_path), device=device)
    else:
        model = SentenceTransformer(model_name, device=device)

    return model


def encode_query(model, text: Optional[str], image_path: Optional[Path]):
    if np is None:
        raise RuntimeError("numpy is required.")
    if text:
        return model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
    if image_path:
        if Image is None:
            raise RuntimeError("Pillow is required for image query.")
        image = Image.open(image_path).convert("RGB")
        return model.encode(image, convert_to_numpy=True, normalize_embeddings=True)
    raise RuntimeError("Specify text or image for query.")


def keyword_match_score(query_text: str, summary: str) -> float:
    """
    计算关键词匹配得分

    Args:
        query_text: 查询文本
        summary: 图像理解文本

    Returns:
        匹配得分 (0-1)
    """
    if not query_text or not summary:
        return 0.0

    query_text = query_text.lower()
    summary = summary.lower()

    # 简单的关键词匹配：计算查询词在summary中出现的比例
    query_words = set(query_text.split())
    if not query_words:
        return 0.0

    matched_words = sum(1 for word in query_words if word in summary)
    return matched_words / len(query_words)


def hybrid_search(
    table,
    query_vec,
    query_text: Optional[str] = None,
    top_k: int = 10,
    filter_str: Optional[str] = None,
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3,
):
    """
    混合检索：向量相似度 + 关键词匹配

    Args:
        table: LanceDB 表
        query_vec: 查询向量
        query_text: 查询文本（用于关键词匹配）
        top_k: 返回数量
        filter_str: 过滤条件
        vector_weight: 向量相似度权重
        keyword_weight: 关键词匹配权重

    Returns:
        混合检索结果 DataFrame
    """
    # 先获取更多候选结果（用于重排序）
    candidate_k = min(top_k * 5, 100)

    # 执行向量搜索
    query = table.search(query_vec.tolist()).limit(candidate_k)
    if filter_str:
        query = query.where(filter_str)

    results_df = query.to_pandas()

    # 如果没有查询文本或没有summary字段，直接返回向量检索结果
    if not query_text or "summary" not in results_df.columns:
        return results_df.head(top_k)

    # 计算混合得分
    scores = []
    for _, row in results_df.iterrows():
        # 向量相似度得分（距离越小越相似，转换为相似度）
        vector_score = 1.0 / (1.0 + float(row["_distance"]))

        # 关键词匹配得分
        keyword_score = keyword_match_score(query_text, row.get("summary", ""))

        # 混合得分
        hybrid_score = vector_weight * vector_score + keyword_weight * keyword_score
        scores.append(hybrid_score)

    # 添加混合得分列
    results_df["hybrid_score"] = scores

    # 按混合得分排序
    results_df = results_df.sort_values("hybrid_score", ascending=False)

    return results_df.head(top_k)


def build_lance_filter(
    event_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 5.0,
    town_name: Optional[str] = None,
    county_name: Optional[str] = None,
    city_name: Optional[str] = None,
    device_name: Optional[str] = None,
    device_code: Optional[str] = None,
    alarm_level: Optional[str] = None,
    confidence_min: Optional[float] = None,
    confidence_max: Optional[float] = None,
    order_status: Optional[str] = None,
    algorithm_name: Optional[str] = None,
    algorithm_code: Optional[str] = None,
    importance_level: Optional[str] = None,
    warning_source_name: Optional[str] = None,
    alarm_body: Optional[str] = None,
    tenant_name: Optional[str] = None,
    channel_name: Optional[str] = None,
    table_columns: Optional[set] = None,
) -> Optional[str]:
    """
    构建 LanceDB 过滤条件（SQL WHERE 语法）
    优化版：修复多条件联合查询问题

    Args:
        table_columns: LanceDB 表的列名集合，传入后会跳过表中不存在的字段，
                       避免旧版向量库缺少 city_name 等列时崩溃。
    """
    conditions = []
    skipped = []

    def _has_col(col_name: str) -> bool:
        """检查字段是否存在于表 schema 中"""
        if table_columns is None:
            return True  # 未传入时不做限制，保持向后兼容
        return col_name in table_columns

    if event_type and _has_col("event_type"):
        conditions.append(f"event_type = '{event_type}'")
    elif event_type:
        skipped.append("event_type")

    # 优化时间过滤逻辑
    if (start_time or end_time) and _has_col("alarm_time"):
        if start_time and end_time:
            conditions.append(f"(alarm_time BETWEEN '{start_time}' AND '{end_time}')")
        elif start_time:
            conditions.append(f"alarm_time >= '{start_time}'")
        elif end_time:
            conditions.append(f"alarm_time <= '{end_time}'")
    elif start_time or end_time:
        skipped.append("alarm_time")

    if lat is not None and lon is not None:
        if _has_col("lat") and _has_col("lon"):
            lat_delta = radius_km / 111.0
            lon_delta = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
            min_lat = lat - lat_delta
            max_lat = lat + lat_delta
            min_lon = lon - lon_delta
            max_lon = lon + lon_delta
            conditions.append(f"(lat >= {min_lat} AND lat <= {max_lat} AND lon >= {min_lon} AND lon <= {max_lon})")
        else:
            skipped.append("lat/lon")

    if town_name:
        if _has_col("town_name"):
            conditions.append(f"town_name = '{town_name}'")
        else:
            skipped.append("town_name")

    if county_name:
        if _has_col("county_name"):
            conditions.append(f"county_name = '{county_name}'")
        else:
            skipped.append("county_name")

    if city_name:
        if _has_col("city_name"):
            conditions.append(f"city_name = '{city_name}'")
        else:
            skipped.append("city_name")

    if device_name:
        if _has_col("device_name"):
            conditions.append(f"device_name LIKE '%{device_name}%'")
        else:
            skipped.append("device_name")

    if alarm_level:
        if _has_col("alarm_level"):
            conditions.append(f"alarm_level = '{alarm_level}'")
        else:
            skipped.append("alarm_level")

    if confidence_min is not None:
        if _has_col("confidence_level"):
            conditions.append(f"confidence_level >= {confidence_min}")
        else:
            skipped.append("confidence_level")

    if confidence_max is not None:
        if _has_col("confidence_level"):
            conditions.append(f"confidence_level <= {confidence_max}")
        else:
            if "confidence_level" not in skipped:
                skipped.append("confidence_level")

    if order_status:
        if _has_col("order_status"):
            conditions.append(f"order_status = '{order_status}'")
        else:
            skipped.append("order_status")

    if algorithm_name:
        if _has_col("algorithm_name"):
            conditions.append(f"algorithm_name LIKE '%{algorithm_name}%'")
        else:
            skipped.append("algorithm_name")

    if algorithm_code:
        if _has_col("algorithm_code"):
            conditions.append(f"algorithm_code = '{algorithm_code}'")
        else:
            skipped.append("algorithm_code")

    if device_code:
        if _has_col("device_code"):
            conditions.append(f"device_code = '{device_code}'")
        else:
            skipped.append("device_code")

    if importance_level:
        if _has_col("importance_level"):
            conditions.append(f"importance_level = '{importance_level}'")
        else:
            skipped.append("importance_level")

    if warning_source_name:
        if _has_col("warning_source_name"):
            conditions.append(f"warning_source_name = '{warning_source_name}'")
        else:
            skipped.append("warning_source_name")

    if alarm_body:
        if _has_col("alarm_body"):
            conditions.append(f"alarm_body LIKE '%{alarm_body}%'")
        else:
            skipped.append("alarm_body")

    if tenant_name:
        if _has_col("tenant_name"):
            conditions.append(f"tenant_name = '{tenant_name}'")
        else:
            skipped.append("tenant_name")

    if channel_name:
        if _has_col("channel_name"):
            conditions.append(f"channel_name LIKE '%{channel_name}%'")
        else:
            skipped.append("channel_name")

    if skipped:
        print(f"[build_lance_filter] 跳过向量库中不存在的字段: {skipped}，请重新运行 embed 更新向量库")

    return " AND ".join(conditions) if conditions else None


def main() -> None:
    parser = argparse.ArgumentParser(description="POC multimodal search query with LanceDB")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    parser.add_argument("--text")
    parser.add_argument("--image")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--event-type")
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--radius-km", type=float, default=5.0)
    parser.add_argument("--hybrid", action="store_true", help="启用混合检索（向量+关键词）")
    parser.add_argument("--vector-weight", type=float, help="向量相似度权重（覆盖配置文件）")
    parser.add_argument("--keyword-weight", type=float, help="关键词匹配权重（覆盖配置文件）")
    parser.add_argument("--rerank", action="store_true", help="启用 Reranker（覆盖配置文件）")
    args = parser.parse_args()

    if np is None:
        raise RuntimeError("numpy is required. Please pip install numpy.")

    if lancedb is None:
        raise RuntimeError("lancedb is required. Please pip install lancedb.")

    config = load_yaml(args.config)
    paths_cfg = config.get("paths", {})
    search_cfg = config.get("search", {})
    lancedb_dir = resolve_path(paths_cfg.get("lancedb_dir", "poc/data/lancedb"))

    # 获取混合检索权重（命令行参数优先）
    vector_weight = args.vector_weight if args.vector_weight is not None else search_cfg.get("vector_weight", 0.7)
    keyword_weight = args.keyword_weight if args.keyword_weight is not None else search_cfg.get("keyword_weight", 0.3)

    # 连接 LanceDB
    db = lancedb.connect(str(lancedb_dir))
    table = db.open_table("embeddings")

    # 生成查询向量
    if args.mock:
        # 获取表的向量维度
        sample = table.to_pandas().head(1)
        dims = len(sample['vector'].iloc[0])
        query_vec = np.random.rand(dims).astype("float32")
        query_vec /= max(1e-12, float(np.linalg.norm(query_vec)))
    else:
        # 使用 ModelManager
        from poc.search.model_manager import ModelManager
        manager = ModelManager(config)

        if args.text:
            query_vec = manager.encode_text(args.text).astype("float32")
        elif args.image:
            query_vec = manager.encode_image(resolve_path(args.image)).astype("float32")
        else:
            raise RuntimeError("Specify --text or --image for query.")

    # 构建过滤条件
    filter_str = build_lance_filter(
        event_type=args.event_type,
        start_time=args.start_time,
        end_time=args.end_time,
        lat=args.lat,
        lon=args.lon,
        radius_km=args.radius_km,
    )

    # 执行检索（混合或纯向量）
    if args.hybrid and args.text:
        results_df = hybrid_search(
            table,
            query_vec,
            query_text=args.text,
            top_k=args.top_k * 2,  # 获取更多候选结果用于 rerank
            filter_str=filter_str,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )
    else:
        query = table.search(query_vec.tolist()).limit(args.top_k * 2)
        if filter_str:
            query = query.where(filter_str)
        results_df = query.to_pandas()

    # 转换为列表格式
    results = []
    for _, row in results_df.iterrows():
        result_item = {
            "asset_id": row["asset_id"],
            "distance": float(row.get("_distance", 0)),
            "score": float(row.get("hybrid_score", row.get("_distance", 0))),
            "file_path": row["file_path"],
            "file_name": row["file_name"],
            "captured_at": row["captured_at"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "event_type": row["event_type"],
            "alarm_time": row["alarm_time"],
            "alarm_level": row["alarm_level"],
        }

        # 添加新字段
        if "summary" in row:
            result_item["summary"] = row["summary"]
        if "description" in row:
            result_item["description"] = row["description"]
        if "address" in row:
            result_item["address"] = row["address"]
        if "device_name" in row:
            result_item["device_name"] = row["device_name"]
        if "confidence_level" in row:
            result_item["confidence_level"] = float(row["confidence_level"])

        results.append(result_item)

    # Reranker（如果启用）
    reranker_enabled = args.rerank or search_cfg.get("reranker_enabled", False)
    if reranker_enabled and args.text and not args.mock:
        print(f"🔄 启用 Reranker，处理 {len(results)} 条候选结果...", file=__import__('sys').stderr)
        from poc.search.model_manager import ModelManager
        manager = ModelManager(config)
        results = manager.rerank(args.text, results, top_k=args.top_k)
        print(f"✓ Reranker 完成，返回 {len(results)} 条结果", file=__import__('sys').stderr)
    else:
        results = results[:args.top_k]

    # 输出结果
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
