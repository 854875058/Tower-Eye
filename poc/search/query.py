import argparse
import json
import math
from pathlib import Path
from typing import List, Optional

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


try:
    import jieba  # type: ignore
    # 验证 jieba 是否真的可用（Python 3.12+ 兼容性问题）
    jieba.cut("test")
except Exception:  # pragma: no cover - optional dependency
    jieba = None


def _tokenize(text: str) -> set:
    """中文分词：优先用 jieba，fallback 到 bigram + trigram 切分"""
    if jieba is not None:
        return {w for w in jieba.cut_for_search(text) if len(w.strip()) > 0}
    # fallback: 中文 bigram + trigram（覆盖大部分中文词汇长度）
    import re
    tokens = set()
    # 提取连续中文片段
    segments = re.findall(r'[\u4e00-\u9fff]+', text)
    for seg in segments:
        # bigram
        for i in range(len(seg) - 1):
            tokens.add(seg[i:i+2])
        # trigram
        for i in range(len(seg) - 2):
            tokens.add(seg[i:i+3])
        # 原始片段本身
        if len(seg) >= 2:
            tokens.add(seg)
    # 英文按空格分
    for w in re.findall(r'[a-zA-Z0-9]+', text):
        if len(w) > 1:
            tokens.add(w)
    return tokens


def keyword_match_score(query_text: str, summary: str) -> float:
    """
    计算关键词匹配得分（支持中文分词）

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

    query_words = _tokenize(query_text)
    # 过滤掉单字符停用词（的、了、在 等），保留有意义的词
    query_words = {w for w in query_words if len(w) > 1}
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
    # 有 filter 时加大候选池，因为 filter 会大幅缩减结果
    if filter_str:
        candidate_k = top_k * 10
    else:
        candidate_k = top_k * 5

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


def build_asset_id_filter(asset_ids: List[str]) -> Optional[str]:
    """
    根据 asset_id 列表生成 LanceDB WHERE 条件。

    Args:
        asset_ids: 需要过滤的 asset_id 列表

    Returns:
        形如 "asset_id IN ('id1','id2',...)" 的字符串，空列表返回 None
    """
    if not asset_ids:
        return None
    escaped = [aid.replace("'", "''") for aid in asset_ids]
    in_list = ", ".join(f"'{aid}'" for aid in escaped)
    return f"asset_id IN ({in_list})"


def build_lance_filter(
    event_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: float = 5.0,
    **kwargs,
) -> Optional[str]:
    """
    构建 LanceDB 过滤条件 — 精简版。

    结构化字段过滤已迁移到 SQLite，此函数仅保留向后兼容签名。
    实际过滤通过 build_asset_id_filter() 传入 asset_id IN 条件。
    """
    # 保留空壳以兼容 CLI main() 等旧调用方
    return None


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

    # 构建过滤条件（已迁移到 SQLite，此处不再过滤）
    filter_str = None

    # 执行检索（混合或纯向量）
    if args.hybrid and args.text:
        results_df = hybrid_search(
            table,
            query_vec,
            query_text=args.text,
            top_k=args.top_k * 2,
            filter_str=filter_str,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )
    else:
        query = table.search(query_vec.tolist()).limit(args.top_k * 2)
        if filter_str:
            query = query.where(filter_str)
        results_df = query.to_pandas()

    # 从 LanceDB 只取 asset_id + distance，然后用 SQLite 补全展示字段
    asset_ids = results_df["asset_id"].tolist()
    distances = {}
    hybrid_scores = {}
    for _, row in results_df.iterrows():
        aid = row["asset_id"]
        distances[aid] = float(row.get("_distance", 0))
        if "hybrid_score" in row:
            hybrid_scores[aid] = float(row["hybrid_score"])

    # 从 SQLite 批量获取完整事件信息
    from poc.pipeline.utils import connect_db
    db_path = resolve_path(paths_cfg.get("db_path", "poc/data/metadata.db"))
    conn = connect_db(str(db_path))
    events_map = {}
    if asset_ids:
        placeholders = ", ".join("?" for _ in asset_ids)
        sql = (
            "SELECT e.*, a.file_path, a.file_name "
            "FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id "
            f"WHERE a.asset_id IN ({placeholders})"
        )
        for row in conn.execute(sql, asset_ids).fetchall():
            rd = dict(row)
            events_map[rd["asset_id"]] = rd
    conn.close()

    # 转换为列表格式（保持 LanceDB 排序）
    results = []
    for aid in asset_ids:
        rd = events_map.get(aid, {})
        extra = {}
        if rd.get("extra_json"):
            try:
                extra = json.loads(rd["extra_json"])
            except Exception:
                pass
        dist = distances.get(aid, 0)
        result_item = {
            "asset_id": aid,
            "distance": dist,
            "score": hybrid_scores.get(aid, dist),
            "file_path": rd.get("file_path", ""),
            "file_name": rd.get("file_name", ""),
            "captured_at": rd.get("alarm_time", ""),
            "lat": rd.get("lat") or 0.0,
            "lon": rd.get("lon") or 0.0,
            "event_type": rd.get("event_type", ""),
            "alarm_time": rd.get("alarm_time", ""),
            "alarm_level": rd.get("alarm_level") or extra.get("emergency_level", ""),
            "summary": rd.get("summary", ""),
            "description": rd.get("description", ""),
            "address": rd.get("address", ""),
            "device_name": rd.get("device_name", ""),
            "confidence_level": rd.get("confidence_level"),
        }
        results.append(result_item)

    # Reranker（如果启用）
    reranker_enabled = args.rerank or search_cfg.get("reranker_enabled", False)
    if reranker_enabled and args.text and not args.mock:
        print(f"🔄 启用 Reranker，处理 {len(results)} 条候选结果...", file=__import__('sys').stderr)
        from poc.search.model_manager import ModelManager
        manager = ModelManager(config)
        results = manager.rerank(args.text, results, top_k=args.top_k)
        print(f"[OK] Reranker 完成，返回 {len(results)} 条结果", file=__import__('sys').stderr)
    else:
        results = results[:args.top_k]

    # 输出结果
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
