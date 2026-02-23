import calendar
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests


SCENE_KEYWORDS = {
    # 车辆相关告警场景
    "车辆闯入监控": "车辆闯入监控告警",
    "车辆闯入": "车辆闯入监控告警",
    "车辆闯红灯": "车辆闯红灯监控告警",
    "危险车辆": "危险车辆识别告警",
    "车辆分类": "车辆分类告警",
    "工程车辆识别": "工程车辆识别检测告警",
    "工程车辆": "工程车辆识别检测告警",
    "车辆闯入检测": "车辆闯入检测告警",
}


@dataclass
class QueryPlan:
    intent: str
    sql: str
    params: List
    filters: Dict


def _parse_top_k(text: str, default: int = 20) -> int:
    match = re.search(r"(前|top|TOP)\s*(\d+)", text)
    if match:
        return int(match.group(2))
    match = re.search(r"(\d+)\s*条", text)
    if match:
        return int(match.group(1))
    return default


def _parse_time_range(text: str) -> Tuple[Optional[str], Optional[str]]:
    # 1) 精确日期范围: 2025-01-01 ~ 2025-01-31
    date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if len(date_matches) >= 2:
        return date_matches[0] + " 00:00:00", date_matches[1] + " 23:59:59"

    # 2) "近N天/小时"
    match = re.search(r"近(\d+)(天|小时)", text)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        end = datetime.now()
        start = end - (timedelta(days=value) if unit == "天" else timedelta(hours=value))
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")

    # 3) "YYYY年M月" — 整月范围
    match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        _, last_day = calendar.monthrange(year, month)
        return f"{year}-{month:02d}-01 00:00:00", f"{year}-{month:02d}-{last_day} 23:59:59"

    # 4) "最近N天"
    match = re.search(r"最近(\d+)(天|小时)", text)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        end = datetime.now()
        start = end - (timedelta(days=value) if unit == "天" else timedelta(hours=value))
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")

    return None, None


def _parse_location(text: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    lat = None
    lon = None
    radius = None
    lat_match = re.search(r"lat\s*=\s*([0-9.]+)", text, re.IGNORECASE)
    lon_match = re.search(r"lon\s*=\s*([0-9.]+)", text, re.IGNORECASE)
    if lat_match:
        lat = float(lat_match.group(1))
    if lon_match:
        lon = float(lon_match.group(1))
    radius_match = re.search(r"(\d+)\s*公里", text)
    if radius_match:
        radius = float(radius_match.group(1))
    return lat, lon, radius


_CHAT_PATTERNS = [
    # 问候
    "你好", "您好", "hello", "hi", "嗨", "hey",
    # 感谢/告别
    "谢谢", "感谢", "再见", "拜拜", "bye",
    # 自我介绍/能力询问
    "你是谁", "你叫什么", "你能做什么", "你会什么", "怎么用", "使用说明", "帮助",
    # 纯闲聊
    "今天天气", "讲个笑话", "你好吗",
]

# 数据库查询关键词 — 只要命中任意一个就不是闲聊
_QUERY_KEYWORDS = [
    "查询", "查看", "搜索", "查找", "查一下", "找一下", "列出",
    "统计", "多少", "数量", "总数", "分布", "TOP", "top", "排名",
    "告警", "事件", "设备", "街道", "区县", "置信度", "工单",
    "最近", "今天", "昨天", "本月", "本周",
]


def _parse_intent(text: str) -> str:
    t = text.strip()
    # 先检查是否命中查询关键词（优先级最高）
    if any(k in t for k in _QUERY_KEYWORDS):
        if any(k in t for k in ["多少", "统计", "数量", "总数", "分布", "TOP", "top", "排名"]):
            return "count"
        return "list"
    # 再检查是否是闲聊
    t_lower = t.lower()
    if any(p in t_lower for p in _CHAT_PATTERNS):
        return "chat"
    # 短文本且无查询关键词 → 大概率闲聊
    if len(t) <= 6:
        return "chat"
    return "list"


def _parse_group_by(text: str) -> Optional[str]:
    """解析 GROUP BY 维度"""
    group_map = {
        "街道": ("town_name", "街道"),
        "乡镇": ("town_name", "街道"),
        "区": ("county_name", "区县"),
        "县": ("county_name", "区县"),
        "设备": ("device_name", "设备"),
        "算法": ("algorithm_name", "算法"),
        "类型": ("event_type", "告警类型"),
        "告警类型": ("event_type", "告警类型"),
    }
    for keyword, (col, alias) in group_map.items():
        if f"按{keyword}" in text or f"各{keyword}" in text:
            return col, alias
    return None


def _parse_area_name(text: str) -> Tuple[Optional[str], Optional[str]]:
    """从问题中提取地区名称（街道/乡镇、区/县）

    排除动词前缀（查询、统计、查看等），只提取地名本身。
    先移除数量词表达式（如"20条"、"10个"），防止量词被误识别为地名前缀。
    """
    town_name = None
    county_name = None

    # 先移除数量词表达式，避免"20条"的"条"被错误地包含到地名中
    cleaned = re.sub(r'\d+\s*[条个件次项篇张]', '', text)

    # 匹配 "XX街道" / "XX镇" / "XX乡"，排除前面的动词
    m = re.search(r"(?:查询|查看|统计|搜索|查|找)?([\u4e00-\u9fa5]{2,4}(?:街道|镇|乡))", cleaned)
    if m:
        town_name = m.group(1)

    # 匹配 "XX区" / "XX县"
    m = re.search(r"(?:查询|查看|统计|搜索|查|找)?([\u4e00-\u9fa5]{2,4}(?:区|县))", cleaned)
    if m:
        county_name = m.group(1)

    return town_name, county_name


def _parse_confidence(text: str) -> Optional[float]:
    """解析置信度条件，如 '置信度大于0.9' '置信度>0.8'"""
    m = re.search(r"置信度\s*(?:大于|>|>=|高于)\s*([0-9.]+)", text)
    if m:
        return float(m.group(1))
    m = re.search(r"高置信", text)
    if m:
        return 0.9  # 默认阈值
    return None


def parse_question(text: str) -> QueryPlan:
    intent = _parse_intent(text)

    # 闲聊意图：不生成 SQL
    if intent == "chat":
        return QueryPlan(intent="chat", sql="", params=[], filters={})

    event_type = None
    for key, value in SCENE_KEYWORDS.items():
        if key in text:
            event_type = value
            break

    start_time, end_time = _parse_time_range(text)
    top_k = _parse_top_k(text)
    lat, lon, radius_km = _parse_location(text)
    town_name, county_name = _parse_area_name(text)
    confidence_min = _parse_confidence(text)
    group_by_result = _parse_group_by(text)

    where = []
    params: List = []
    if event_type:
        where.append("event_type = ?")
        params.append(event_type)
    if start_time:
        where.append("alarm_time >= ?")
        params.append(start_time)
    if end_time:
        where.append("alarm_time <= ?")
        params.append(end_time)
    if town_name:
        where.append("town_name LIKE ?")
        params.append(f"%{town_name}%")
    if county_name:
        where.append("county_name LIKE ?")
        params.append(f"%{county_name}%")
    if confidence_min is not None:
        where.append("confidence_level >= ?")
        params.append(confidence_min)

    where_sql = " WHERE " + " AND ".join(where) if where else ""

    if intent == "count":
        # 动态 GROUP BY
        if group_by_result:
            group_col, group_alias = group_by_result
        else:
            group_col, group_alias = "event_type", "告警类型"
        sql = (
            f"SELECT {group_col} AS {group_alias}, COUNT(*) AS 数量 FROM events"
            + where_sql
            + f" GROUP BY {group_col} ORDER BY 数量 DESC"
        )
    else:
        sql = (
            "SELECT event_type AS 告警类型, alarm_time AS 告警时间, "
            "address AS 地址, town_name AS 街道, "
            "device_name AS 设备名称, algorithm_name AS 算法, "
            "order_status AS 工单状态, confidence_level AS 置信度, "
            "file_path AS 图片路径, video_path AS 视频路径 "
            "FROM events"
            + where_sql
            + " ORDER BY alarm_time DESC LIMIT ?"
        )
        params.append(top_k)

    filters = {
        "event_type": event_type,
        "start_time": start_time,
        "end_time": end_time,
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "top_k": top_k,
        "town_name": town_name,
        "county_name": county_name,
        "confidence_min": confidence_min,
    }

    return QueryPlan(intent=intent, sql=sql, params=params, filters=filters)


def _get_llm_config(config: Dict):
    """提取 LLM 连接配置（api_key, url, model）"""
    llm_cfg = config.get("llm", {})
    api_key = llm_cfg.get("api_key") or None
    if not api_key:
        api_key_env = llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")
        api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError("DEEPSEEK API key not configured (neither in config.llm.api_key nor environment).")

    base_url = os.getenv("DEEPSEEK_BASE_URL", llm_cfg.get("base_url", "https://api.deepseek.com"))
    model = os.getenv("DEEPSEEK_MODEL", llm_cfg.get("model", "deepseek-chat"))
    url = base_url.rstrip("/") + "/v1/chat/completions"
    timeout = llm_cfg.get("timeout", 30)

    return api_key, url, model, timeout


def _call_llm_chat(api_key: str, url: str, model: str, timeout: int,
                   system_prompt: str, user_prompt: str) -> str:
    """通用 LLM 调用，返回 content 文本"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def _parse_llm_json(content: str) -> dict:
    """从 LLM 输出中提取 JSON 对象（兼容 markdown 代码块）"""
    # 去掉 markdown 代码块包裹
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # 去掉首行 ```json 和末行 ```
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except Exception as exc:
        raise RuntimeError(f"LLM 输出不是有效 JSON: {content}") from exc


def _build_nl2sql_system_prompt(schema_prompt: str) -> str:
    """构建 NL2SQL 的 system prompt"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        "你是一个专业的 NL2SQL 助手，负责将中文自然语言问题转换为 DuckDB SQL 查询。\n\n"
        f"# 当前时间\n{now_str}\n"
        "所有涉及'最近N天'、'本月'、'今天'、'昨天'等相对时间的表达，都必须基于上面的当前时间计算。\n\n"
        "# 数据库 Schema\n"
        f"{schema_prompt}\n\n"
        "# 重要：数据库结构说明\n"
        "所有数据存储在一张统一的 `embeddings` 表中，`events` 和 `assets` 是该表的视图别名。\n"
        "你可以直接查询 `events` 表，无需 JOIN assets，因为所有字段（包括 file_path、file_name）都在同一张表中。\n"
        "示例：SELECT event_type, alarm_time, file_path FROM events WHERE ...\n\n"
        "# 实体提取规则（非常重要）\n"
        "在生成 SQL 前，你必须先从用户问题中正确提取实体：\n"
        "1. **区分量词和地名**：'20条'中的'条'是量词，不是地名的一部分。\n"
        "   - 正确：'查询最近20条新开口镇的告警' → town_name='新开口镇', LIMIT 20\n"
        "   - 错误：town_name='条新开口镇'\n"
        "2. **常见量词**：条、个、件、次、项、篇、张 — 这些紧跟数字时是数量单位，不是地名前缀。\n"
        "3. **地名后缀识别**：街道、镇、乡、区、县、市、省 — 这些是地名标志。\n"
        "4. **时间表达式**：'最近N天'、'本月'、'今天' 等需要转换为具体日期范围。\n"
        "5. **'最近N条' ≠ '最近N天'**：'最近20条'表示 ORDER BY ... DESC LIMIT 20，"
        "**绝对不要**添加时间过滤条件！只有明确说'最近N天/小时/月'时才添加时间过滤。\n"
        "   - 正确：'查询最近20条告警' → LIMIT 20，无 WHERE 时间条件\n"
        "   - 错误：'查询最近20条告警' → WHERE alarm_time >= date('now', '-20 days')\n"
        "6. **事件类型**：从用户描述中匹配 event_type 字段的枚举值。\n\n"
        "# intent 分类规则（必须遵守）\n"
        "- **count**：用户问'统计'、'数量'、'多少'、'分布'、'TOP'、'排名'，或 SQL 包含 COUNT/SUM/AVG + GROUP BY\n"
        "- **list**：用户问'查询'、'查看'、'详细信息'、'明细'，需要返回逐行记录\n"
        "- 例如：'按街道统计告警数量' → intent=count；'查询最近20条告警' → intent=list\n\n"
        "# SQL 生成规则\n"
        "1. 直接查询 `events` 表即可，所有字段都在这张表中，不需要 JOIN。\n"
        "2. 时间字段 `alarm_time` 格式为 `YYYY-MM-DD HH:MM:SS`，时间过滤用字符串比较即可。\n"
        "3. SQL 中的值必须用 `$1`, `$2`, ... 占位符（DuckDB 参数化查询），对应的值放在 params 数组中。\n"
        "4. 如果是列表查询（intent=list），SELECT 中必须包含 `file_path` 和 `video_path`，方便展示图片和视频。\n"
        "5. 如果是统计查询（intent=count），建议带 GROUP BY 分组维度和 ORDER BY 数量 DESC。\n"
        "6. 只允许 SELECT 查询，禁止 INSERT/UPDATE/DELETE/DROP 等写操作。\n"
        "7. 列表查询默认 LIMIT 20，除非用户指定了数量。\n"
        "8. town_name 匹配用 LIKE '%关键词%' 模糊匹配，关键词只包含纯地名。\n\n"
        "# 输出格式\n"
        "严格输出一个 JSON 对象，不要包含任何多余文字、注释或 markdown 代码块：\n"
        '{"intent": "count|list", "sql": "...", "params": [...], "filters": {...}}\n'
        "filters 包含: event_type, start_time, end_time, lat, lon, radius_km, top_k, "
        "town_name, county_name, confidence_min（值为 null 表示未指定）。"
    )


def _call_deepseek_nl2sql(question: str, config: Dict, fallback: QueryPlan) -> QueryPlan:
    from poc.qa.schema_meta import build_schema_prompt

    api_key, url, model, timeout = _get_llm_config(config)
    db_path = config.get("paths", {}).get("db_path", "poc/data/metadata.db")
    schema_prompt = build_schema_prompt(db_path)

    system_prompt = _build_nl2sql_system_prompt(schema_prompt)
    user_prompt = f"问题: {question}\n请直接输出 JSON。"

    content = _call_llm_chat(api_key, url, model, timeout, system_prompt, user_prompt)
    obj = _parse_llm_json(content)

    intent = obj.get("intent") or fallback.intent
    sql = obj.get("sql") or fallback.sql
    params = obj.get("params") or fallback.params
    filters = obj.get("filters") or fallback.filters

    # 确保 filters 至少包含必要键
    merged_filters = dict(fallback.filters)
    if isinstance(filters, dict):
        merged_filters.update(filters)

    return QueryPlan(intent=intent, sql=sql, params=params, filters=merged_filters)


def _auto_correct_intent(plan: QueryPlan) -> QueryPlan:
    """根据 SQL 内容自动纠正 intent。
    如果 SQL 包含聚合函数 + GROUP BY，intent 应该是 count 而非 list。
    """
    sql_upper = (plan.sql or "").upper()
    has_aggregate = any(fn in sql_upper for fn in ("COUNT(", "SUM(", "AVG("))
    has_group_by = "GROUP BY" in sql_upper
    if has_aggregate and has_group_by and plan.intent != "count":
        print(f"[auto_correct_intent] SQL 包含聚合+GROUP BY，intent 从 '{plan.intent}' 纠正为 'count'")
        plan.intent = "count"
    return plan


def _try_sql_cache(text: str, rule_plan: QueryPlan) -> Optional[QueryPlan]:
    """尝试从 trace DB 的 SQL 缓存中命中历史查询。

    命中后复用 SQL 模板（intent + sql 结构），但 params 由规则引擎
    根据当前时间重新提取，避免缓存的时间参数过期。
    """
    from poc.qa.trace import get_trace_manager

    manager = get_trace_manager()
    if not manager:
        return None

    cached = manager.lookup_sql_cache(text)
    if not cached:
        return None

    cached_intent, cached_sql = cached

    # 用规则引擎重新提取 params（时间、地名等实时参数）
    fresh_plan = parse_question(text)

    print(f"[sql_cache] HIT - intent={cached_intent}, reusing cached SQL template")
    return QueryPlan(
        intent=cached_intent,
        sql=cached_sql,
        params=fresh_plan.params,
        filters=fresh_plan.filters,
    )


def build_query_plan(text: str, config: Dict) -> QueryPlan:
    """构建查询计划: 根据配置选择规则引擎或 DeepSeek LLM。"""

    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled", False):
        print("[build_query_plan] LLM 未启用，使用规则引擎")
        return _auto_correct_intent(parse_question(text))

    mode = llm_cfg.get("mode", "rule")
    rule_plan = parse_question(text)

    # 闲聊意图直接返回，不调 LLM
    if rule_plan.intent == "chat":
        print("[build_query_plan] 识别为闲聊，跳过 LLM")
        return rule_plan

    if mode == "rule":
        return _auto_correct_intent(rule_plan)

    if mode in {"llm", "hybrid"}:
        # 先查 SQL 缓存，命中则跳过 LLM 调用
        cached_plan = _try_sql_cache(text, rule_plan)
        if cached_plan:
            return _auto_correct_intent(cached_plan)

        try:
            print(f"[build_query_plan] 调用 LLM ({mode} 模式)...")
            llm_plan = _call_deepseek_nl2sql(text, config, rule_plan)
            print(f"[build_query_plan] LLM 调用成功, intent={llm_plan.intent}")
            return _auto_correct_intent(llm_plan)
        except Exception as e:
            print(f"[build_query_plan] LLM 调用失败，降级为规则引擎: {e}")
            return _auto_correct_intent(rule_plan)

    return _auto_correct_intent(rule_plan)


def call_llm_fix_sql(question: str, failed_sql: str, error_msg: str,
                     config: Dict, db_path: str) -> QueryPlan:
    """
    调用 LLM 修正失败的 SQL。

    Args:
        question: 原始用户问题
        failed_sql: 执行失败的 SQL
        error_msg: 错误信息
        config: 全局配置
        db_path: 数据库路径

    Returns:
        修正后的 QueryPlan
    """
    from poc.qa.schema_meta import build_schema_prompt

    api_key, url, model, timeout = _get_llm_config(config)
    schema_prompt = build_schema_prompt(db_path)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    system_prompt = (
        "你是一个 SQL 修正助手。用户之前生成的 SQL 执行失败了，请根据错误信息修正 SQL。\n\n"
        f"# 当前时间\n{now_str}\n\n"
        "# 数据库 Schema\n"
        f"{schema_prompt}\n\n"
        "# 重要：数据库结构说明\n"
        "所有数据在一张统一的 `embeddings` 表中，`events` 和 `assets` 是该表的视图别名。\n"
        "直接查询 `events` 表即可，无需 JOIN，所有字段都在同一张表中。\n\n"
        "# 关键规则\n"
        "1. 直接查询 `events` 表，不需要 JOIN。\n"
        "2. 时间字段 `alarm_time` 格式为 `YYYY-MM-DD HH:MM:SS`。\n"
        "3. SQL 中的值必须用 `$1`, `$2`, ... 占位符（DuckDB 参数化查询），对应的值放在 params 数组中。\n"
        "4. 如果是列表查询，SELECT 中必须包含 `file_path` 和 `video_path`。\n"
        "5. 只允许 SELECT 查询。\n\n"
        "# 输出格式\n"
        "严格输出一个 JSON 对象：\n"
        '{"intent": "count|list", "sql": "...", "params": [...], "filters": {...}}\n'
    )

    user_prompt = (
        f"原始问题: {question}\n"
        f"失败的 SQL: {failed_sql}\n"
        f"错误信息: {error_msg}\n\n"
        "请修正 SQL 并直接输出 JSON。"
    )

    content = _call_llm_chat(api_key, url, model, timeout, system_prompt, user_prompt)
    obj = _parse_llm_json(content)

    intent = obj.get("intent", "list")
    sql = obj.get("sql", "")
    params = obj.get("params", [])
    filters = obj.get("filters", {})

    return _auto_correct_intent(QueryPlan(intent=intent, sql=sql, params=params, filters=filters))
