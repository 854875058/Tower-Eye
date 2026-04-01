from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
METADATA_DB = PROJECT_ROOT / "data" / "metadata.db"
WARNING_IMG_ROOT = PROJECT_ROOT / "data" / "warning_img"
WARNING_VIDEO_ROOT = PROJECT_ROOT / "data" / "warning_file"
ONTOLOGY_CONFIG_PATH = PROJECT_ROOT / "backend" / "data" / "tower_ontology_config.json"

DEFAULT_ONTOLOGY_CONFIG = {
    "entities": [
        {
            "type": "source",
            "label": "数据源",
            "description": "原始业务数据载体，包括事件元数据、图片资源、视频资源。",
            "key_fields": ["source_name", "storage_path"],
            "source_fields": ["events", "warning_img", "warning_file"],
            "enabled": True,
        },
        {
            "type": "event",
            "label": "告警事件",
            "description": "视联告警核心业务对象，承载事件类型、时间、位置、设备和置信度。",
            "key_fields": ["event_id", "event_type", "alarm_time", "confidence_level"],
            "source_fields": ["event_id", "event_type", "alarm_time", "confidence_level", "summary"],
            "enabled": True,
        },
        {
            "type": "region",
            "label": "区域实体",
            "description": "用于聚合告警热点、分析区域风险和巡检优先级。",
            "key_fields": ["province_name", "city_name", "county_name"],
            "source_fields": ["province_name", "city_name", "county_name", "town_name"],
            "enabled": True,
        },
        {
            "type": "device",
            "label": "设备实体",
            "description": "承载设备热点、通道活跃度和重点复核对象。",
            "key_fields": ["device_name", "channel_name"],
            "source_fields": ["device_name", "channel_name", "algorithm_name"],
            "enabled": True,
        },
        {
            "type": "algorithm",
            "label": "告警算法",
            "description": "表示当前告警所使用的算法模型及其触发情况。",
            "key_fields": ["algorithm_name"],
            "source_fields": ["algorithm_name"],
            "enabled": True,
        },
        {
            "type": "media",
            "label": "多模态证据",
            "description": "与告警事件关联的图片和视频证据。",
            "key_fields": ["image_url", "video_url"],
            "source_fields": ["img_src_path", "video_path"],
            "enabled": True,
        },
        {
            "type": "process",
            "label": "处理过程",
            "description": "描述从事件接入、图谱关联、风险排序到建议生成的处理链路。",
            "key_fields": ["process_name"],
            "source_fields": ["事件接入", "知识关联", "风险排序", "建议生成"],
            "enabled": True,
        },
        {
            "type": "recommendation",
            "label": "处置建议",
            "description": "面向巡检、复核和样本治理的建议输出对象。",
            "key_fields": ["title", "priority"],
            "source_fields": ["title", "priority", "reason"],
            "enabled": True,
        },
    ],
    "relations": [
        {"type": "feeds", "label": "数据注入", "source_type": "source", "target_type": "process", "description": "原始数据进入处理流程。", "source_field": None, "enabled": True},
        {"type": "produces", "label": "产出", "source_type": "process", "target_type": "event", "description": "处理流程产出业务事件。", "source_field": None, "enabled": True},
        {"type": "located_in", "label": "发生区域", "source_type": "event", "target_type": "region", "description": "告警事件映射到区域实体。", "source_field": "county_name", "enabled": True},
        {"type": "detected_on", "label": "触发设备", "source_type": "event", "target_type": "device", "description": "告警事件关联触发设备。", "source_field": "device_name", "enabled": True},
        {"type": "uses_algorithm", "label": "关联算法", "source_type": "event", "target_type": "algorithm", "description": "告警事件由特定算法识别产生。", "source_field": "algorithm_name", "enabled": True},
        {"type": "has_image", "label": "关联图片", "source_type": "event", "target_type": "media", "description": "告警事件关联图片证据。", "source_field": "img_src_path", "enabled": True},
        {"type": "has_video", "label": "关联视频", "source_type": "event", "target_type": "media", "description": "告警事件关联视频证据。", "source_field": "video_path", "enabled": True},
        {"type": "supports", "label": "支撑分析", "source_type": "region", "target_type": "process", "description": "区域或设备信息参与风险分析。", "source_field": None, "enabled": True},
        {"type": "transforms", "label": "处理流转", "source_type": "process", "target_type": "process", "description": "处理阶段之间的流转关系。", "source_field": None, "enabled": True},
        {"type": "outputs", "label": "输出建议", "source_type": "process", "target_type": "recommendation", "description": "分析流程输出建议动作。", "source_field": None, "enabled": True},
    ],
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _warning_img_url(path: Optional[str]) -> Optional[str]:
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        return None
    return f"/tower-warning-img/{Path(text).name}"


def _warning_video_url(path: Optional[str]) -> Optional[str]:
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        return None
    return f"/tower-warning-video/{Path(text).name}"


def _priority_bucket(score: float) -> str:
    if score >= 85:
        return "P1"
    if score >= 70:
        return "P2"
    return "P3"


def _build_chart_payload(
    *,
    chart_type: str,
    title: str,
    categories: list[str],
    series_name: str,
    values: list[float | int],
    y_axis_name: str = "数量",
) -> dict[str, Any]:
    return {
        "chart_type": chart_type,
        "title": title,
        "categories": categories,
        "series": [
            {
                "name": series_name,
                "data": values,
            }
        ],
        "y_axis_name": y_axis_name,
    }


class TowerWarningDemoService:
    def __init__(self) -> None:
        if not METADATA_DB.exists():
            raise FileNotFoundError(str(METADATA_DB))

    def _ensure_ontology_config(self) -> None:
        ONTOLOGY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not ONTOLOGY_CONFIG_PATH.exists():
            ONTOLOGY_CONFIG_PATH.write_text(
                json.dumps(DEFAULT_ONTOLOGY_CONFIG, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def get_ontology_config(self) -> dict[str, Any]:
        self._ensure_ontology_config()
        payload = json.loads(ONTOLOGY_CONFIG_PATH.read_text(encoding="utf-8"))
        existing_entity_types = {item.get("type") for item in payload.get("entities", [])}
        for item in DEFAULT_ONTOLOGY_CONFIG["entities"]:
            if item["type"] not in existing_entity_types:
                payload.setdefault("entities", []).append(item)
        existing_relation_types = {item.get("type") for item in payload.get("relations", [])}
        for item in DEFAULT_ONTOLOGY_CONFIG["relations"]:
            if item["type"] not in existing_relation_types:
                payload.setdefault("relations", []).append(item)
        payload["updated_at"] = datetime.fromtimestamp(ONTOLOGY_CONFIG_PATH.stat().st_mtime).isoformat()
        return payload

    def save_ontology_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        entities = payload.get("entities") or []
        relations = payload.get("relations") or []
        normalized = {
            "entities": entities,
            "relations": relations,
        }
        ONTOLOGY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ONTOLOGY_CONFIG_PATH.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.get_ontology_config()

    def reset_ontology_config(self) -> dict[str, Any]:
        ONTOLOGY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ONTOLOGY_CONFIG_PATH.write_text(
            json.dumps(DEFAULT_ONTOLOGY_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.get_ontology_config()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(METADATA_DB)
        conn.row_factory = sqlite3.Row
        return conn

    def get_dashboard(self) -> dict[str, Any]:
        conn = self._connect()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM events")
        total_events = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(DISTINCT device_name), COUNT(DISTINCT county_name), COUNT(DISTINCT city_name) FROM events")
        distinct_devices, distinct_counties, distinct_cities = cur.fetchone()
        cur.execute("SELECT MIN(confidence_level), AVG(confidence_level), MAX(confidence_level) FROM events WHERE confidence_level IS NOT NULL")
        min_conf, avg_conf, max_conf = cur.fetchone()
        cur.execute("SELECT MIN(alarm_time), MAX(alarm_time) FROM events")
        min_time, max_time = cur.fetchone()

        cur.execute(
            """
            SELECT county_name, COUNT(*) AS cnt, AVG(confidence_level) AS avg_conf, MAX(alarm_time) AS last_time
            FROM events
            GROUP BY county_name
            ORDER BY cnt DESC
            LIMIT 10
            """
        )
        hot_regions = [
            {
                "county_name": row["county_name"] or "未知区域",
                "count": int(row["cnt"] or 0),
                "avg_confidence": round(_to_float(row["avg_conf"]), 4),
                "last_alarm_time": row["last_time"],
            }
            for row in cur.fetchall()
        ]
        for item in hot_regions:
            region_score = min((item["count"] / max(total_events, 1)) * 100 * 4.5 + (1 - item["avg_confidence"]) * 35 + 10, 100)
            item["risk_score"] = round(region_score, 2)
            item["priority"] = _priority_bucket(item["risk_score"])

        cur.execute(
            """
            SELECT device_name, COUNT(*) AS cnt, AVG(confidence_level) AS avg_conf, MAX(alarm_time) AS last_time
            FROM events
            GROUP BY device_name
            ORDER BY cnt DESC
            LIMIT 10
            """
        )
        hot_devices = [
            {
                "device_name": row["device_name"] or "未知设备",
                "count": int(row["cnt"] or 0),
                "avg_confidence": round(_to_float(row["avg_conf"]), 4),
                "last_alarm_time": row["last_time"],
            }
            for row in cur.fetchall()
        ]
        for item in hot_devices:
            device_score = min((item["count"] / max(total_events, 1)) * 100 * 4.5 + (1 - item["avg_confidence"]) * 30 + 8, 100)
            item["risk_score"] = round(device_score, 2)
            item["priority"] = _priority_bucket(item["risk_score"])

        cur.execute(
            """
            SELECT algorithm_name, COUNT(*) AS cnt, AVG(confidence_level) AS avg_conf, MAX(alarm_time) AS last_time
            FROM events
            GROUP BY algorithm_name
            ORDER BY cnt DESC
            LIMIT 10
            """
        )
        algorithm_top = [
            {
                "algorithm_name": row["algorithm_name"] or "未知算法",
                "count": int(row["cnt"] or 0),
                "avg_confidence": round(_to_float(row["avg_conf"]), 4),
                "last_alarm_time": row["last_time"],
            }
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT event_id, event_type, county_name, city_name, device_name, alarm_time, confidence_level, summary, img_src_path, video_path
            FROM events
            ORDER BY CAST(confidence_level AS FLOAT) ASC, alarm_time DESC
            LIMIT 12
            """
        )
        low_confidence = [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "county_name": row["county_name"],
                "city_name": row["city_name"],
                "device_name": row["device_name"],
                "alarm_time": row["alarm_time"],
                "confidence_level": round(_to_float(row["confidence_level"]), 4),
                "summary": row["summary"] or "",
                "image_url": _warning_img_url(row["img_src_path"]),
                "video_url": _warning_video_url(row["video_path"]),
            }
            for row in cur.fetchall()
        ]
        hot_region_map = {item["county_name"]: item for item in hot_regions}
        hot_device_map = {item["device_name"]: item for item in hot_devices}
        for item in low_confidence:
            confidence = float(item["confidence_level"] or 0)
            region_score = hot_region_map.get(item["county_name"], {}).get("risk_score", 0)
            device_score = hot_device_map.get(item["device_name"], {}).get("risk_score", 0)
            event_score = min((1 - confidence) * 55 + region_score * 0.25 + device_score * 0.2 + 15, 100)
            item["risk_score"] = round(event_score, 2)
            item["priority"] = _priority_bucket(item["risk_score"])
            item["action_type"] = "人工复核" if confidence < 0.72 else "重点巡检"

        cur.execute(
            """
            SELECT substr(alarm_time, 1, 10) AS day, COUNT(*) AS cnt
            FROM events
            GROUP BY substr(alarm_time, 1, 10)
            ORDER BY day DESC
            LIMIT 14
            """
        )
        trend = [{"day": row["day"], "count": int(row["cnt"] or 0)} for row in cur.fetchall()][::-1]

        conn.close()

        recommendations = self._build_recommendations(hot_regions, hot_devices, low_confidence)

        return {
            "summary": {
                "total_events": total_events,
                "distinct_devices": int(distinct_devices or 0),
                "distinct_counties": int(distinct_counties or 0),
                "distinct_cities": int(distinct_cities or 0),
                "avg_confidence": round(_to_float(avg_conf), 4),
                "min_confidence": round(_to_float(min_conf), 4),
                "max_confidence": round(_to_float(max_conf), 4),
                "time_range": {"start": min_time, "end": max_time},
                "image_count": len(list(WARNING_IMG_ROOT.glob("*.jpg"))) if WARNING_IMG_ROOT.exists() else 0,
                "video_count": len(list(WARNING_VIDEO_ROOT.glob("*.mp4"))) if WARNING_VIDEO_ROOT.exists() else 0,
            },
            "hot_regions": hot_regions,
            "hot_devices": hot_devices,
            "algorithm_top": algorithm_top,
            "low_confidence_events": low_confidence,
            "trend": trend,
            "priority_queue": low_confidence[:8],
            "recommendations": recommendations,
        }

    def answer(self, question: str) -> dict[str, Any]:
        dashboard = self.get_dashboard()
        lowered = (question or "").lower()
        steps: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        visualization: Optional[dict[str, Any]] = None

        def add_step(name: str, detail: str) -> None:
            steps.append({"step": name, "detail": detail})

        def add_action(action_type: str, label: str, target: str, payload: Optional[dict[str, Any]] = None) -> None:
            actions.append({
                "type": action_type,
                "label": label,
                "target": target,
                "payload": payload or {},
            })

        if any(token in lowered for token in ["趋势", "变化", "trend", "变化趋势"]):
            add_step("intent", "识别为告警趋势分析")
            add_step("tool", "调用趋势分析器")
            visualization = _build_chart_payload(
                chart_type="line",
                title="告警变化趋势",
                categories=[item["day"] for item in dashboard["trend"]],
                series_name="告警数量",
                values=[item["count"] for item in dashboard["trend"]],
                y_axis_name="告警数",
            )
            answer = "当前已生成告警变化趋势图，可直接查看近一段时间的告警波动情况，并结合峰值日期进一步追查区域和设备。"
            evidence = dashboard["trend"]
            add_action("focus_section", "查看变化趋势", "trend")
        elif any(token in lowered for token in ["区域", "地区", "分布", "哪里", "热点", "高发", "county", "region"]):
            add_step("intent", "识别为热点区域分析")
            add_step("tool", "调用区域热点分析器")
            top_region = dashboard["hot_regions"][0] if dashboard["hot_regions"] else None
            if top_region:
                answer = (
                    f"当前告警最集中的区域是{top_region['county_name']}，"
                    f"累计{top_region['count']}条事件，平均置信度{top_region['avg_confidence']:.2f}，"
                    f"区域风险分为{top_region['risk_score']:.1f}，处置优先级为{top_region['priority']}。"
                    "建议优先排查该区域重点站址、设备通道与布控策略。"
                )
            else:
                answer = "当前没有可分析的区域热点。"
            evidence = dashboard["hot_regions"][:5]
            visualization = _build_chart_payload(
                chart_type="bar",
                title="当前告警地区分布",
                categories=[item["county_name"] for item in dashboard["hot_regions"][:6]],
                series_name="告警次数",
                values=[item["count"] for item in dashboard["hot_regions"][:6]],
                y_axis_name="告警次数",
            )
            add_action("focus_section", "查看区域分布", "hot_regions")
            add_action("focus_graph", "定位区域图谱", "graph")
        elif any(token in lowered for token in ["设备", "device", "通道", "摄像头"]):
            add_step("intent", "识别为设备风险分析")
            add_step("tool", "调用设备热点分析器")
            top_device = dashboard["hot_devices"][0] if dashboard["hot_devices"] else None
            if top_device:
                answer = (
                    f"当前最活跃的设备是{top_device['device_name']}，"
                    f"累计触发{top_device['count']}次告警，最近一次发生在{top_device['last_alarm_time']}，"
                    f"设备风险分为{top_device['risk_score']:.1f}，优先级为{top_device['priority']}。"
                    "建议将该设备纳入重点巡检和阈值复核清单。"
                )
            else:
                answer = "当前没有可分析的设备热点。"
            evidence = dashboard["hot_devices"][:5]
            visualization = _build_chart_payload(
                chart_type="bar",
                title="高频告警设备分布",
                categories=[item["device_name"] for item in dashboard["hot_devices"][:6]],
                series_name="告警次数",
                values=[item["count"] for item in dashboard["hot_devices"][:6]],
                y_axis_name="告警次数",
            )
            add_action("focus_section", "查看设备热点", "hot_devices")
        elif any(token in lowered for token in ["误报", "低置信度", "confidence", "复核", "人工"]):
            add_step("intent", "识别为疑似误报分析")
            add_step("tool", "调用低置信度事件筛查器")
            low_conf = dashboard["low_confidence_events"][:5]
            if low_conf:
                answer = (
                    f"当前已筛出{len(low_conf)}条低置信度样本，"
                    f"最低置信度为{low_conf[0]['confidence_level']:.2f}，首条事件风险分为{low_conf[0]['risk_score']:.1f}，"
                    f"优先级为{low_conf[0]['priority']}。建议优先进行人工复核，并回流训练样本。"
                )
            else:
                answer = "当前没有低置信度样本。"
            evidence = low_conf
            add_action("focus_section", "查看待复核样本", "priority_queue")
            if low_conf:
                add_action("open_lineage", "查看首条事件血缘", "lineage", {"event_id": low_conf[0]["event_id"]})
        elif any(token in lowered for token in ["建议", "怎么做", "处置", "优化", "dispatch", "调度"]):
            add_step("intent", "识别为处置建议生成")
            add_step("tool", "调用规则化运营建议引擎")
            top_recommendation = dashboard["recommendations"][0] if dashboard["recommendations"] else None
            if top_recommendation:
                answer = (
                    f"当前建议优先执行“{top_recommendation['title']}”，"
                    f"建议动作是：{top_recommendation['action']}。"
                    "同时结合重点设备复核和低置信度样本回流形成闭环处置。"
                )
            else:
                answer = "当前没有可输出的处置建议。"
            evidence = dashboard["recommendations"]
            add_action("focus_section", "查看处置建议", "recommendations")
        else:
            add_step("intent", "识别为全局概览分析")
            add_step("tool", "调用总览分析器")
            summary = dashboard["summary"]
            answer = (
                f"当前样本共包含{summary['total_events']}条告警事件、"
                f"{summary['image_count']}张图片、{summary['video_count']}段视频，"
                f"覆盖{summary['distinct_counties']}个区县和{summary['distinct_devices']}个设备。"
                "当前平台已具备区域热点、设备风险、低置信度样本复核和处置建议四类分析能力。"
            )
            evidence = {
                "summary": summary,
                "hot_regions": dashboard["hot_regions"][:3],
                "hot_devices": dashboard["hot_devices"][:3],
            }
            add_action("focus_section", "查看平台概览", "overview")

        return {
            "question": question,
            "answer": answer,
            "steps": steps,
            "actions": actions,
            "visualization": visualization,
            "evidence": evidence,
            "dashboard": dashboard if "全局" in answer or "样本共包含" in answer else None,
        }

    def get_graph(self) -> dict[str, Any]:
        dashboard = self.get_dashboard()
        ontology_config = self.get_ontology_config()
        enabled_entities = {
            item["type"]: item
            for item in ontology_config.get("entities", [])
            if item.get("enabled", True)
        }
        enabled_relations = {
            item["type"]: item
            for item in ontology_config.get("relations", [])
            if item.get("enabled", True)
        }
        conn = self._connect()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT event_id, event_type, county_name, city_name, device_name, alarm_time, confidence_level,
                   summary, img_src_path, video_path, province_name, channel_name, algorithm_name
            FROM events
            ORDER BY CAST(confidence_level AS FLOAT) ASC, alarm_time DESC
            LIMIT 12
            """
        )
        selected_rows = list(cur.fetchall())
        conn.close()

        ontology = [
            {
                "type": item["type"],
                "label": item["label"],
                "description": item["description"],
                "key_fields": item.get("key_fields", []),
                "source_fields": item.get("source_fields", []),
                "enabled": item.get("enabled", True),
            }
            for item in ontology_config.get("entities", [])
        ]

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        node_ids: set[str] = set()

        def add_node(node_id: str, **payload: Any) -> None:
            if node_id in node_ids:
                return
            node_ids.add(node_id)
            nodes.append({"id": node_id, **payload})

        def add_edge(source: str, target: str, relation: str, label: str) -> None:
            edges.append({"source": source, "target": target, "relation": relation, "label": label})

        if "source" in enabled_entities:
            add_node("source:metadata", label="事件元数据", category="source", symbolSize=54, value=715)
            add_node("source:images", label="图片样本库", category="source", symbolSize=50, value=dashboard["summary"]["image_count"])
            add_node("source:videos", label="视频样本库", category="source", symbolSize=50, value=dashboard["summary"]["video_count"])
        if "process" in enabled_entities:
            add_node("process:ingest", label="事件接入", category="process", symbolSize=44)
            add_node("process:graph", label="知识关联", category="process", symbolSize=44)
            add_node("process:risk", label="风险排序", category="process", symbolSize=44)
            add_node("process:suggest", label="建议生成", category="process", symbolSize=44)

        if "feeds" in enabled_relations and "source" in enabled_entities and "process" in enabled_entities:
            add_edge("source:metadata", "process:ingest", "feeds", enabled_relations["feeds"]["label"])
            add_edge("source:images", "process:graph", "feeds", enabled_relations["feeds"]["label"])
            add_edge("source:videos", "process:graph", "feeds", enabled_relations["feeds"]["label"])
        if "transforms" in enabled_relations and "process" in enabled_entities:
            add_edge("process:ingest", "process:graph", "transforms", enabled_relations["transforms"]["label"])
            add_edge("process:graph", "process:risk", "transforms", enabled_relations["transforms"]["label"])
            add_edge("process:risk", "process:suggest", "transforms", enabled_relations["transforms"]["label"])

        if "region" in enabled_entities:
            for item in dashboard["hot_regions"][:6]:
                region_id = f"region:{item['county_name']}"
                add_node(
                    region_id,
                    label=item["county_name"],
                    category="region",
                    symbolSize=30 + min(item["count"] / 8, 28),
                    value=item["count"],
                    meta=item,
                )
                if "produces" in enabled_relations and "process" in enabled_entities:
                    add_edge("process:graph", region_id, "produces", enabled_relations["produces"]["label"])
                if "supports" in enabled_relations and "process" in enabled_entities:
                    add_edge(region_id, "process:risk", "supports", enabled_relations["supports"]["label"])

        if "device" in enabled_entities:
            for item in dashboard["hot_devices"][:6]:
                device_id = f"device:{item['device_name']}"
                add_node(
                    device_id,
                    label=item["device_name"],
                    category="device",
                    symbolSize=28 + min(item["count"] / 10, 26),
                    value=item["count"],
                    meta=item,
                )
                if "produces" in enabled_relations and "process" in enabled_entities:
                    add_edge("process:graph", device_id, "produces", enabled_relations["produces"]["label"])
                if "supports" in enabled_relations and "process" in enabled_entities:
                    add_edge(device_id, "process:risk", "supports", enabled_relations["supports"]["label"])

        if "algorithm" in enabled_entities:
            for item in dashboard.get("algorithm_top", [])[:6]:
                algorithm_id = f"algorithm:{item['algorithm_name']}"
                add_node(
                    algorithm_id,
                    label=item["algorithm_name"],
                    category="algorithm",
                    symbolSize=28 + min(item["count"] / 12, 18),
                    value=item["count"],
                    meta=item,
                )
                if "supports" in enabled_relations and "process" in enabled_entities:
                    add_edge(algorithm_id, "process:risk", "supports", enabled_relations["supports"]["label"])

        for index, row in enumerate(selected_rows):
            event_id = f"event:{row['event_id']}"
            region_id = f"region:{row['county_name'] or '未知区域'}"
            device_id = f"device:{row['device_name'] or '未知设备'}"
            algorithm_id = f"algorithm:{row['algorithm_name'] or '未知算法'}"
            conf = round(_to_float(row["confidence_level"]), 4)
            if "event" in enabled_entities:
                add_node(
                    event_id,
                    label=f"{row['event_type']} #{index + 1}",
                    category="event",
                    symbolSize=28,
                    value=max(conf * 100, 1),
                    meta={
                        "event_id": row["event_id"],
                        "event_type": row["event_type"],
                        "county_name": row["county_name"],
                        "city_name": row["city_name"],
                        "device_name": row["device_name"],
                        "alarm_time": row["alarm_time"],
                        "confidence_level": conf,
                        "summary": row["summary"] or "",
                        "image_url": _warning_img_url(row["img_src_path"]),
                        "video_url": _warning_video_url(row["video_path"]),
                    },
                )
                if "produces" in enabled_relations and "process" in enabled_entities:
                    add_edge("process:ingest", event_id, "produces", enabled_relations["produces"]["label"])
                if "located_in" in enabled_relations and "region" in enabled_entities:
                    add_edge(event_id, region_id, "located_in", enabled_relations["located_in"]["label"])
                if "detected_on" in enabled_relations and "device" in enabled_entities:
                    add_edge(event_id, device_id, "detected_on", enabled_relations["detected_on"]["label"])
                if "uses_algorithm" in enabled_relations and "algorithm" in enabled_entities:
                    add_edge(event_id, algorithm_id, "uses_algorithm", enabled_relations["uses_algorithm"]["label"])
                if "supports" in enabled_relations and "process" in enabled_entities:
                    add_edge(event_id, "process:risk", "supports", enabled_relations["supports"]["label"])

            if "media" in enabled_entities:
                image_url = _warning_img_url(row["img_src_path"])
                if image_url and "has_image" in enabled_relations and "event" in enabled_entities:
                    image_id = f"image:{row['event_id']}"
                    add_node(
                        image_id,
                        label="事件图片",
                        category="media",
                        symbolSize=20,
                        value=1,
                        meta={"event_id": row["event_id"], "image_url": image_url, "summary": row["summary"] or ""},
                    )
                    add_edge(event_id, image_id, "has_image", enabled_relations["has_image"]["label"])
                    if "supports" in enabled_relations and "process" in enabled_entities:
                        add_edge(image_id, "process:graph", "supports", enabled_relations["supports"]["label"])

                video_url = _warning_video_url(row["video_path"])
                if video_url and "has_video" in enabled_relations and "event" in enabled_entities:
                    video_id = f"video:{row['event_id']}"
                    add_node(
                        video_id,
                        label="事件视频",
                        category="media",
                        symbolSize=20,
                        value=1,
                        meta={"event_id": row["event_id"], "video_url": video_url, "summary": row["summary"] or ""},
                    )
                    add_edge(event_id, video_id, "has_video", enabled_relations["has_video"]["label"])
                    if "supports" in enabled_relations and "process" in enabled_entities:
                        add_edge(video_id, "process:graph", "supports", enabled_relations["supports"]["label"])

        if "recommendation" in enabled_entities:
            for rec in dashboard["recommendations"]:
                rec_id = f"rec:{rec['type']}"
                add_node(
                    rec_id,
                    label=rec["title"],
                    category="recommendation",
                    symbolSize=34,
                    value=1,
                    meta=rec,
                )
                if "outputs" in enabled_relations and "process" in enabled_entities:
                    add_edge("process:suggest", rec_id, "outputs", enabled_relations["outputs"]["label"])

        node_stats = Counter(node["category"] for node in nodes)
        edge_stats = Counter(edge["relation"] for edge in edges)

        return {
            "ontology": ontology,
            "graph": {
                "nodes": nodes,
                "edges": edges,
                "stats": {
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "node_categories": dict(node_stats),
                    "edge_categories": dict(edge_stats),
                },
            },
        }

    def get_event_lineage(self, event_id: str) -> dict[str, Any]:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT event_id, event_type, alarm_time, county_name, city_name, province_name, town_name,
                   device_name, channel_name, confidence_level, summary, description, img_src_path, video_path,
                   algorithm_name, alarm_source, alarm_level, address
            FROM events
            WHERE event_id = ?
            """,
            (event_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            raise ValueError("Event not found")

        confidence = round(_to_float(row["confidence_level"]), 4)
        risk_bucket = "high" if confidence >= 0.9 else "medium" if confidence >= 0.75 else "low"
        needs_review = confidence < 0.72

        timeline = [
            {
                "stage": "source",
                "title": "原始告警事件",
                "description": "来自视联告警元数据表，包含告警类型、设备、区域、时间和摘要。",
                "evidence": {
                    "event_type": row["event_type"],
                    "alarm_source": row["alarm_source"],
                    "alarm_level": row["alarm_level"],
                    "alarm_time": row["alarm_time"],
                },
            },
            {
                "stage": "media",
                "title": "多模态证据关联",
                "description": "系统自动关联该事件对应图片与视频资源，形成事件证据集合。",
                "evidence": {
                    "image_url": _warning_img_url(row["img_src_path"]),
                    "video_url": _warning_video_url(row["video_path"]),
                },
            },
            {
                "stage": "graph",
                "title": "图谱实体归一",
                "description": "将事件映射到区域、设备、通道等业务实体，纳入知识图谱。",
                "evidence": {
                    "province_name": row["province_name"],
                    "city_name": row["city_name"],
                    "county_name": row["county_name"],
                    "town_name": row["town_name"],
                    "device_name": row["device_name"],
                    "channel_name": row["channel_name"],
                },
            },
            {
                "stage": "analysis",
                "title": "风险分析",
                "description": "根据告警置信度、事件摘要和区域/设备活跃度进行风险排序和样本筛查。",
                "evidence": {
                    "confidence_level": confidence,
                    "risk_bucket": risk_bucket,
                    "needs_manual_review": needs_review,
                    "algorithm_name": row["algorithm_name"],
                },
            },
            {
                "stage": "action",
                "title": "处置建议",
                "description": "结合区域热点、设备活跃度和置信度，生成面向巡检、复核和样本治理的建议。",
                "evidence": {
                    "primary_action": "人工复核并检查布控阈值" if needs_review else "纳入区域巡检重点关注",
                    "summary": row["summary"] or row["description"] or "",
                    "address": row["address"] or "",
                },
            },
        ]

        return {
            "event": {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "alarm_time": row["alarm_time"],
                "province_name": row["province_name"],
                "city_name": row["city_name"],
                "county_name": row["county_name"],
                "device_name": row["device_name"],
                "channel_name": row["channel_name"],
                "confidence_level": confidence,
                "summary": row["summary"] or "",
                "description": row["description"] or "",
                "image_url": _warning_img_url(row["img_src_path"]),
                "video_url": _warning_video_url(row["video_path"]),
            },
            "timeline": timeline,
            "recommendation": {
                "risk_bucket": risk_bucket,
                "needs_manual_review": needs_review,
                "next_action": "人工复核 + 样本回流" if needs_review else "区域巡检 + 规则阈值检查",
            },
        }

    def _build_recommendations(
        self,
        hot_regions: list[dict[str, Any]],
        hot_devices: list[dict[str, Any]],
        low_confidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        if hot_regions:
            region = hot_regions[0]
            recommendations.append(
                {
                    "type": "regional_patrol",
                    "title": f"优先巡检高发区域：{region['county_name']}",
                    "reason": f"该区域累计告警{region['count']}次，是当前最集中区域。",
                    "risk_score": region.get("risk_score", 0),
                    "action": "安排区域巡检、复核布控策略、排查高频点位。",
                    "priority": "high",
                }
            )
        if hot_devices:
            device = hot_devices[0]
            recommendations.append(
                {
                    "type": "device_focus",
                    "title": f"重点复核设备：{device['device_name']}",
                    "reason": f"该设备触发{device['count']}次告警，建议检查布控与告警阈值。",
                    "risk_score": device.get("risk_score", 0),
                    "action": "列入重点设备清单，核查摄像头视角、阈值和模型表现。",
                    "priority": "high",
                }
            )
        if low_confidence:
            recommendations.append(
                {
                    "type": "label_feedback",
                    "title": "构建低置信度样本复核队列",
                    "reason": f"当前已识别{len(low_confidence)}条低置信度事件，适合作为训练样本回流入口。",
                    "risk_score": round(sum(item.get("risk_score", 0) for item in low_confidence[:5]) / max(min(len(low_confidence), 5), 1), 2),
                    "action": "优先人工复核低置信度事件，并将复核结果回流样本库。",
                    "priority": "medium",
                }
            )
        return recommendations
