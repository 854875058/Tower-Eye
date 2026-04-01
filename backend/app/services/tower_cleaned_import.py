from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.models import CSVFile, DataSource, DataSourceType, DataSourceSchema, Dataset, DatasetStatus, ProcessingStatus
from app.services.datasource import DataSourceService

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]
TOWER_METADATA_DB = PROJECT_ROOT / "data" / "metadata.db"
TOWER_EXPORT_DIR = BACKEND_DIR / "data" / "uploads"
TOWER_EXPORT_FILENAME = "tower_warning_events_cleaned.csv"

DEFAULT_DATA_SOURCE_NAME = "铁塔告警清洗数据源"
DEFAULT_DATASET_NAME = "铁塔告警清洗数据集"
DEFAULT_DATASET_DESCRIPTION = "基于铁塔清洗后的 metadata.db events 表自动接入，供当前系统查询页和智能问答直接使用。"


def _normalize_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value


def export_tower_events_to_csv(
    *,
    metadata_db: Path = TOWER_METADATA_DB,
    export_dir: Path = TOWER_EXPORT_DIR,
    filename: str = TOWER_EXPORT_FILENAME,
) -> tuple[Path, int, int]:
    """将清洗后的 events 表导出为当前系统可消费的单表 CSV。"""
    if not metadata_db.exists():
        raise FileNotFoundError(f"未找到清洗后的 metadata.db: {metadata_db}")

    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / filename

    conn = sqlite3.connect(str(metadata_db))
    conn.row_factory = sqlite3.Row
    try:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()]
        if not columns:
            raise ValueError("metadata.db 中未找到 events 表字段")

        rows = conn.execute("SELECT * FROM events ORDER BY alarm_time DESC, event_id DESC").fetchall()
        if not rows:
            raise ValueError("metadata.db 中未找到可导入的事件数据")

        with open(export_path, "w", encoding="utf-8-sig", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: _normalize_csv_value(row[column]) for column in columns})

        return export_path, len(rows), len(columns)
    finally:
        conn.close()


class TowerCleanedImportService:
    """将铁塔清洗后的结构化告警数据接入到当前系统的数据源/数据集体系。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.data_source_service = DataSourceService(db)

    async def import_cleaned_events(
        self,
        *,
        workspace_id: int,
        data_source_name: str = DEFAULT_DATA_SOURCE_NAME,
        dataset_name: str = DEFAULT_DATASET_NAME,
        description: str | None = DEFAULT_DATASET_DESCRIPTION,
    ) -> Dataset:
        export_path, row_count, column_count = export_tower_events_to_csv()

        data_source = await self._upsert_csv_data_source(
            workspace_id=workspace_id,
            name=data_source_name,
            export_path=export_path,
            row_count=row_count,
            column_count=column_count,
        )
        dataset = await self._upsert_dataset(
            workspace_id=workspace_id,
            data_source=data_source,
            name=dataset_name,
            description=description or DEFAULT_DATASET_DESCRIPTION,
        )
        await self.db.refresh(dataset)
        return dataset

    async def _upsert_csv_data_source(
        self,
        *,
        workspace_id: int,
        name: str,
        export_path: Path,
        row_count: int,
        column_count: int,
    ) -> DataSource:
        result = await self.db.execute(
            select(DataSource).where(
                and_(
                    DataSource.workspace_id == workspace_id,
                    DataSource.name == name,
                    DataSource.is_active == True,
                )
            )
        )
        data_source = result.scalar_one_or_none()

        if data_source is None:
            data_source = DataSource(
                workspace_id=workspace_id,
                name=name,
                type=DataSourceType.CSV,
                connection_string=str(export_path),
                is_active=True,
            )
            self.db.add(data_source)
            await self.db.flush()
        else:
            data_source.type = DataSourceType.CSV
            data_source.connection_string = str(export_path)
            data_source.is_active = True
            await self.db.execute(delete(CSVFile).where(CSVFile.data_source_id == data_source.id))
            await self.db.execute(delete(DataSourceSchema).where(DataSourceSchema.data_source_id == data_source.id))

        csv_file = CSVFile(
            data_source_id=data_source.id,
            filename=export_path.name,
            file_path=str(export_path),
            file_size=os.path.getsize(export_path),
            row_count=row_count,
            column_count=column_count,
        )
        self.db.add(csv_file)
        await self.db.commit()
        await self.db.refresh(data_source)

        await self.data_source_service.refresh_schema(data_source)
        await self.db.refresh(data_source)
        return data_source

    async def _upsert_dataset(
        self,
        *,
        workspace_id: int,
        data_source: DataSource,
        name: str,
        description: str,
    ) -> Dataset:
        result = await self.db.execute(
            select(Dataset).where(
                and_(
                    Dataset.workspace_id == workspace_id,
                    Dataset.name == name,
                    Dataset.status != DatasetStatus.DEPRECATED,
                )
            )
        )
        dataset = result.scalar_one_or_none()

        default_dimensions = [
            {"name": "省份", "column": "province_name"},
            {"name": "城市", "column": "city_name"},
            {"name": "区县", "column": "county_name"},
            {"name": "街道", "column": "town_name"},
            {"name": "设备", "column": "device_name"},
            {"name": "算法", "column": "algorithm_name"},
            {"name": "告警类型", "column": "event_type"},
            {"name": "告警时间", "column": "alarm_time"},
        ]
        default_aliases = [
            {"alias": "告警", "column": "event_type"},
            {"alias": "告警类型", "column": "event_type"},
            {"alias": "区县", "column": "county_name"},
            {"alias": "街道", "column": "town_name"},
            {"alias": "设备", "column": "device_name"},
            {"alias": "算法", "column": "algorithm_name"},
            {"alias": "置信度", "column": "confidence_level"},
            {"alias": "视频", "column": "video_path"},
            {"alias": "图片", "column": "img_src_path"},
        ]

        if dataset is None:
            dataset = Dataset(
                workspace_id=workspace_id,
                data_source_id=data_source.id,
                data_source_ids=[data_source.id],
                name=name,
                description=description,
                status=DatasetStatus.ACTIVE,
                processing_status=ProcessingStatus.READY,
                progress=100.0,
                metrics=[],
                dimensions=default_dimensions,
                aliases=default_aliases,
                business_rules="该数据集来自铁塔清洗后的告警事件主表 events，可直接用于区域、设备、算法、时间等维度查询。",
                media_count=0,
                processed_count=0,
                failed_count=0,
            )
            self.db.add(dataset)
        else:
            dataset.data_source_id = data_source.id
            dataset.data_source_ids = [data_source.id]
            dataset.description = description
            dataset.status = DatasetStatus.ACTIVE
            dataset.processing_status = ProcessingStatus.READY
            dataset.progress = 100.0
            dataset.error_message = None
            dataset.dimensions = default_dimensions
            dataset.aliases = default_aliases
            dataset.business_rules = "该数据集来自铁塔清洗后的告警事件主表 events，可直接用于区域、设备、算法、时间等维度查询。"
            dataset.version = int(dataset.version or 1) + 1

        await self.db.commit()
        await self.db.refresh(dataset)
        logger.info(
            "铁塔清洗数据接入完成: workspace=%s, data_source=%s, dataset=%s",
            workspace_id,
            data_source.id,
            dataset.id,
        )
        return dataset
