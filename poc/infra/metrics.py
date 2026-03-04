"""
可观测性指标收集与分析模块

功能：
1. LLM 调用成本追踪（token 消耗、API 调用次数）
2. 检索质量指标（召回率、精确率、MRR）
3. 热点问题分析（高频查询 Top N）
4. 失败 case 分析（错误类型分布、失败原因）
5. 性能指标（P50/P95/P99 响应时间）
"""

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from poc.qa.trace import get_trace_manager


@dataclass
class LLMCallMetrics:
    """LLM 调用指标"""
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float  # 估算成本（美元）
    latency_ms: float
    timestamp: str
    trace_id: str
    purpose: str  # 用途：nl2sql, fix_sql, semantic_enhance 等


@dataclass
class RetrievalMetrics:
    """检索质量指标"""
    query: str
    top_k: int
    retrieved_count: int
    relevant_count: int  # 用户点击/确认的相关结果数
    precision: float  # 精确率
    recall: float  # 召回率（需要标注数据）
    mrr: float  # Mean Reciprocal Rank
    latency_ms: float
    timestamp: str
    trace_id: str


class MetricsCollector:
    """指标收集器"""

    def __init__(self, db_path: Optional[Path] = None):
        """
        Args:
            db_path: 指标数据库路径，默认使用 trace.db 同目录
        """
        if db_path is None:
            trace_mgr = get_trace_manager()
            if trace_mgr and trace_mgr.db_path:
                db_path = trace_mgr.db_path.parent / "metrics.db"
            else:
                db_path = Path("poc/data/metrics.db")

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(str(self.db_path))

        # LLM 调用记录表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name TEXT NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                cost_usd REAL,
                latency_ms REAL,
                timestamp TEXT NOT NULL,
                trace_id TEXT,
                purpose TEXT
            )
        """)

        # 检索质量记录表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS retrieval_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                top_k INTEGER,
                retrieved_count INTEGER,
                relevant_count INTEGER,
                precision REAL,
                recall REAL,
                mrr REAL,
                latency_ms REAL,
                timestamp TEXT NOT NULL,
                trace_id TEXT
            )
        """)

        # 创建索引
        conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_timestamp ON llm_calls(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_trace ON llm_calls(trace_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_timestamp ON retrieval_metrics(timestamp)")

        conn.commit()
        conn.close()

    def record_llm_call(self, metrics: LLMCallMetrics):
        """记录 LLM 调用"""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            INSERT INTO llm_calls
            (model_name, prompt_tokens, completion_tokens, total_tokens, cost_usd,
             latency_ms, timestamp, trace_id, purpose)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics.model_name,
            metrics.prompt_tokens,
            metrics.completion_tokens,
            metrics.total_tokens,
            metrics.cost_usd,
            metrics.latency_ms,
            metrics.timestamp,
            metrics.trace_id,
            metrics.purpose
        ))
        conn.commit()
        conn.close()

    def record_retrieval(self, metrics: RetrievalMetrics):
        """记录检索指标"""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            INSERT INTO retrieval_metrics
            (query, top_k, retrieved_count, relevant_count, precision, recall, mrr,
             latency_ms, timestamp, trace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics.query,
            metrics.top_k,
            metrics.retrieved_count,
            metrics.relevant_count,
            metrics.precision,
            metrics.recall,
            metrics.mrr,
            metrics.latency_ms,
            metrics.timestamp,
            metrics.trace_id
        ))
        conn.commit()
        conn.close()

    def get_llm_cost_summary(self, hours: int = 24) -> Dict[str, Any]:
        """获取 LLM 成本汇总

        Args:
            hours: 统计最近 N 小时的数据

        Returns:
            {
                "total_calls": 总调用次数,
                "total_tokens": 总 token 数,
                "total_cost_usd": 总成本,
                "by_model": {模型名: {calls, tokens, cost}},
                "by_purpose": {用途: {calls, tokens, cost}},
                "avg_latency_ms": 平均延迟
            }
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        # 总体统计
        row = conn.execute("""
            SELECT
                COUNT(*) as total_calls,
                SUM(total_tokens) as total_tokens,
                SUM(cost_usd) as total_cost,
                AVG(latency_ms) as avg_latency
            FROM llm_calls
            WHERE timestamp >= ?
        """, (cutoff,)).fetchone()

        summary = {
            "total_calls": row["total_calls"] or 0,
            "total_tokens": row["total_tokens"] or 0,
            "total_cost_usd": round(row["total_cost"] or 0, 4),
            "avg_latency_ms": round(row["avg_latency"] or 0, 2)
        }

        # 按模型分组
        by_model = {}
        for row in conn.execute("""
            SELECT model_name, COUNT(*) as calls, SUM(total_tokens) as tokens, SUM(cost_usd) as cost
            FROM llm_calls
            WHERE timestamp >= ?
            GROUP BY model_name
        """, (cutoff,)):
            by_model[row["model_name"]] = {
                "calls": row["calls"],
                "tokens": row["tokens"] or 0,
                "cost_usd": round(row["cost"] or 0, 4)
            }
        summary["by_model"] = by_model

        # 按用途分组
        by_purpose = {}
        for row in conn.execute("""
            SELECT purpose, COUNT(*) as calls, SUM(total_tokens) as tokens, SUM(cost_usd) as cost
            FROM llm_calls
            WHERE timestamp >= ?
            GROUP BY purpose
        """, (cutoff,)):
            by_purpose[row["purpose"] or "unknown"] = {
                "calls": row["calls"],
                "tokens": row["tokens"] or 0,
                "cost_usd": round(row["cost"] or 0, 4)
            }
        summary["by_purpose"] = by_purpose

        conn.close()
        return summary

    def get_retrieval_quality(self, hours: int = 24) -> Dict[str, Any]:
        """获取检索质量统计

        Returns:
            {
                "total_queries": 总查询数,
                "avg_precision": 平均精确率,
                "avg_recall": 平均召回率,
                "avg_mrr": 平均 MRR,
                "avg_latency_ms": 平均延迟,
                "p50_latency_ms": P50 延迟,
                "p95_latency_ms": P95 延迟,
                "p99_latency_ms": P99 延迟
            }
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row

        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                AVG(precision) as avg_precision,
                AVG(recall) as avg_recall,
                AVG(mrr) as avg_mrr,
                AVG(latency_ms) as avg_latency
            FROM retrieval_metrics
            WHERE timestamp >= ?
        """, (cutoff,)).fetchone()

        summary = {
            "total_queries": row["total"] or 0,
            "avg_precision": round(row["avg_precision"] or 0, 3),
            "avg_recall": round(row["avg_recall"] or 0, 3),
            "avg_mrr": round(row["avg_mrr"] or 0, 3),
            "avg_latency_ms": round(row["avg_latency"] or 0, 2)
        }

        # 计算百分位延迟
        latencies = [r["latency_ms"] for r in conn.execute("""
            SELECT latency_ms FROM retrieval_metrics
            WHERE timestamp >= ? AND latency_ms IS NOT NULL
            ORDER BY latency_ms
        """, (cutoff,))]

        if latencies:
            import statistics
            summary["p50_latency_ms"] = round(statistics.median(latencies), 2)
            summary["p95_latency_ms"] = round(latencies[int(len(latencies) * 0.95)], 2)
            summary["p99_latency_ms"] = round(latencies[int(len(latencies) * 0.99)], 2)
        else:
            summary["p50_latency_ms"] = 0
            summary["p95_latency_ms"] = 0
            summary["p99_latency_ms"] = 0

        conn.close()
        return summary

    def get_hot_queries(self, limit: int = 10, hours: int = 24) -> List[Tuple[str, int]]:
        """获取热点问题 Top N

        Returns:
            [(问题, 查询次数), ...]
        """
        trace_mgr = get_trace_manager()
        if not trace_mgr:
            return []

        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        traces = trace_mgr.query_traces(
            start_time=cutoff,
            limit=10000  # 获取足够多的数据用于统计
        )

        # 使用归一化后的问题进行统计
        from poc.qa.trace import normalize_question
        counter = Counter()
        for t in traces:
            q = t.get("question", "")
            if q:
                normalized = normalize_question(q)
                counter[normalized] += 1

        return counter.most_common(limit)

    def get_failure_analysis(self, hours: int = 24) -> Dict[str, Any]:
        """获取失败 case 分析

        Returns:
            {
                "total_failures": 总失败数,
                "failure_rate": 失败率,
                "by_error_type": {错误类型: 次数},
                "recent_failures": [最近失败的 case]
            }
        """
        trace_mgr = get_trace_manager()
        if not trace_mgr:
            return {
                "total_failures": 0,
                "failure_rate": 0,
                "by_error_type": {},
                "recent_failures": []
            }

        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        # 获取统计数据
        stats = trace_mgr.get_statistics(start_time=cutoff)
        total = stats.get("total_queries", 0)
        failures = stats.get("error_count", 0)

        # 获取失败记录
        failed_traces = trace_mgr.query_traces(
            start_time=cutoff,
            status="error",
            limit=100
        )

        # 错误类型分类
        error_types = Counter()
        recent_failures = []

        for t in failed_traces:
            error_msg = t.get("error_message", "")

            # 简单的错误分类
            if "SQL" in error_msg or "syntax" in error_msg.lower():
                error_type = "SQL语法错误"
            elif "timeout" in error_msg.lower():
                error_type = "超时"
            elif "connection" in error_msg.lower():
                error_type = "连接错误"
            elif "not found" in error_msg.lower():
                error_type = "资源未找到"
            else:
                error_type = "其他错误"

            error_types[error_type] += 1

            # 保留最近的失败 case
            if len(recent_failures) < 20:
                recent_failures.append({
                    "timestamp": t.get("timestamp", "")[:19],
                    "question": t.get("question", "")[:100],
                    "error": error_msg[:200],
                    "trace_id": t.get("trace_id", "")
                })

        return {
            "total_failures": failures,
            "failure_rate": round(failures / total * 100, 2) if total > 0 else 0,
            "by_error_type": dict(error_types),
            "recent_failures": recent_failures
        }


# 全局单例
_metrics_collector: Optional[MetricsCollector] = None


def init_metrics_collector(db_path: Optional[Path] = None):
    """初始化全局指标收集器"""
    global _metrics_collector
    _metrics_collector = MetricsCollector(db_path=db_path)


def get_metrics_collector() -> Optional[MetricsCollector]:
    """获取全局指标收集器"""
    return _metrics_collector


def estimate_llm_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """估算 LLM 调用成本（美元）

    价格参考（2026年3月）：
    - DeepSeek: $0.14/M input tokens, $0.28/M output tokens
    - GPT-4: $10/M input tokens, $30/M output tokens
    - GPT-3.5: $0.5/M input tokens, $1.5/M output tokens
    """
    pricing = {
        "deepseek": (0.14, 0.28),
        "gpt-4": (10.0, 30.0),
        "gpt-3.5": (0.5, 1.5),
        "qwen": (0.0, 0.0),  # 本地模型无成本
    }

    model_lower = model_name.lower()
    for key, (input_price, output_price) in pricing.items():
        if key in model_lower:
            cost = (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
            return round(cost, 6)

    # 默认使用 DeepSeek 价格
    return round((prompt_tokens * 0.14 + completion_tokens * 0.28) / 1_000_000, 6)
