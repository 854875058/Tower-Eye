from app.core.database import Base, engine
from app.models.models import (
    CSVFile,
    DataSource,
    DataSourceSchema,
    Dataset,
    DatasetMediaResource,
    ImageIndex,
    QueryHistory,
    User,
    UserWorkspace,
    VideoSegmentIndex,
    WorkbenchChunk,
    WorkbenchDataset,
    WorkbenchResource,
    WorkbenchSubscription,
    Workspace,
)
from scripts.migrate_media_schema import migrate_media_schema
from scripts.migrate_workbench_schema import migrate_workbench_schema


def init_db() -> None:
    Base.metadata.create_all(engine)
    migrate_media_schema(engine)
    migrate_workbench_schema(engine)
    print("数据库表创建/迁移成功!")


if __name__ == "__main__":
    init_db()
