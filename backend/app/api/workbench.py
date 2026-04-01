import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.datasets import verify_workspace_access
from app.core.database import get_db
from app.models.models import User
from app.schemas.schemas import (
    WorkbenchDatasetCreate,
    WorkbenchDatasetDetailResponse,
    WorkbenchProcessingRequest,
    WorkbenchDatasetResponse,
    WorkbenchResourceResponse,
    WorkbenchSampleImportRequest,
    WorkbenchSearchRequest,
    WorkbenchSearchResult,
    WorkbenchSubscriptionCreate,
    WorkbenchSubscriptionResponse,
    WorkbenchSubscriptionUpdate,
)
from app.services.workbench import WorkbenchService, ensure_workbench_dirs
from app.services.workbench_tasks import get_workbench_task_manager

router = APIRouter()


def _build_dataset_detail_response(dataset, resources) -> WorkbenchDatasetDetailResponse:
    return WorkbenchDatasetDetailResponse(
        id=dataset.id,
        workspace_id=dataset.workspace_id,
        name=dataset.name,
        description=dataset.description,
        processing_status=dataset.processing_status.value if hasattr(dataset.processing_status, "value") else str(dataset.processing_status),
        resource_count=dataset.resource_count,
        processed_count=dataset.processed_count,
        failed_count=dataset.failed_count,
        chunk_count=dataset.chunk_count,
        vector_count=dataset.vector_count,
        total_text_length=dataset.total_text_length,
        source_summary=dataset.source_summary,
        processing_summary=dataset.processing_summary,
        error_message=dataset.error_message,
        last_ingested_at=dataset.last_ingested_at,
        processing_updated_at=dataset.processing_updated_at,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
        resources=[
            WorkbenchResourceResponse(
                id=item.id,
                dataset_id=item.dataset_id,
                source_kind=item.source_kind.value if hasattr(item.source_kind, "value") else str(item.source_kind),
                source_uri=item.source_uri,
                stored_path=item.stored_path,
                file_name=item.file_name,
                file_extension=item.file_extension,
                file_category=item.file_category,
                mime_type=item.mime_type,
                file_size=item.file_size,
                checksum=item.checksum,
                parser_name=item.parser_name,
                status=item.status.value if hasattr(item.status, "value") else str(item.status),
                chunk_count=item.chunk_count,
                text_length=item.text_length,
                extraction_metadata=item.extraction_metadata,
                labels=list(item.labels or []),
                category_label=item.category_label,
                cluster_id=item.cluster_id,
                cluster_label=item.cluster_label,
                summary_text=item.summary_text,
                quality_score=item.quality_score,
                processing_metadata=item.processing_metadata,
                error_message=item.error_message,
                created_at=item.created_at,
                updated_at=item.updated_at,
                last_processed_at=item.last_processed_at,
            )
            for item in resources
        ],
    )


def _build_subscription_response(subscription) -> WorkbenchSubscriptionResponse:
    source_config = dict(subscription.source_config or {}) if isinstance(subscription.source_config, dict) else subscription.source_config
    if isinstance(source_config, dict) and source_config.get("password"):
        source_config["password"] = "__configured__"
    return WorkbenchSubscriptionResponse(
        id=subscription.id,
        workspace_id=subscription.workspace_id,
        dataset_id=subscription.dataset_id,
        name=subscription.name,
        source_kind=subscription.source_kind.value if hasattr(subscription.source_kind, "value") else str(subscription.source_kind),
        is_enabled=subscription.is_enabled,
        interval_minutes=subscription.interval_minutes,
        local_paths=list(subscription.local_paths or []),
        source_config=source_config,
        last_status=subscription.last_status.value if hasattr(subscription.last_status, "value") else str(subscription.last_status),
        last_message=subscription.last_message,
        last_run_at=subscription.last_run_at,
        next_run_at=subscription.next_run_at,
        last_new_resources=subscription.last_new_resources,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


async def _parse_workbench_create_request(
    request: Request,
) -> tuple[WorkbenchDatasetCreate, list[UploadFile]]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        payload = await request.json()
        return WorkbenchDatasetCreate.model_validate(payload), []

    form = await request.form()
    raw_payload = form.get("payload")
    if not raw_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing payload field")

    payload_data = json.loads(str(raw_payload))
    payload = WorkbenchDatasetCreate.model_validate(payload_data)
    files = [item for item in form.getlist("files") if getattr(item, "filename", None)]
    return payload, files


@router.post("/datasets", response_model=WorkbenchDatasetResponse)
async def create_workbench_dataset(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    payload, files = await _parse_workbench_create_request(request)
    if not await verify_workspace_access(payload.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the workspace")

    ensure_workbench_dirs()
    service = WorkbenchService(db)
    try:
        dataset = await service.create_dataset(
            workspace_id=payload.workspace_id,
            name=payload.name,
            description=payload.description,
            uploads=files,
            file_paths=payload.file_paths,
            sftp_config=payload.sftp_config.model_dump() if payload.sftp_config else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await get_workbench_task_manager().enqueue_dataset(dataset.id)
    await db.refresh(dataset)
    return dataset


@router.post("/import/tower-warning-sample", response_model=WorkbenchDatasetResponse)
async def import_tower_warning_sample(
    data: WorkbenchSampleImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await verify_workspace_access(data.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the workspace")

    ensure_workbench_dirs()
    service = WorkbenchService(db)
    try:
        dataset = await service.import_tower_warning_sample_dataset(
            workspace_id=data.workspace_id,
            name=data.name,
            description=data.description,
            max_records=data.max_records,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await get_workbench_task_manager().enqueue_dataset(dataset.id)
    await db.refresh(dataset)
    return dataset


@router.get("/datasets", response_model=list[WorkbenchDatasetResponse])
async def list_workbench_datasets(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await verify_workspace_access(workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the workspace")

    service = WorkbenchService(db)
    return await service.list_datasets(workspace_id)


@router.get("/datasets/{dataset_id}", response_model=WorkbenchDatasetDetailResponse)
async def get_workbench_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkbenchService(db)
    detail = await service.get_dataset_detail(dataset_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    dataset, resources = detail
    if not await verify_workspace_access(dataset.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the dataset")
    return _build_dataset_detail_response(dataset, resources)


@router.post("/datasets/{dataset_id}/search", response_model=list[WorkbenchSearchResult])
async def search_workbench_dataset(
    dataset_id: int,
    data: WorkbenchSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkbenchService(db)
    dataset = await service.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    if not await verify_workspace_access(dataset.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the dataset")
    return await service.search_dataset(dataset_id, data.query, data.top_k)


@router.post("/datasets/{dataset_id}/process", response_model=WorkbenchDatasetDetailResponse)
async def process_workbench_dataset(
    dataset_id: int,
    data: WorkbenchProcessingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkbenchService(db)
    dataset = await service.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    if not await verify_workspace_access(dataset.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the dataset")

    try:
        detail = await service.process_dataset(
            dataset_id,
            extract_labels=data.extract_labels,
            cluster_count=data.cluster_count,
            refresh_summary=data.refresh_summary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    processed_dataset, resources = detail
    return _build_dataset_detail_response(processed_dataset, resources)


@router.get("/datasets/{dataset_id}/export")
async def export_workbench_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkbenchService(db)
    dataset = await service.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    if not await verify_workspace_access(dataset.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the dataset")

    payload = await service.export_dataset_payload(dataset_id)
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    file_name = f"workbench-dataset-{dataset_id}.json"
    headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
    return Response(content=content, media_type="application/json; charset=utf-8", headers=headers)


@router.get("/datasets/{dataset_id}/resources/{resource_id}/download")
async def download_workbench_resource(
    dataset_id: int,
    resource_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkbenchService(db)
    detail = await service.get_dataset_detail(dataset_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    dataset, resources = detail
    if not await verify_workspace_access(dataset.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the dataset")

    resource = next((item for item in resources if item.id == resource_id), None)
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    file_path = Path(resource.stored_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file not found")
    return FileResponse(path=str(file_path), filename=resource.file_name)


@router.post("/subscriptions", response_model=WorkbenchSubscriptionResponse)
async def create_workbench_subscription(
    data: WorkbenchSubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await verify_workspace_access(data.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the workspace")

    service = WorkbenchService(db)
    try:
        subscription = await service.create_subscription(
            workspace_id=data.workspace_id,
            dataset_id=data.dataset_id,
            name=data.name,
            source_kind=data.source_kind,
            interval_minutes=data.interval_minutes,
            is_enabled=data.is_enabled,
            local_paths=data.local_paths,
            sftp_config=data.sftp_config.model_dump() if data.sftp_config else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _build_subscription_response(subscription)


@router.get("/subscriptions", response_model=list[WorkbenchSubscriptionResponse])
async def list_workbench_subscriptions(
    workspace_id: int,
    dataset_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await verify_workspace_access(workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the workspace")

    service = WorkbenchService(db)
    subscriptions = await service.list_subscriptions(workspace_id, dataset_id)
    return [_build_subscription_response(item) for item in subscriptions]


@router.patch("/subscriptions/{subscription_id}", response_model=WorkbenchSubscriptionResponse)
async def update_workbench_subscription(
    subscription_id: int,
    data: WorkbenchSubscriptionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkbenchService(db)
    subscription = await service.get_subscription(subscription_id)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    if not await verify_workspace_access(subscription.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the subscription")

    try:
        updated = await service.update_subscription(
            subscription_id,
            name=data.name,
            interval_minutes=data.interval_minutes,
            is_enabled=data.is_enabled,
            local_paths=data.local_paths,
            sftp_config=data.sftp_config.model_dump() if data.sftp_config else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _build_subscription_response(updated)


@router.post("/subscriptions/{subscription_id}/run", response_model=WorkbenchSubscriptionResponse)
async def run_workbench_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkbenchService(db)
    subscription = await service.get_subscription(subscription_id)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    if not await verify_workspace_access(subscription.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the subscription")

    try:
        refreshed, new_count = await service.run_subscription(subscription_id)
        if new_count > 0:
            await get_workbench_task_manager().enqueue_dataset(refreshed.dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _build_subscription_response(refreshed)


@router.delete("/subscriptions/{subscription_id}")
async def delete_workbench_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkbenchService(db)
    subscription = await service.get_subscription(subscription_id)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    if not await verify_workspace_access(subscription.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the subscription")

    await service.delete_subscription(subscription_id)
    return {"message": "Deleted"}


@router.delete("/datasets/{dataset_id}")
async def delete_workbench_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkbenchService(db)
    dataset = await service.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    if not await verify_workspace_access(dataset.workspace_id, current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the dataset")

    await service.delete_dataset(dataset_id)
    return {"message": "Deleted"}
