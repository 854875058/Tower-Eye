"""
系统监控 API
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import sqlite3
import time
from typing import Any, Dict

import requests
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.openai_compat import build_v1_endpoint
from app.models.models import DataSource, Dataset, QueryHistory, User, Workspace, WorkbenchDataset
from app.services.trace import get_trace_manager

logger = get_logger(__name__)
router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
TOWER_METADATA_DB = os.path.join(PROJECT_ROOT, "data", "metadata.db")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_down_payload(message: str, detail: str = "", latency_ms: int = 0) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": False,
        "status": "down",
        "message": message,
        "checked_at": _utc_now_iso(),
        "latency_ms": latency_ms,
    }
    if detail:
        payload["detail"] = detail
    return payload


def _build_up_payload(message: str, latency_ms: int, model: str = "", detail: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ok": True,
        "status": "up",
        "message": message,
        "checked_at": _utc_now_iso(),
        "latency_ms": latency_ms,
    }
    if model:
        payload["model"] = model
    if detail:
        payload["detail"] = detail
    return payload


def _build_service_payload(
    name: str,
    status: str,
    message: str,
    *,
    detail: str = "",
    latency_ms: int | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "status": status,
        "message": message,
    }
    if detail:
        payload["detail"] = detail
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    return payload


def _chat_completion_probe(base_url: str, api_key: str, model: str, timeout_sec: int) -> Dict[str, Any]:
    """对不支持 /v1/models 的兼容网关，回退用 chat/completions 做连通性探测。"""
    url = build_v1_endpoint(base_url, "/chat/completions")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    started = time.perf_counter()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code == 200:
            return _build_up_payload("环境启动正常", latency_ms, model=model, detail="通过 chat/completions 心跳检测")
        if resp.status_code in {401, 403}:
            return _build_down_payload("环境启动异常", f"LLM 鉴权失败（{resp.status_code}）", latency_ms)
        return _build_down_payload("环境启动异常", f"LLM 心跳探测失败（chat/completions 返回 {resp.status_code}）", latency_ms)
    except requests.RequestException as exc:
        logger.warning(f"LLM chat completion probe failed: {exc}")
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _build_down_payload("环境启动异常", f"LLM 连接失败: {exc}", latency_ms)


def _probe_llm_sync(base_url: str, api_key: str, model: str) -> Dict[str, Any]:
    """在线程池中执行心跳探测，避免阻塞事件循环。"""
    models_url = build_v1_endpoint(base_url, "/models")
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout_sec = 8
    started = time.perf_counter()

    try:
        resp = requests.get(models_url, headers=headers, timeout=timeout_sec)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code == 200:
            data = resp.json() if resp.content else {}
            model_count = len(data.get("data", [])) if isinstance(data, dict) else 0
            payload = _build_up_payload("环境启动正常", latency_ms, model=model)
            payload["model_count"] = model_count
            return payload

        detail = f"LLM 服务返回 HTTP {resp.status_code}"
        if resp.status_code == 401:
            detail = "LLM 鉴权失败（401）"
        elif resp.status_code == 403:
            detail = "LLM 鉴权失败（403）"
        elif resp.status_code in {404, 405}:
            return _chat_completion_probe(base_url, api_key, model, timeout_sec)
        return _build_down_payload("环境启动异常", detail, latency_ms)
    except requests.RequestException as exc:
        logger.warning(f"LLM heartbeat failed: {exc}")
        return _chat_completion_probe(base_url, api_key, model, timeout_sec)


def _probe_generic_http_service(name: str, url: str | None) -> Dict[str, Any]:
    if not url:
        return _build_service_payload(name, "unconfigured", "未配置", detail="未检测到服务地址")

    started = time.perf_counter()
    try:
        resp = requests.get(url, timeout=5)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code < 500:
            return _build_service_payload(name, "up", "服务可达", detail=url, latency_ms=latency_ms)
        return _build_service_payload(name, "degraded", f"服务返回 HTTP {resp.status_code}", detail=url, latency_ms=latency_ms)
    except requests.RequestException as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _build_service_payload(name, "down", "服务不可达", detail=f"{url} | {exc}", latency_ms=latency_ms)


def _read_tower_metadata_counts() -> Dict[str, int]:
    payload = {"assets": 0, "events": 0, "detections": 0}
    if not os.path.exists(TOWER_METADATA_DB):
        return payload

    conn = sqlite3.connect(TOWER_METADATA_DB)
    try:
        cursor = conn.cursor()
        for table in ("assets", "events", "detections"):
            try:
                payload[table] = int(cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except Exception:
                payload[table] = 0
        return payload
    finally:
        conn.close()


async def _build_monitor_summary(db: AsyncSession) -> Dict[str, Any]:
    workspace_count = int((await db.execute(select(func.count(Workspace.id)))).scalar() or 0)
    data_source_count = int((await db.execute(select(func.count(DataSource.id)).where(DataSource.is_active == True))).scalar() or 0)
    dataset_count = int((await db.execute(select(func.count(Dataset.id)))).scalar() or 0)
    workbench_dataset_count = int((await db.execute(select(func.count(WorkbenchDataset.id)))).scalar() or 0)
    query_history_count = int((await db.execute(select(func.count(QueryHistory.id)))).scalar() or 0)

    tower_counts = await run_in_threadpool(_read_tower_metadata_counts)

    trace_stats: Dict[str, Any] = {
        "total_queries": 0,
        "success_count": 0,
        "error_count": 0,
        "success_rate": 0.0,
        "avg_duration_ms": 0.0,
        "by_intent": {},
        "recent_queries": [],
    }
    trace_manager = get_trace_manager()
    if trace_manager:
        stats = trace_manager.get_statistics()
        total_queries = int(stats.get("total_queries") or 0)
        success_count = int(stats.get("success_count") or 0)
        error_count = int(stats.get("error_count") or 0)
        trace_stats.update(
            {
                "total_queries": total_queries,
                "success_count": success_count,
                "error_count": error_count,
                "success_rate": round((success_count / total_queries) * 100, 2) if total_queries else 0.0,
                "avg_duration_ms": float(stats.get("avg_duration_ms") or 0.0),
                "by_intent": stats.get("by_intent") or {},
                "recent_queries": [
                    {
                        "timestamp": item.get("timestamp"),
                        "question": item.get("question"),
                        "intent": item.get("intent"),
                        "status": item.get("status"),
                        "duration_ms": item.get("total_duration_ms"),
                        "trace_id": item.get("trace_id"),
                    }
                    for item in trace_manager.query_traces(limit=10)
                ],
            }
        )

    base_url = (settings.LLM_BASE_URL or os.getenv("LLM_BASE_URL") or "").strip()
    api_key = (settings.LLM_API_KEY or os.getenv("LLM_API_KEY") or "").strip()
    model = (settings.LLM_MODEL or os.getenv("LLM_MODEL") or "deepseek-chat").strip()
    llm_status = _build_down_payload("环境启动异常", "LLM 未配置")
    if base_url and api_key:
        llm_status = await run_in_threadpool(_probe_llm_sync, base_url, api_key, model)

    external_services = [
        _build_service_payload(
            "LLM 服务",
            llm_status.get("status", "down"),
            llm_status.get("message", ""),
            detail=llm_status.get("detail", ""),
            latency_ms=llm_status.get("latency_ms"),
        ),
        await run_in_threadpool(_probe_generic_http_service, "Embedding 服务", settings.EMBEDDING_QWEN_API_URL),
        await run_in_threadpool(_probe_generic_http_service, "Reranker 服务", settings.RERANKER_API_URL),
        _build_service_payload(
            "铁塔清洗数据",
            "up" if os.path.exists(TOWER_METADATA_DB) else "down",
            "清洗数据已就绪" if os.path.exists(TOWER_METADATA_DB) else "清洗数据缺失",
            detail=TOWER_METADATA_DB,
        ),
    ]

    tool_registry = [
        {"name": "NL2SQL 查询规划器", "category": "Query", "description": "负责自然语言转 SQL、多表候选规划和短会话追问理解。"},
        {"name": "多模态检索器", "category": "Search", "description": "负责图片、视频片段和文本的融合检索与结果重排。"},
        {"name": "语义增强器", "category": "Enhance", "description": "负责对列表查询结果补充语义命中分数和补充推荐结果。"},
        {"name": "视联告警分析器", "category": "Tower Demo", "description": "负责区域热点、设备热点、风险评分、优先级和建议动作输出。"},
        {"name": "知识图谱与血缘服务", "category": "Graph", "description": "负责本体配置、图谱构建和单事件血缘链展示。"},
        {"name": "数据工作台处理器", "category": "Workbench", "description": "负责数据采集、切块、向量化、标签抽取、聚类与质量评分。"},
    ]

    return {
        "data_stats": {
            "workspace_count": workspace_count,
            "data_source_count": data_source_count,
            "dataset_count": dataset_count,
            "workbench_dataset_count": workbench_dataset_count,
            "query_history_count": query_history_count,
            "tower_assets": tower_counts["assets"],
            "tower_events": tower_counts["events"],
            "tower_detections": tower_counts["detections"],
        },
        "query_trace": trace_stats,
        "tool_registry": tool_registry,
        "external_services": external_services,
        "checked_at": _utc_now_iso(),
    }


@router.get("/llm-heartbeat")
async def llm_heartbeat(_: User = Depends(get_current_user)):
    """LLM 心跳检查：验证服务可达性与基础鉴权是否可用"""
    base_url = (settings.LLM_BASE_URL or os.getenv("LLM_BASE_URL") or "").strip()
    api_key = (settings.LLM_API_KEY or os.getenv("LLM_API_KEY") or "").strip()
    model = (settings.LLM_MODEL or os.getenv("LLM_MODEL") or "").strip()

    if not base_url:
        return _build_down_payload("环境启动异常", "LLM_BASE_URL 未配置")
    if not api_key:
        return _build_down_payload("环境启动异常", "LLM_API_KEY 未配置")

    return await run_in_threadpool(
        _probe_llm_sync,
        base_url,
        api_key,
        model or "deepseek-chat",
    )


@router.get("/monitor-summary")
async def monitor_summary(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """系统监控汇总：数据统计、查询追踪、Tool 注册中心、外部服务状态。"""
    return await _build_monitor_summary(db)
