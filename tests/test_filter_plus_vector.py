"""
测试：高级筛选 + 文字描述同时使用时，向量检索能否返回结果

复现 Bug：
  - 用户在多模态检索页面同时设置高级筛选条件（如 event_type）和输入文字描述
  - 预期返回匹配筛选条件的向量检索结果
  - 实际返回 0 条（修复前）

根因：
  1. hybrid_search candidate_k 硬上限 100，filter 后所剩无几
  2. 预筛选 ID > 100 时走 post-filter，但 hybrid_search 内部先截断再 post-filter，交集为空

修复：
  1. hybrid_search 去掉 100 硬上限，有 filter 时加大候选池
  2. lance_filter 阈值从 100 提到 1000
  3. post-filter 路径加大 fetch_k
"""
import sys
import tempfile
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

# ── 项目根目录加入 sys.path ──
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Mock LanceDB table ──
class MockSearchBuilder:
    """模拟 LanceDB search().limit().where().to_pandas() 链式调用"""

    def __init__(self, df, query_vec):
        self._df = df.copy()
        self._limit = len(df)
        self._where = None
        self._query_vec = query_vec

    def limit(self, n):
        self._limit = n
        return self

    def where(self, condition):
        self._where = condition
        return self

    def to_pandas(self):
        df = self._df.copy()
        if self._where:
            # 解析 "asset_id IN ('id1','id2',...)" 条件
            if "asset_id IN" in self._where:
                import re
                ids = re.findall(r"'([^']*)'", self._where)
                df = df[df["asset_id"].isin(ids)]
        # 计算伪距离（用欧氏距离）
        vecs = np.stack(df["vector"].values)
        dists = np.linalg.norm(vecs - self._query_vec, axis=1)
        df = df.copy()
        df["_distance"] = dists
        df = df.sort_values("_distance").head(self._limit)
        return df


class MockTable:
    """模拟 LanceDB table"""

    def __init__(self, data):
        self._df = pd.DataFrame(data)

    def search(self, query_vec):
        return MockSearchBuilder(self._df, np.array(query_vec))


# ── 构造测试数据 ──
DIM = 8
np.random.seed(42)


def _make_records(n, event_type, city_name, prefix="id"):
    """生成 n 条指定 event_type/city_name 的记录，向量随机"""
    records = []
    for i in range(n):
        records.append({
            "asset_id": f"{prefix}_{event_type}_{i}",
            "file_path": f"/fake/{prefix}_{i}.jpg",
            "file_name": f"{prefix}_{i}.jpg",
            "vector": np.random.randn(DIM).astype("float32").tolist(),
            "event_type": event_type,
            "city_name": city_name,
            "county_name": "",
            "town_name": "",
            "alarm_level": "low",
            "alarm_time": "2026-02-20 10:00:00",
            "summary": f"{event_type} at {city_name}",
            "description": "",
            "address": "",
            "device_name": "",
            "confidence_level": 0.8,
            "order_status": "",
            "importance_level": "",
            "alarm_source": "",
            "alarm_body": "",
            "tenant_name": "",
            "channel_name": "",
            "algorithm_name": "",
            "algorithm_code": "",
            "device_code": "",
            "extra_json": "",
        })
    return records


def build_test_data():
    """构造混合数据集：多种 event_type，模拟真实场景"""
    data = []
    data.extend(_make_records(50, "vehicle_intrusion", "city_A", "a"))
    data.extend(_make_records(50, "fire_alarm", "city_B", "b"))
    data.extend(_make_records(200, "person_intrusion", "city_A", "c"))  # > 100 条
    data.extend(_make_records(30, "vehicle_intrusion", "city_C", "d"))
    return data


# ── 测试用例 ──

def test_hybrid_search_with_filter_returns_results():
    """hybrid_search + lance_filter: 应返回匹配 filter 的结果"""
    from poc.search.query import hybrid_search, build_asset_id_filter

    data = build_test_data()
    table = MockTable(data)
    query_vec = np.random.randn(DIM).astype("float32")

    # 筛选 vehicle_intrusion 的 asset_id（共 80 条，<= 1000 走 lance_filter）
    target_ids = [r["asset_id"] for r in data if r["event_type"] == "vehicle_intrusion"]
    lance_filter = build_asset_id_filter(target_ids)

    results_df = hybrid_search(
        table, query_vec, query_text="vehicle intrusion",
        top_k=10, filter_str=lance_filter,
    )

    assert len(results_df) > 0, "hybrid_search + filter should return results"
    # 所有结果的 asset_id 都应在 target_ids 中
    for aid in results_df["asset_id"].tolist():
        assert aid in target_ids, f"Result {aid} not in filtered set"
    print(f"[PASS] test_hybrid_search_with_filter_returns_results: {len(results_df)} results")


def test_hybrid_search_no_hardcap_100():
    """验证 candidate_k 不再被硬限制为 100"""
    from poc.search.query import hybrid_search

    # 构造 200 条同类数据
    data = _make_records(200, "test_event", "city_X", "x")
    table = MockTable(data)
    query_vec = np.random.randn(DIM).astype("float32")

    # top_k=50, 无 filter 时 candidate_k = 50*5 = 250 (旧代码 min(250,100)=100)
    results_df = hybrid_search(
        table, query_vec, query_text="test event",
        top_k=50, filter_str=None,
    )
    assert len(results_df) == 50, f"Expected 50 results, got {len(results_df)}"
    print(f"[PASS] test_hybrid_search_no_hardcap_100: {len(results_df)} results")


def test_post_filter_path_returns_results():
    """模拟 > 1000 条预筛选 ID 走 post-filter 路径"""
    from poc.search.query import hybrid_search

    # 构造 1500 条数据，其中 1200 条是目标类型
    data = _make_records(1200, "target_event", "city_Y", "t")
    data.extend(_make_records(300, "other_event", "city_Z", "o"))
    table = MockTable(data)
    query_vec = np.random.randn(DIM).astype("float32")

    target_ids = {r["asset_id"] for r in data if r["event_type"] == "target_event"}
    top_k = 10

    # 模拟 do_search 中 post-filter 路径的逻辑
    # > 1000 条 -> post_filter_ids, fetch_k 加大
    fetch_k = max(top_k * 5 * 5, top_k * 10)  # 修复后的逻辑
    results_df = hybrid_search(
        table, query_vec, query_text="target event",
        top_k=fetch_k, filter_str=None,
    )
    # post-filter
    results_df = results_df[results_df["asset_id"].isin(target_ids)]
    results_df = results_df.head(top_k)

    assert len(results_df) > 0, "post-filter path should return results"
    for aid in results_df["asset_id"].tolist():
        assert aid in target_ids, f"Result {aid} not in target set"
    print(f"[PASS] test_post_filter_path_returns_results: {len(results_df)} results")


def test_lance_filter_threshold_1000():
    """验证 <= 1000 条预筛选 ID 走 lance_filter 而非 post-filter"""
    from poc.search.query import build_asset_id_filter

    # 500 条 -> 应该生成 lance_filter
    ids_500 = [f"id_{i}" for i in range(500)]
    f = build_asset_id_filter(ids_500)
    assert f is not None, "500 IDs should produce a lance_filter"
    assert "asset_id IN" in f

    # 1000 条 -> 仍应生成 lance_filter
    ids_1000 = [f"id_{i}" for i in range(1000)]
    f = build_asset_id_filter(ids_1000)
    assert f is not None, "1000 IDs should produce a lance_filter"
    print("[PASS] test_lance_filter_threshold_1000")


def test_filter_only_no_text():
    """纯筛选无文字：走 SQL 路径，不应受向量检索影响"""
    from poc.app.pages.shared import build_sqlite_filter

    filters = {"event_type": "vehicle_intrusion", "city_name": "city_A"}
    where_extra, params = build_sqlite_filter(filters)
    assert "event_type LIKE" in where_extra
    assert "city_name LIKE" in where_extra
    assert len(params) == 2
    print("[PASS] test_filter_only_no_text")


def test_build_sqlite_filter_empty():
    """空筛选条件应返回空字符串"""
    from poc.app.pages.shared import build_sqlite_filter

    where_extra, params = build_sqlite_filter({})
    assert where_extra == ""
    assert params == []
    print("[PASS] test_build_sqlite_filter_empty")


if __name__ == "__main__":
    test_hybrid_search_with_filter_returns_results()
    test_hybrid_search_no_hardcap_100()
    test_post_filter_path_returns_results()
    test_lance_filter_threshold_1000()
    test_filter_only_no_text()
    test_build_sqlite_filter_empty()
    print("\n=== ALL TESTS PASSED ===")
