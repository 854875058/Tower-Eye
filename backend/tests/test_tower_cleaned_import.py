from __future__ import annotations

import asyncio
import shutil
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

import app.core.database as db_module
from app.core.database import Base
from app.models.models import CSVFile, DataSource, DataSourceSchema, Dataset, Workspace
from app.services.tower_cleaned_import import TowerCleanedImportService


def build_tower_metadata_db(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE events (
                event_id TEXT PRIMARY KEY,
                asset_id TEXT,
                event_type TEXT,
                alarm_time TEXT,
                county_name TEXT,
                town_name TEXT,
                device_name TEXT,
                algorithm_name TEXT,
                confidence_level REAL,
                video_path TEXT,
                img_src_path TEXT,
                img_icon_path TEXT,
                summary TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO events (
                event_id, asset_id, event_type, alarm_time, county_name, town_name,
                device_name, algorithm_name, confidence_level, video_path,
                img_src_path, img_icon_path, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "evt-1",
                "asset-1",
                "车辆闯入监控告警",
                "2025-11-18 13:39:00",
                "海沧区",
                "东孚街道",
                "测试设备1",
                "车辆闯入监控",
                0.88,
                "warning_file/demo.mp4",
                "warning_img/demo_01.jpg",
                "warning_img/demo_02.jpg",
                "测试事件摘要",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_import_tower_cleaned_dataset_is_idempotent(monkeypatch):
    runtime_dir = Path.cwd() / "backend" / "data" / "_tower_import_test_runtime"
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir, ignore_errors=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    db_file = runtime_dir / "test_chatbot.db"
    metadata_db = build_tower_metadata_db(runtime_dir / "tower_metadata.db")
    export_dir = runtime_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

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
    monkeypatch.setattr("app.services.tower_cleaned_import.TOWER_METADATA_DB", metadata_db)
    monkeypatch.setattr("app.services.tower_cleaned_import.TOWER_EXPORT_DIR", export_dir)

    Base.metadata.create_all(sync_engine)

    with Session(sync_engine) as session:
        workspace = Workspace(name="测试工作空间", description="test")
        session.add(workspace)
        session.commit()
        workspace_id = workspace.id

    async def _run_import():
        async with async_session_maker() as session:
            service = TowerCleanedImportService(session)
            first = await service.import_cleaned_events(workspace_id=workspace_id)
            second = await service.import_cleaned_events(workspace_id=workspace_id)
            return first.id, second.id, first.data_source_ids, second.data_source_ids

    first_id, second_id, first_sources, second_sources = asyncio.run(_run_import())

    assert first_id == second_id
    assert first_sources == second_sources
    assert len(first_sources) == 1

    with Session(sync_engine) as session:
        datasets = session.query(Dataset).all()
        data_sources = session.query(DataSource).all()
        csv_files = session.query(CSVFile).all()
        schemas = session.query(DataSourceSchema).all()

        assert len(datasets) == 1
        assert len(data_sources) == 1
        assert len(csv_files) == 1
        assert len(schemas) >= 5
        assert Path(csv_files[0].file_path).exists()
        assert datasets[0].name == "铁塔告警清洗数据集"
        assert datasets[0].status.value == "active"

    asyncio.run(async_engine.dispose())
    sync_engine.dispose()
    shutil.rmtree(runtime_dir, ignore_errors=True)
