"""
DuckDB 引擎 — 基于 Lance 表的统一 SQL 查询接口

将 LanceDB embeddings 表加载为 Arrow 数据，注册到 DuckDB 内存中，
替代 SQLite 提供结构化查询能力。与 LanceDB 向量检索共享同一份数据。
"""
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

try:
    import lancedb
except ImportError:
    lancedb = None

_lock = threading.Lock()
_engine: Optional["DuckDBEngine"] = None


class DuckDBEngine:
    """DuckDB 查询引擎 — 从 Lance 表加载数据"""

    def __init__(self, lancedb_dir: str, table_name: str = "embeddings"):
        self._lancedb_dir = str(lancedb_dir)
        self._table_name = table_name
        self._con: Optional[duckdb.DuckDBPyConnection] = None
        self._reload()

    def _reload(self):
        """从 LanceDB 加载 Arrow 数据注册到 DuckDB"""
        if lancedb is None:
            raise RuntimeError("lancedb is required")
        db = lancedb.connect(self._lancedb_dir)
        table = db.open_table(self._table_name)
        arrow_table = table.to_arrow()
        # 去掉 vector 列（DuckDB 不需要）
        if "vector" in arrow_table.column_names:
            arrow_table = arrow_table.drop("vector")
        self._con = duckdb.connect(":memory:")
        self._con.register("embeddings", arrow_table)
        # 创建视图别名，兼容原有 events/assets 的 SQL
        self._con.execute("""
            CREATE OR REPLACE VIEW events AS SELECT * FROM embeddings
        """)
        self._con.execute("""
            CREATE OR REPLACE VIEW assets AS SELECT * FROM embeddings
        """)

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            self._reload()
        return self._con

    def execute(self, sql: str, params: Optional[List] = None) -> List[Dict[str, Any]]:
        """执行 SQL 查询，返回 List[Dict]"""
        try:
            if params:
                result = self.con.execute(sql, params)
            else:
                result = self.con.execute(sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            raise RuntimeError(f"DuckDB query failed: {e}") from e

    def execute_df(self, sql: str, params: Optional[List] = None):
        """执行 SQL 查询，返回 pandas DataFrame"""
        if params:
            return self.con.execute(sql, params).fetchdf()
        return self.con.execute(sql).fetchdf()

    def reload(self):
        """重新加载 Lance 数据（数据更新后调用）"""
        self._reload()

    def table_info(self) -> List[Tuple[str, str]]:
        """返回表的列名和类型"""
        rows = self.con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'embeddings'"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def count(self, table: str = "embeddings") -> int:
        """返回行数"""
        return self.con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def distinct_values(self, column: str, table: str = "embeddings",
                        limit: int = 50) -> List[str]:
        """获取某列的去重值"""
        rows = self.con.execute(
            f'SELECT DISTINCT "{column}" FROM {table} '
            f'WHERE "{column}" IS NOT NULL AND CAST("{column}" AS VARCHAR) <> \'\' '
            f'ORDER BY "{column}" LIMIT ?',
            [limit]
        ).fetchall()
        return [str(r[0]) for r in rows]


def get_duckdb_engine(lancedb_dir: str, table_name: str = "embeddings") -> DuckDBEngine:
    """获取全局单例 DuckDB 引擎"""
    global _engine
    with _lock:
        if _engine is None:
            _engine = DuckDBEngine(lancedb_dir, table_name)
        return _engine


def reset_engine():
    """重置引擎（数据迁移后调用）"""
    global _engine
    with _lock:
        _engine = None
