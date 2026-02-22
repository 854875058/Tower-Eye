"""
表头码表生成器 — 从 DuckDB (Lance 表) 提取字段信息 + 示例值

用途：
- 为 LLM NL2SQL 提供精确的 schema 描述
- 包含字段名、类型、中文含义、示例值/枚举值
- 结果缓存，避免重复查询
"""

from functools import lru_cache
from typing import Dict, List, Tuple

from poc.pipeline.utils import resolve_path

# ── 字段中文含义映射 ──────────────────────────────────────────────
COLUMN_DESCRIPTIONS: Dict[str, str] = {
    # events 表
    "event_id": "事件ID(主键)",
    "asset_id": "关联资产ID",
    "event_type": "告警类型",
    "alarm_level": "告警等级",
    "alarm_source": "告警来源",
    "alarm_time": "告警时间(格式: YYYY-MM-DD HH:MM:SS)",
    "lat": "纬度",
    "lon": "经度",
    "region": "区域",
    "extra_json": "扩展JSON数据",
    "summary": "AI图像理解描述",
    "description": "告警描述",
    "address": "详细地址",
    "province_name": "省份",
    "city_name": "城市",
    "county_name": "区/县",
    "town_code": "街道编码",
    "town_name": "街道/乡镇",
    "device_code": "设备编码",
    "device_name": "设备名称",
    "channel_code": "通道编码",
    "channel_name": "通道名称",
    "algorithm_code": "算法编码",
    "algorithm_name": "算法名称",
    "order_status": "工单状态(1=待处理,2=处理中,4=已完成,6=已关闭)",
    "confidence_level": "置信度(0-1)",
    "confidence_level_max": "最大置信度(0-1)",
    "emergency_level": "紧急等级(1=一般)",
    "importance_level": "重要等级(1=普通,2=重要)",
    "tenant_name": "租户名称",
    "video_path": "视频本地路径",
    "img_src_path": "原图本地路径",
    "img_icon_path": "缩略图路径",
    "warning_order_id": "告警工单ID",
    "warning_type_id": "告警类型ID",
    "alarm_body": "告警主体",
    # assets 表
    "file_path": "图片文件路径",
    "file_name": "文件名",
    "captured_at": "拍摄时间",
    "media_type": "媒体类型",
    "source": "数据来源",
}

# 枚举字段 — 这些字段用 SELECT DISTINCT 获取全部值而非采样
ENUM_FIELDS = {
    "order_status",
    "emergency_level",
    "importance_level",
    "alarm_level",
    "media_type",
    "source",
}

# 表中文名映射
TABLE_DESCRIPTIONS: Dict[str, str] = {
    "events": "告警事件表",
    "assets": "资产/图片表",
}

# 需要关注的表（白名单）
TARGET_TABLES = ["events", "assets"]


def _get_table_columns(engine, table: str) -> List[Tuple[str, str]]:
    """获取表的列名和类型（从 DuckDB information_schema）"""
    rows = engine.con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ?", [table]
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _get_sample_values(engine, table: str, column: str,
                       is_enum: bool = False, limit: int = 5) -> str:
    """获取字段的示例值或枚举值"""
    try:
        if is_enum:
            rows = engine.con.execute(
                f'SELECT DISTINCT "{column}" FROM {table} '
                f'WHERE "{column}" IS NOT NULL AND CAST("{column}" AS VARCHAR) <> \'\' '
                f'ORDER BY "{column}"'
            ).fetchall()
        else:
            rows = engine.con.execute(
                f'SELECT DISTINCT "{column}" FROM {table} '
                f'WHERE "{column}" IS NOT NULL AND CAST("{column}" AS VARCHAR) <> \'\' '
                f'ORDER BY "{column}" LIMIT {limit}'
            ).fetchall()
        values = [str(r[0]) for r in rows if r[0] is not None]
        if not values:
            return ""
        truncated = []
        for v in values:
            if len(v) > 30:
                truncated.append(v[:27] + "...")
            else:
                truncated.append(v)
        return ", ".join(truncated)
    except Exception:
        return ""


def _build_table_prompt(engine, table: str) -> str:
    """为单个表生成码表文本"""
    table_desc = TABLE_DESCRIPTIONS.get(table, table)
    columns = _get_table_columns(engine, table)

    lines = [
        f"## 表: {table} ({table_desc})",
        "| 列名 | 类型 | 中文含义 | 示例值 |",
        "|------|------|----------|--------|",
    ]

    for col_name, col_type in columns:
        desc = COLUMN_DESCRIPTIONS.get(col_name, "")
        is_enum = col_name in ENUM_FIELDS
        samples = _get_sample_values(engine, table, col_name, is_enum=is_enum)
        lines.append(f"| {col_name} | {col_type} | {desc} | {samples} |")

    return "\n".join(lines)


@lru_cache(maxsize=4)
def build_schema_prompt(db_path: str) -> str:
    """
    从 DuckDB (Lance 表) 生成完整的 schema 码表文本。

    Args:
        db_path: LanceDB 目录路径或旧 SQLite 路径（兼容，会自动转为 LanceDB 路径）

    Returns:
        Markdown 格式的码表描述字符串
    """
    from poc.search.duckdb_engine import get_duckdb_engine

    # 兼容旧调用：如果传入的是 .db 文件路径，自动转为 LanceDB 目录
    p = resolve_path(db_path)
    if p.suffix == ".db":
        lancedb_dir = p.parent / "lancedb"
    else:
        lancedb_dir = p

    engine = get_duckdb_engine(str(lancedb_dir))

    # 数据统一在 embeddings 表中，通过 events/assets 视图暴露
    # 只展示 events 视图给 LLM（包含所有字段）
    parts = []
    for table in TARGET_TABLES:
        try:
            cols = _get_table_columns(engine, table)
            if cols:
                parts.append(_build_table_prompt(engine, table))
        except Exception:
            pass
    return "\n\n".join(parts)
