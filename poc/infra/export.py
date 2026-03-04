"""
用户体验优化工具模块

功能：
1. 结果导出（Excel/CSV）
2. 搜索建议/自动补全
3. 查询模板管理
"""

import csv
import io
from datetime import datetime
from typing import Any, Dict, List


def export_to_csv(data: List[Dict[str, Any]], filename: str = None) -> bytes:
    """
    导出数据为 CSV 格式

    Args:
        data: 数据列表
        filename: 文件名（可选）

    Returns:
        CSV 文件的字节内容
    """
    if not data:
        return b""

    output = io.StringIO()

    # 获取所有列名
    fieldnames = list(data[0].keys())

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for row in data:
        # 过滤掉不可序列化的字段
        clean_row = {}
        for key, value in row.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                clean_row[key] = value
            else:
                clean_row[key] = str(value)
        writer.writerow(clean_row)

    return output.getvalue().encode('utf-8-sig')  # 使用 BOM 以便 Excel 正确识别


def export_to_excel(data: List[Dict[str, Any]], filename: str = None) -> bytes:
    """
    导出数据为 Excel 格式（需要 openpyxl）

    Args:
        data: 数据列表
        filename: 文件名（可选）

    Returns:
        Excel 文件的字节内容
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        # 如果没有 openpyxl，降级为 CSV
        return export_to_csv(data, filename)

    if not data:
        return b""

    wb = Workbook()
    ws = wb.active
    ws.title = "查询结果"

    # 写入表头
    fieldnames = list(data[0].keys())
    for col_idx, field in enumerate(fieldnames, start=1):
        cell = ws.cell(row=1, column=col_idx, value=field)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")

    # 写入数据
    for row_idx, row in enumerate(data, start=2):
        for col_idx, field in enumerate(fieldnames, start=1):
            value = row.get(field)
            if isinstance(value, (str, int, float, bool)) or value is None:
                ws.cell(row=row_idx, column=col_idx, value=value)
            else:
                ws.cell(row=row_idx, column=col_idx, value=str(value))

    # 保存到字节流
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


# 预定义查询模板
QUERY_TEMPLATES = {
    "统计分析": [
        "按街道统计最近30天各类告警数量",
        "统计各设备触发告警次数最多的TOP10",
        "按告警类型统计最近7天的数量分布",
        "按区县统计告警数量排名",
    ],
    "详细查询": [
        "查询最近20条车辆闯入告警的详细信息",
        "查询置信度大于0.9的高置信告警",
        "查询最近24小时的所有告警",
        "查询特定设备的历史告警记录",
    ],
    "视觉搜索": [
        "找红色挖掘机的图片",
        "找工地上有卡车的图片",
        "找停在路边的车辆",
        "找施工现场的照片",
    ],
    "地理位置": [
        "查询某个街道的告警分布",
        "查询某个区县的告警热点",
        "查询距离某个坐标5公里内的告警",
    ]
}


def get_query_templates(category: str = None) -> Dict[str, List[str]]:
    """
    获取查询模板

    Args:
        category: 类别名称（可选），如果不指定则返回所有

    Returns:
        查询模板字典
    """
    if category:
        return {category: QUERY_TEMPLATES.get(category, [])}
    return QUERY_TEMPLATES


def get_search_suggestions(query: str, history: List[str] = None, limit: int = 5) -> List[str]:
    """
    获取搜索建议（基于历史查询和模板）

    Args:
        query: 当前查询文本
        history: 历史查询列表
        limit: 返回建议数量

    Returns:
        建议列表
    """
    suggestions = []

    # 1. 从历史查询中匹配
    if history:
        for h in reversed(history):  # 最近的优先
            if query.lower() in h.lower() and h not in suggestions:
                suggestions.append(h)
                if len(suggestions) >= limit:
                    return suggestions

    # 2. 从模板中匹配
    for category, templates in QUERY_TEMPLATES.items():
        for template in templates:
            if query.lower() in template.lower() and template not in suggestions:
                suggestions.append(template)
                if len(suggestions) >= limit:
                    return suggestions

    return suggestions


def format_sql_explain(sql: str, explain_result: List[Dict] = None) -> str:
    """
    格式化 SQL 执行计划

    Args:
        sql: SQL 语句
        explain_result: EXPLAIN 结果

    Returns:
        格式化的执行计划文本
    """
    output = []
    output.append("=== SQL 执行计划 ===")
    output.append(f"SQL: {sql}")
    output.append("")

    if explain_result:
        output.append("执行步骤：")
        for idx, step in enumerate(explain_result, start=1):
            output.append(f"{idx}. {step}")
    else:
        output.append("（执行计划不可用）")

    return "\n".join(output)
