from fastapi import APIRouter

from app.api import annotations, auth, data_sources, datasets, history, queries, system, tower_demo, workbench

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["Auth"])
router.include_router(data_sources.router, prefix="/data-sources", tags=["Data Sources"])
router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
router.include_router(annotations.router, prefix="/annotations", tags=["Annotations"])
router.include_router(queries.router, prefix="/queries", tags=["Queries"])
router.include_router(history.router, prefix="/history", tags=["History"])
router.include_router(system.router, prefix="/system", tags=["System"])
router.include_router(workbench.router, prefix="/workbench", tags=["Data Workbench"])
router.include_router(tower_demo.router, prefix="/tower-demo", tags=["Tower Demo"])
