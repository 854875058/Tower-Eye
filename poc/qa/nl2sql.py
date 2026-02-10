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
    date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if len(date_matches) >= 2:
        return date_matches[0], date_matches[1]

    match = re.search(r"近(\d+)(天|小时)", text)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        end = datetime.now()  # 使用本地时间，而不是UTC时间
        start = end - (timedelta(days=value) if unit == "天" else timedelta(hours=value))
        # 使用空格格式而不是ISO格式的T，以匹配数据库中的时间格式
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


def _parse_intent(text: str) -> str:
    if any(k in text for k in ["多少", "统计", "数量", "总数", "分布", "TOP", "top", "排名"]):
        return "count"
    return "list"


def _parse_area_name(text: str) -> Tuple[Optional[str], Optional[str]]:
    """从问题中提取地区名称（街道/乡镇、区/县）

    Returns:
        (town_name, county_name)
    """
    import re
    town_name = None
    county_name = None

    # 匹配 "XX街道" / "XX镇" / "XX乡"
    m = re.search(r"([\u4e00-\u9fa5]{2,6}(?:街道|镇|乡))", text)
    if m:
        town_name = m.group(1)

    # 匹配 "XX区" / "XX县"
    m = re.search(r"([\u4e00-\u9fa5]{2,6}(?:区|县))", text)
    if m:
        county_name = m.group(1)

    return town_name, county_name


def parse_question(text: str) -> QueryPlan:
    intent = _parse_intent(text)
    event_type = None
    for key, value in SCENE_KEYWORDS.items():
        if key in text:
            event_type = value
            break

    start_time, end_time = _parse_time_range(text)
    top_k = _parse_top_k(text)
    lat, lon, radius_km = _parse_location(text)
    town_name, county_name = _parse_area_name(text)

    where = []
    params: List = []
    if event_type:
        where.append("e.event_type = ?")
        params.append(event_type)
    if start_time:
        where.append("e.alarm_time >= ?")
        params.append(start_time)
    if end_time:
        where.append("e.alarm_time <= ?")
        params.append(end_time)
    if town_name:
        where.append("e.town_name LIKE ?")
        params.append(f"%{town_name}%")
    if county_name:
        where.append("e.county_name LIKE ?")
        params.append(f"%{county_name}%")

    where_sql = " WHERE " + " AND ".join(where) if where else ""

    if intent == "count":
        sql = (
            "SELECT e.event_type AS 告警类型, COUNT(*) AS 数量 FROM events e "
            "LEFT JOIN assets a ON e.asset_id = a.asset_id"
            + where_sql
            + " GROUP BY e.event_type ORDER BY 数量 DESC"
        )
    else:
        sql = (
            "SELECT e.event_type AS 告警类型, e.alarm_time AS 告警时间, "
            "e.address AS 地址, e.town_name AS 街道, "
            "e.device_name AS 设备名称, e.algorithm_name AS 算法, "
            "e.order_status AS 工单状态, e.confidence_level AS 置信度, "
            "a.file_path AS 图片路径, e.video_path AS 视频路径 "
            "FROM events e LEFT JOIN assets a ON e.asset_id = a.asset_id"
            + where_sql
            + " ORDER BY e.alarm_time DESC LIMIT ?"
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
    }

    return QueryPlan(intent=intent, sql=sql, params=params, filters=filters)


def _call_deepseek_nl2sql(question: str, config: Dict, fallback: QueryPlan) -> QueryPlan:
    llm_cfg = config.get("llm", {})
    # 优先使用配置文件中的 api_key, 为空时再回退到环境变量
    api_key = llm_cfg.get("api_key") or None
    if not api_key:
        api_key_env = llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")
        api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError("DEEPSEEK API key not configured (neither in config.llm.api_key nor environment).")

    base_url = os.getenv("DEEPSEEK_BASE_URL", llm_cfg.get("base_url", "https://api.deepseek.com"))
    model = os.getenv("DEEPSEEK_MODEL", llm_cfg.get("model", "deepseek-chat"))

    url = base_url.rstrip("/") + "/v1/chat/completions"

    schema_description = (
        "数据库中有两个主要表:\n"
        "1) events(event_id, asset_id, event_type, alarm_level, alarm_source, alarm_time, "
        "lat, lon, region, extra_json, summary, description, address, device_name, confidence_level, "
        "province_name, city_name, county_name, town_code, town_name, "
        "device_code, channel_code, channel_name, "
        "warning_order_id, warning_type_id, alarm_body, algorithm_code, algorithm_name, "
        "emergency_level, importance_level, order_status, confidence_level_max, tenant_name, "
        "video_path, img_src_path, img_icon_path)\n"
        "2) assets(asset_id, media_type, file_path, file_name, captured_at, lat, lon, source)\n"
        "常用字段说明: event_type=告警类型, alarm_time=告警时间, town_name=乡镇/街道, "
        "county_name=区/县, device_code=设备编码, device_name=设备名称, "
        "algorithm_name=算法名称, order_status=工单状态, address=地址, "
        "img_src_path=原图路径, video_path=视频路径, summary=图像理解描述。\n"
        "请只查询这两个表, 避免任何DDL或写操作。"
    )

    system_prompt = (
        "你是一个 NL2SQL 助手, 负责将中文自然语言问题转换为 SQLite 的 SQL 查询。"
        "你必须严格输出一个 JSON 对象, 不能包含多余文字。\n"
        "JSON 结构为: {\"intent\": \"count|list\", \"sql\": string, \"params\": list, \"filters\": {}}。\n"
        "filters 必须包含这些键: event_type, start_time, end_time, lat, lon, radius_km, top_k。\n"
        "时间过滤使用 events.alarm_time 字段。\n" + schema_description
    )

    user_prompt = (
        "问题: " + question + "\n"
        "请直接输出 JSON, 不要添加注释或解释。"
    )

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

    response = requests.post(url, headers=headers, json=payload, timeout=llm_cfg.get("timeout", 30))
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()

    try:
        obj = json.loads(content)
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise RuntimeError(f"LLM 输出不是有效 JSON: {content}") from exc

    intent = obj.get("intent") or fallback.intent
    sql = obj.get("sql") or fallback.sql
    params = obj.get("params") or fallback.params
    filters = obj.get("filters") or fallback.filters

    # 确保 filters 至少包含必要键
    merged_filters = dict(fallback.filters)
    if isinstance(filters, dict):
        merged_filters.update(filters)

    return QueryPlan(intent=intent, sql=sql, params=params, filters=merged_filters)


def build_query_plan(text: str, config: Dict) -> QueryPlan:
    """构建查询计划: 根据配置选择规则引擎或 DeepSeek LLM。"""

    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled", False):
        return parse_question(text)

    mode = llm_cfg.get("mode", "rule")
    rule_plan = parse_question(text)

    if mode == "rule":
        return rule_plan

    if mode in {"llm", "hybrid"}:
        try:
            llm_plan = _call_deepseek_nl2sql(text, config, rule_plan)
            if mode == "llm":
                return llm_plan
            # hybrid: 默认优先采用 LLM 结果, 如需更保守可以在此加入简单校验
            return llm_plan
        except Exception:
            return rule_plan

    return rule_plan
