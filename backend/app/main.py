from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import AppConfig
from .models import (
    ConfirmDeletionPayload,
    DeletionPlan,
    DeletionPlanPayload,
    DeletionResult,
    ExportFilters,
    FolderLabel,
    GroupDiff,
    GroupRecord,
    ScanProgress,
    ScanRequest,
)
from .store import ScanManager

logger = logging.getLogger("xfolder")

config = AppConfig.from_env()
config.config_path.mkdir(parents=True, exist_ok=True)
scan_manager = ScanManager(config)

app = FastAPI(title="Folder Similarity Scanner", version="2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_scan_manager() -> ScanManager:
    return scan_manager


@app.on_event("shutdown")
def shutdown_event() -> None:
    scan_manager.shutdown()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/scans", response_model=ScanProgress, status_code=status.HTTP_202_ACCEPTED)
def start_scan(request: ScanRequest, manager: ScanManager = Depends(get_scan_manager)) -> ScanProgress:
    job = manager.start_scan(request)
    return manager.get_progress(job.scan_id)


@app.get("/api/scans", response_model=list[ScanProgress])
def list_scans(manager: ScanManager = Depends(get_scan_manager)) -> list[ScanProgress]:
    return [manager.get_progress(job.scan_id) for job in manager.list_jobs()]


@app.get("/api/scans/{scan_id}", response_model=ScanProgress)
def get_scan(scan_id: str, manager: ScanManager = Depends(get_scan_manager)) -> ScanProgress:
    return manager.get_progress(scan_id)


@app.get("/api/scans/{scan_id}/groups", response_model=list[GroupRecord])
def get_groups(
    scan_id: str,
    label: Optional[FolderLabel] = None,
    manager: ScanManager = Depends(get_scan_manager),
) -> list[GroupRecord]:
    return manager.get_groups(scan_id, label)


@app.post("/api/scans/{scan_id}/export")
def export_groups(
    scan_id: str,
    fmt: str,
    include: Optional[list[str]] = Query(default=None),
    exclude: Optional[list[str]] = Query(default=None),
    manager: ScanManager = Depends(get_scan_manager),
) -> Response:
    if fmt not in {"json", "csv", "md"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported export format")
    filters = ExportFilters(
        include=include or [],
        exclude=exclude or [],
    )
    payload = manager.export(scan_id, fmt, filters)
    media_type = {
        "json": "application/json",
        "csv": "text/csv",
        "md": "text/markdown",
    }[fmt]
    return Response(content=payload, media_type=media_type)


@app.post("/api/scans/{scan_id}/deletion/plan", response_model=DeletionPlan)
def create_plan(
    scan_id: str,
    payload: DeletionPlanPayload,
    manager: ScanManager = Depends(get_scan_manager),
) -> DeletionPlan:
    return manager.create_deletion_plan(scan_id, payload)


@app.post("/api/deletions/{plan_id}/confirm", response_model=DeletionResult)
def confirm_plan(
    plan_id: str,
    payload: ConfirmDeletionPayload,
    manager: ScanManager = Depends(get_scan_manager),
) -> DeletionResult:
    return manager.execute_plan(plan_id, payload.token)


@app.get("/api/scans/{scan_id}/groups/{group_id}/diff", response_model=GroupDiff)
def get_group_diff(
    scan_id: str,
    group_id: str,
    left: str,
    right: str,
    manager: ScanManager = Depends(get_scan_manager),
) -> GroupDiff:
    return manager.get_group_diff(scan_id, group_id, left, right)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):  # type: ignore[override]
    logger.exception("Unhandled exception on %s: %s", request.url, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


frontend_path = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
