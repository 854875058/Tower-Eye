"""
混合检索策略模块

支持多种检索策略的组合：
1. 向量检索（Vector Search）
2. BM25 关键词检索
3. 重排序（Reranker）

根据查询类型自动选择最优策略
"""

import math
from collections import Counter
from typing import Dict, List, Optional, Tuple

try:
    import numpy as np
except ImportError:
    np = None


class BM25:
    """BM25 算法实现（用于关键词检索）"""

    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75):
        """
        初始化 BM25

        Args:
            corpus: 文档列表
            k1: 词频饱和参数（默认1.5）
            b: 文档长度归一化参数（默认0.75）
        """
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.corpus_size = len(corpus)
        self.avgdl = sum(len(doc.split()) for doc in corpus) / self.corpus_size if self.corpus_size > 0 else 0
        self.doc_freqs = []
        self.idf = {}
        self.doc_len = []

        # 计算文档频率和IDF
        self._initialize()

    def _initialize(self):
        """初始化文档频率和IDF"""
        df = {}
        for doc in self.corpus:
            words = doc.split()
            self.doc_len.append(len(words))
            frequencies = Counter(words)
            self.doc_freqs.append(frequencies)

            for word in frequencies.keys():
                df[word] = df.get(word, 0) + 1

        # 计算IDF
        for word, freq in df.items():
            self.idf[word] = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1)

    def get_scores(self, query: str) -> List[float]:
        """
        计算查询与所有文档的BM25得分

        Args:
            query: 查询文本

        Returns:
            每个文档的BM25得分列表
        """
        scores = []
        query_words = query.split()

        for idx, doc_freq in enumerate(self.doc_freqs):
            score = 0.0
            doc_len = self.doc_len[idx]

            for word in query_words:
                if word not in doc_freq:
                    continue

                freq = doc_freq[word]
                idf = self.idf.get(word, 0)

                # BM25 公式
                numerator = freq * (self.k1 + 1)
                denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                score += idf * (numerator / denominator)

            scores.append(score)

        return scores


def detect_query_type(query_text: str) -> str:
    """
    检测查询类型，决定使用哪种检索策略

    Args:
        query_text: 查询文本

    Returns:
        查询类型：
        - "visual": 视觉内容描述（颜色、物体、场景等）
        - "keyword": 关键词查询（地点、设备名称等）
        - "hybrid": 混合查询
    """
    # 视觉关键词
    visual_keywords = [
        "红色", "蓝色", "白色", "黑色", "黄色", "绿色",
        "挖掘机", "卡车", "轿车", "货车", "吊车",
        "停在", "行驶", "施工", "挖掘",
        "沙地", "土坡", "工地", "草地", "马路"
    ]

    # 结构化关键词
    structured_keywords = [
        "统计", "数量", "多少", "总数", "分布",
        "按街道", "按设备", "按类型"
    ]

    visual_count = sum(1 for kw in visual_keywords if kw in query_text)
    structured_count = sum(1 for kw in structured_keywords if kw in query_text)

    if structured_count > 0:
        return "keyword"  # 结构化查询优先用关键词
    elif visual_count >= 2:
        return "visual"  # 多个视觉关键词用向量检索
    elif visual_count == 1:
        return "hybrid"  # 单个视觉关键词用混合检索
    else:
        return "keyword"  # 默认关键词检索


def enhanced_hybrid_search(
    table,
    query_vec,
    query_text: str,
    top_k: int = 10,
    filter_str: Optional[str] = None,
    use_reranker: bool = False,
    reranker=None,
    strategy: str = "auto"
) -> Tuple[List[Dict], Dict]:
    """
    增强的混合检索：自动选择最优策略

    Args:
        table: LanceDB 表
        query_vec: 查询向量
        query_text: 查询文本
        top_k: 返回数量
        filter_str: 过滤条件
        use_reranker: 是否使用重排序
        reranker: Reranker 实例
        strategy: 检索策略（"auto", "vector", "bm25", "hybrid"）

    Returns:
        (结果列表, 元数据字典)
    """
    metadata = {
        "strategy": strategy,
        "query_type": None,
        "vector_results": 0,
        "bm25_results": 0,
        "reranked": use_reranker
    }

    # 自动检测查询类型
    if strategy == "auto":
        query_type = detect_query_type(query_text)
        metadata["query_type"] = query_type

        if query_type == "visual":
            strategy = "vector"
        elif query_type == "keyword":
            strategy = "bm25"
        else:
            strategy = "hybrid"

    metadata["strategy"] = strategy

    # 获取候选结果
    if filter_str:
        candidate_k = top_k * 10
    else:
        candidate_k = top_k * 5

    # 执行向量检索
    query_obj = table.search(query_vec.tolist()).limit(candidate_k)
    if filter_str:
        query_obj = query_obj.where(filter_str)

    results_df = query_obj.to_pandas()
    metadata["vector_results"] = len(results_df)

    if len(results_df) == 0:
        return [], metadata

    # 根据策略计算得分
    if strategy == "vector":
        # 纯向量检索
        results_df["final_score"] = results_df["_distance"].apply(lambda d: 1.0 / (1.0 + float(d)))

    elif strategy == "bm25":
        # BM25 关键词检索
        if "summary" in results_df.columns:
            corpus = results_df["summary"].fillna("").tolist()
            bm25 = BM25(corpus)
            bm25_scores = bm25.get_scores(query_text)
            metadata["bm25_results"] = sum(1 for s in bm25_scores if s > 0)

            # 归一化 BM25 得分
            max_bm25 = max(bm25_scores) if bm25_scores else 1.0
            if max_bm25 > 0:
                bm25_scores = [s / max_bm25 for s in bm25_scores]

            results_df["bm25_score"] = bm25_scores
            results_df["final_score"] = bm25_scores
        else:
            # 没有 summary 字段，降级为向量检索
            results_df["final_score"] = results_df["_distance"].apply(lambda d: 1.0 / (1.0 + float(d)))

    elif strategy == "hybrid":
        # 混合检索：向量 + BM25
        vector_scores = results_df["_distance"].apply(lambda d: 1.0 / (1.0 + float(d))).tolist()

        if "summary" in results_df.columns:
            corpus = results_df["summary"].fillna("").tolist()
            bm25 = BM25(corpus)
            bm25_scores = bm25.get_scores(query_text)
            metadata["bm25_results"] = sum(1 for s in bm25_scores if s > 0)

            # 归一化 BM25 得分
            max_bm25 = max(bm25_scores) if bm25_scores else 1.0
            if max_bm25 > 0:
                bm25_scores = [s / max_bm25 for s in bm25_scores]

            # 混合得分：60% 向量 + 40% BM25
            hybrid_scores = [0.6 * v + 0.4 * b for v, b in zip(vector_scores, bm25_scores)]
            results_df["bm25_score"] = bm25_scores
            results_df["vector_score"] = vector_scores
            results_df["final_score"] = hybrid_scores
        else:
            # 没有 summary 字段，降级为向量检索
            results_df["final_score"] = vector_scores

    # 按得分排序
    results_df = results_df.sort_values("final_score", ascending=False)

    # 转换为字典列表
    results = results_df.head(top_k * 2 if use_reranker else top_k).to_dict("records")

    # 使用 Reranker 重排序
    if use_reranker and reranker and len(results) > 0:
        try:
            results = reranker.rerank(query_text, results, top_k=top_k)
            metadata["reranked"] = True
        except Exception as e:
            print(f"[WARN] Reranker 失败，使用原始排序: {e}")
            results = results[:top_k]
            metadata["reranked"] = False
    else:
        results = results[:top_k]

    return results, metadata


def explain_search_strategy(metadata: Dict) -> str:
    """
    解释检索策略选择

    Args:
        metadata: 检索元数据

    Returns:
        策略说明文本
    """
    strategy = metadata.get("strategy", "unknown")
    query_type = metadata.get("query_type", "unknown")
    reranked = metadata.get("reranked", False)

    explanations = {
        "vector": "使用向量检索（适合视觉内容描述）",
        "bm25": "使用BM25关键词检索（适合精确匹配）",
        "hybrid": "使用混合检索（向量+BM25，适合复杂查询）"
    }

    base_text = explanations.get(strategy, f"使用{strategy}策略")

    if query_type:
        base_text += f"，查询类型：{query_type}"

    if reranked:
        base_text += "，已使用Reranker重排序"

    vector_count = metadata.get("vector_results", 0)
    bm25_count = metadata.get("bm25_results", 0)

    if vector_count > 0:
        base_text += f"，向量召回{vector_count}条"
    if bm25_count > 0:
        base_text += f"，BM25匹配{bm25_count}条"

    return base_text
