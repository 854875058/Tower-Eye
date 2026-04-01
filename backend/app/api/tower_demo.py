from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import get_current_user
from app.models.models import User
from app.schemas.schemas import TowerOntologyConfigPayload
from app.services.tower_demo import TowerWarningDemoService

router = APIRouter()


@router.get("/dashboard")
async def get_tower_demo_dashboard(_: User = Depends(get_current_user)):
    try:
        return TowerWarningDemoService().get_dashboard()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/graph")
async def get_tower_demo_graph(_: User = Depends(get_current_user)):
    try:
        return TowerWarningDemoService().get_graph()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/ontology")
async def get_tower_demo_ontology(_: User = Depends(get_current_user)):
    try:
        return TowerWarningDemoService().get_ontology_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/ontology")
async def save_tower_demo_ontology(
    payload: TowerOntologyConfigPayload,
    _: User = Depends(get_current_user),
):
    try:
        return TowerWarningDemoService().save_ontology_config(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ontology/reset")
async def reset_tower_demo_ontology(_: User = Depends(get_current_user)):
    try:
        return TowerWarningDemoService().reset_ontology_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/lineage/{event_id}")
async def get_tower_demo_lineage(
    event_id: str,
    _: User = Depends(get_current_user),
):
    try:
        return TowerWarningDemoService().get_event_lineage(event_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/assistant")
async def ask_tower_demo_assistant(
    payload: dict,
    _: User = Depends(get_current_user),
):
    question = str((payload or {}).get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    try:
        return TowerWarningDemoService().answer(question)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
