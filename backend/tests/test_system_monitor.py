from __future__ import annotations

import asyncio
import shutil
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

import app.core.database as db_module
from app.api.system import _build_monitor_summary
from app.core.database import Base
from app.models.models import DataSource, DataSourceType, Dataset, DatasetStatus, ProcessingStatus, QueryHistory, Workspace


def test_build_monitor_summary_returns_expected_sections(monkeypatch):
    runtime_dir = Path.cwd() / "backend" / "data" / "_system_monitor_test_runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir, ignore_errors=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    db_file = runtime_dir / "test_chatbot.db"
    tower_db = runtime_dir / "tower_metadata.db"

    tower_conn = sqlite3.connect(str(tower_db))
    try:
        tower_conn.execute("CREATE TABLE assets (asset_id TEXT)")
        tower_conn.execute("CREATE TABLE events (event_id TEXT)")
        tower_conn.execute("CREATE TABLE detections (id INTEGER)")
        tower_conn.executemany("INSERT INTO assets (asset_id) VALUES (?)", [("a1",), ("a2",)])
        tower_conn.executemany("INSERT INTO events (event_id) VALUES (?)", [("e1",), ("e2",), ("e3",)])
        tower_conn.execute("INSERT INTO detections (id) VALUES (1)")
        tower_conn.commit()
    finally:
        tower_conn.close()

    sync_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        echo=False,
    )
    async_session_maker = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", sync_engine)
    monkeypatch.setattr(db_module, "async_engine", async_engine)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", async_session_maker)
    monkeypatch.setattr("app.api.system.TOWER_METADATA_DB", str(tower_db))

    class FakeTraceManager:
        def get_statistics(self):
            return {
                "total_queries": 12,
                "success_count": 9,
                "error_count": 3,
                "avg_duration_ms": 42.5,
                "by_intent": {"list": 7, "count": 5},
            }

        def query_traces(self, limit=10):
            return [
                {
                    "timestamp": "2026-04-01T12:00:00",
                    "question": "统计海沧区告警数量",
                    "intent": "count",
                    "status": "success",
                    "total_duration_ms": 35,
                    "trace_id": "trace-1",
                }
            ]

    monkeypatch.setattr("app.api.system.get_trace_manager", lambda: FakeTraceManager())
    monkeypatch.setattr(
        "app.api.system._probe_llm_sync",
        lambda *args, **kwargs: {
            "ok": True,
            "status": "up",
            "message": "环境启动正常",
            "latency_ms": 11,
            "detail": "mock llm",
        },
    )
    monkeypatch.setattr(
        "app.api.system._probe_generic_http_service",
        lambda name, url: {"name": name, "status": "unconfigured", "message": "未配置", "detail": str(url or "")},
    )

    Base.metadata.create_all(sync_engine)

    with Session(sync_engine) as session:
        workspace = Workspace(name="默认工作空间", description="test")
        session.add(workspace)
        session.flush()
        session.add(
            DataSource(
                workspace_id=workspace.id,
                name="铁塔告警清洗数据源",
                type=DataSourceType.CSV,
                connection_string="demo.csv",
                is_active=True,
            )
        )
        session.add(
            Dataset(
                workspace_id=workspace.id,
                name="铁塔告警清洗数据集",
                status=DatasetStatus.ACTIVE,
                processing_status=ProcessingStatus.READY,
                data_source_ids=[1],
                data_source_id=1,
            )
        )
        session.add(
            QueryHistory(
                user_id=1,
                workspace_id=workspace.id,
                question="统计海沧区告警数量",
                row_count=5,
                status="success",
                trace_id="trace-1",
            )
        )
        session.commit()

    async def _run():
        async with async_session_maker() as session:
            return await _build_monitor_summary(session)

    payload = asyncio.run(_run())
    assert payload["data_stats"]["workspace_count"] == 1
    assert payload["data_stats"]["data_source_count"] == 1
    assert payload["data_stats"]["dataset_count"] == 1
    assert payload["data_stats"]["tower_assets"] == 2
    assert payload["data_stats"]["tower_events"] == 3
    assert payload["query_trace"]["total_queries"] == 12
    assert len(payload["tool_registry"]) >= 4
    assert len(payload["external_services"]) == 4

    asyncio.run(async_engine.dispose())
    sync_engine.dispose()
    shutil.rmtree(runtime_dir, ignore_errors=True)
