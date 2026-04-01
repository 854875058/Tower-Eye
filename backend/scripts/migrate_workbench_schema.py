from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import Engine, inspect, text


WORKBENCH_DATASET_COLUMNS = {
    "processing_summary": "JSON",
    "processing_updated_at": "DATETIME",
}

WORKBENCH_RESOURCE_COLUMNS = {
    "labels": "JSON",
    "category_label": "VARCHAR(100)",
    "cluster_id": "INTEGER",
    "cluster_label": "VARCHAR(255)",
    "summary_text": "TEXT",
    "quality_score": "FLOAT",
    "processing_metadata": "JSON",
}


def _ensure_columns(engine: Engine, table_name: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    with engine.begin() as conn:
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))


def _execute_batch(engine: Engine, statements: Iterable[str]) -> None:
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def migrate_workbench_schema(engine: Optional[Engine] = None) -> None:
    if engine is None:
        from app.core.database import engine as default_engine
        engine = default_engine

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "workbench_datasets" in tables:
        _ensure_columns(engine, "workbench_datasets", WORKBENCH_DATASET_COLUMNS)
    if "workbench_resources" in tables:
        _ensure_columns(engine, "workbench_resources", WORKBENCH_RESOURCE_COLUMNS)

    _execute_batch(
        engine,
        [
            """
            CREATE TABLE IF NOT EXISTS workbench_subscriptions (
                id INTEGER PRIMARY KEY,
                workspace_id INTEGER NOT NULL,
                dataset_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                source_kind TEXT NOT NULL,
                is_enabled BOOLEAN DEFAULT 1,
                interval_minutes INTEGER DEFAULT 60,
                local_paths JSON,
                source_config JSON,
                last_status TEXT DEFAULT 'idle',
                last_message TEXT,
                last_run_at DATETIME,
                next_run_at DATETIME,
                last_new_resources INTEGER DEFAULT 0,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(workspace_id) REFERENCES workspaces (id),
                FOREIGN KEY(dataset_id) REFERENCES workbench_datasets (id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS ix_workbench_subscriptions_workspace_enabled ON workbench_subscriptions (workspace_id, is_enabled)",
            "CREATE INDEX IF NOT EXISTS ix_workbench_subscriptions_next_run ON workbench_subscriptions (next_run_at)",
        ],
    )


if __name__ == "__main__":
    migrate_workbench_schema()
    print("workbench schema migration completed")
