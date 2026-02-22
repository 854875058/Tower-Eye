"""
语义层 - Tool 抽象

功能：
1. 将复杂的 SQL 查询封装成语义化的 Tool 函数
2. 隐藏底层数据库表结构和 Join 逻辑
3. 提供统一的接口给 Agent 调用
4. 支持参数验证和错误处理
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from poc.pipeline.utils import resolve_path
from poc.qa.guardrails import SQLGuardrail
from poc.search.duckdb_engine import get_duckdb_engine


@dataclass
class ToolResult:
    """Tool 执行结果"""
    success: bool
    data: Any
    error: Optional[str] = None
    metadata: Optional[Dict] = None


class SemanticTool:
    """语义层 Tool 基类"""

    def __init__(self, db_path: str):
        self.db_path = resolve_path(db_path)
        # 兼容：如果传入 .db 路径，自动转为 LanceDB 目录
        if self.db_path.suffix == ".db":
            self._lancedb_dir = str(self.db_path.parent / "lancedb")
        else:
            self._lancedb_dir = str(self.db_path)

    def _execute_query(self, sql: str, params: List) -> List[Dict]:
        """安全执行查询（通过 DuckDB）"""
        # 安全检查
        SQLGuardrail.validate_sql(sql)
        params = SQLGuardrail.sanitize_params(params)

        engine = get_duckdb_engine(self._lancedb_dir)
        return engine.execute(sql, params)

    def execute(self, **kwargs) -> ToolResult:
        """执行 Tool（子类实现）"""
        raise NotImplementedError


class GetVehicleCountTool(SemanticTool):
    """获取车辆数量统计"""

    name = "get_vehicle_count"
    description = "统计指定条件下的车辆数量（支持时间范围、地点、告警类型过滤）"

    def execute(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        event_type: Optional[str] = None,
        address: Optional[str] = None,
        channel_name: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """
        执行车辆统计查询

        Args:
            start_time: 开始时间（ISO格式）
            end_time: 结束时间（ISO格式）
            event_type: 告警类型（如 "车辆闯入监控告警"）
            address: 地址关键词（模糊匹配）
            channel_name: 通道名称关键词（模糊匹配）

        Returns:
            ToolResult 包含统计数量
        """
        try:
            where_clauses = []
            params = []

            # 时间过滤
            if start_time:
                where_clauses.append("e.alarm_time >= ?")
                params.append(start_time)
            if end_time:
                where_clauses.append("e.alarm_time <= ?")
                params.append(end_time)

            # 告警类型过滤
            if event_type:
                where_clauses.append("e.event_type = ?")
                params.append(event_type)

            # 地址模糊匹配
            if address:
                where_clauses.append("(a.address LIKE ? OR e.extra_json LIKE ?)")
                params.extend([f"%{address}%", f"%{address}%"])

            # 通道名称模糊匹配
            if channel_name:
                where_clauses.append("e.extra_json LIKE ?")
                params.append(f'%"channel_name":"%{channel_name}%"%')

            where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            sql = f"""
                SELECT COUNT(*) AS cnt
                FROM events e
                LEFT JOIN assets a ON e.asset_id = a.asset_id
                {where_sql}
            """

            rows = self._execute_query(sql, params)
            count = rows[0]["cnt"] if rows else 0

            return ToolResult(
                success=True,
                data={"count": count},
                metadata={"sql": sql, "params": params}
            )

        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class GetAlarmListTool(SemanticTool):
    """获取告警列表"""

    name = "get_alarm_list"
    description = "查询告警事件列表（支持分页、排序、多条件过滤）"

    def execute(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        event_type: Optional[str] = None,
        address: Optional[str] = None,
        channel_name: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "alarm_time",
        order_direction: str = "DESC",
        **kwargs
    ) -> ToolResult:
        """
        执行告警列表查询

        Args:
            start_time: 开始时间
            end_time: 结束时间
            event_type: 告警类型
            address: 地址关键词
            channel_name: 通道名称关键词
            limit: 返回数量限制
            offset: 偏移量（分页）
            order_by: 排序字段
            order_direction: 排序方向（ASC/DESC）

        Returns:
            ToolResult 包含告警列表
        """
        try:
            where_clauses = []
            params = []

            # 时间过滤
            if start_time:
                where_clauses.append("e.alarm_time >= ?")
                params.append(start_time)
            if end_time:
                where_clauses.append("e.alarm_time <= ?")
                params.append(end_time)

            # 告警类型过滤
            if event_type:
                where_clauses.append("e.event_type = ?")
                params.append(event_type)

            # 地址模糊匹配
            if address:
                where_clauses.append("(a.address LIKE ? OR e.extra_json LIKE ?)")
                params.extend([f"%{address}%", f"%{address}%"])

            # 通道名称模糊匹配
            if channel_name:
                where_clauses.append("e.extra_json LIKE ?")
                params.append(f'%"channel_name":"%{channel_name}%"%')

            where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            # 验证排序字段（防止注入）
            allowed_order_fields = ["alarm_time", "event_type", "event_id"]
            if order_by not in allowed_order_fields:
                order_by = "alarm_time"

            # 验证排序方向
            order_direction = order_direction.upper()
            if order_direction not in ["ASC", "DESC"]:
                order_direction = "DESC"

            sql = f"""
                SELECT
                    e.event_id,
                    e.event_type,
                    e.alarm_time,
                    e.alarm_level,
                    e.alarm_source,
                    a.file_path,
                    a.file_name,
                    a.lat,
                    a.lon,
                    a.address
                FROM events e
                LEFT JOIN assets a ON e.asset_id = a.asset_id
                {where_sql}
                ORDER BY e.{order_by} {order_direction}
                LIMIT ? OFFSET ?
            """

            params.extend([limit, offset])
            rows = self._execute_query(sql, params)

            return ToolResult(
                success=True,
                data={"alarms": rows, "count": len(rows)},
                metadata={"sql": sql, "limit": limit, "offset": offset}
            )

        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class GetLocationInfoTool(SemanticTool):
    """获取地点信息（用于地址解析）"""

    name = "get_location_info"
    description = "根据地点名称查询数据库中的真实地址和坐标信息"

    def execute(self, location_keyword: str, limit: int = 10, **kwargs) -> ToolResult:
        """
        查询地点信息

        Args:
            location_keyword: 地点关键词（如 "滨南东路"）
            limit: 返回数量限制

        Returns:
            ToolResult 包含匹配的地址列表
        """
        try:
            # 从 assets 表查询地址
            sql_assets = """
                SELECT DISTINCT
                    address,
                    lat,
                    lon,
                    COUNT(*) as count
                FROM assets
                WHERE address LIKE ?
                GROUP BY address, lat, lon
                ORDER BY count DESC
                LIMIT ?
            """

            # 从 events 表的 extra_json 查询通道名称
            sql_events = """
                SELECT DISTINCT
                    extra_json,
                    COUNT(*) as count
                FROM events
                WHERE extra_json LIKE ?
                GROUP BY extra_json
                ORDER BY count DESC
                LIMIT ?
            """

            keyword_pattern = f"%{location_keyword}%"

            # 查询 assets
            assets_rows = self._execute_query(sql_assets, [keyword_pattern, limit])

            # 查询 events（简化处理，实际应该解析 JSON）
            events_rows = self._execute_query(sql_events, [keyword_pattern, limit])

            # 合并结果
            locations = []
            for row in assets_rows:
                locations.append({
                    "address": row["address"],
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "source": "assets",
                    "frequency": row["count"]
                })

            return ToolResult(
                success=True,
                data={"locations": locations, "count": len(locations)},
                metadata={"keyword": location_keyword}
            )

        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class GetTimeRangeStatsTool(SemanticTool):
    """获取时间段统计（按小时/天/月聚合）"""

    name = "get_time_range_stats"
    description = "统计指定时间范围内的告警数量分布（按时间粒度聚合）"

    def execute(
        self,
        start_time: str,
        end_time: str,
        granularity: str = "hour",  # hour, day, month
        event_type: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """
        执行时间段统计

        Args:
            start_time: 开始时间
            end_time: 结束时间
            granularity: 时间粒度（hour/day/month）
            event_type: 告警类型过滤

        Returns:
            ToolResult 包含时间序列统计数据
        """
        try:
            # 根据粒度选择时间格式化函数
            time_format_map = {
                "hour": "%Y-%m-%d %H:00:00",
                "day": "%Y-%m-%d",
                "month": "%Y-%m"
            }

            time_format = time_format_map.get(granularity, "%Y-%m-%d %H:00:00")

            where_clauses = ["alarm_time >= ?", "alarm_time <= ?"]
            params = [start_time, end_time]

            if event_type:
                where_clauses.append("event_type = ?")
                params.append(event_type)

            where_sql = " WHERE " + " AND ".join(where_clauses)

            sql = f"""
                SELECT
                    strftime('{time_format}', alarm_time) as time_bucket,
                    COUNT(*) as count
                FROM events
                {where_sql}
                GROUP BY time_bucket
                ORDER BY time_bucket
            """

            rows = self._execute_query(sql, params)

            return ToolResult(
                success=True,
                data={"time_series": rows, "granularity": granularity},
                metadata={"sql": sql}
            )

        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class ToolRegistry:
    """Tool 注册中心"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.tools: Dict[str, SemanticTool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """注册默认 Tools"""
        self.register(GetVehicleCountTool(self.db_path))
        self.register(GetAlarmListTool(self.db_path))
        self.register(GetLocationInfoTool(self.db_path))
        self.register(GetTimeRangeStatsTool(self.db_path))

    def register(self, tool: SemanticTool):
        """注册 Tool"""
        self.tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[SemanticTool]:
        """获取 Tool"""
        return self.tools.get(name)

    def list_tools(self) -> List[Dict[str, str]]:
        """列出所有 Tools"""
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self.tools.values()
        ]

    def execute_tool(self, name: str, **kwargs) -> ToolResult:
        """执行 Tool"""
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(success=False, data=None, error=f"Tool '{name}' not found")
        return tool.execute(**kwargs)


# 全局单例
_tool_registry: Optional[ToolRegistry] = None


def init_tool_registry(db_path: str):
    """初始化全局 Tool 注册中心"""
    global _tool_registry
    _tool_registry = ToolRegistry(db_path)


def get_tool_registry() -> Optional[ToolRegistry]:
    """获取全局 Tool 注册中心"""
    return _tool_registry
