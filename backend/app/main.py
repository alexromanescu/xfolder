from __future__ import annotations

import logging
import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import AppConfig
from .logstream import LogStreamHandler
from .models import (
    ConfirmDeletionPayload,
    DeletionPlan,
    DeletionPlanPayload,
    DeletionResult,
    ExportFilters,
    FolderLabel,
    GroupContents,
    GroupDiff,
    GroupRecord,
    ScanProgress,
    ScanRequest,
    SimilarityMatrixResponse,
    TreemapResponse,
)
from .store import ScanManager

logger = logging.getLogger("xfolder")

config = AppConfig.from_env()
logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))
logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

log_stream_handler: Optional[LogStreamHandler] = None
if config.log_stream_enabled:
    log_stream_handler = LogStreamHandler()
    logger.addHandler(log_stream_handler)

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


@app.get("/api/scans/{scan_id}/matrix", response_model=SimilarityMatrixResponse)
def get_similarity_matrix(
    scan_id: str,
    min_similarity: float = Query(default=0.5, ge=0.0, le=1.0),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    manager: ScanManager = Depends(get_scan_manager),
) -> SimilarityMatrixResponse:
    return manager.get_similarity_matrix(scan_id, min_similarity=min_similarity, limit=limit, offset=offset)


@app.get("/api/scans/{scan_id}/density/treemap", response_model=TreemapResponse)
def get_density_treemap(
    scan_id: str,
    manager: ScanManager = Depends(get_scan_manager),
) -> TreemapResponse:
    return manager.get_treemap(scan_id)


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


@app.get("/api/scans/{scan_id}/groups/{group_id}/contents", response_model=GroupContents)
def get_group_contents(
    scan_id: str,
    group_id: str,
    manager: ScanManager = Depends(get_scan_manager),
) -> GroupContents:
    return manager.get_group_contents(scan_id, group_id)


@app.get("/api/system/logs/stream")
async def stream_logs(level: Optional[str] = Query(default=None)):
    if not config.log_stream_enabled or not log_stream_handler:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Log streaming disabled")
    requested = (level or config.log_level).upper()
    min_level = getattr(logging, requested, logging.INFO)
    subscriber = log_stream_handler.subscribe()

    async def event_generator():
        queue, loop = subscriber
        try:
            for entry in log_stream_handler.history(min_level):
                yield _format_sse(entry)
            while True:
                entry = await queue.get()
                if entry.level_no >= min_level:
                    yield _format_sse(entry)
        finally:
            log_stream_handler.unsubscribe((queue, loop))

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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


def _format_sse(entry) -> str:
    payload = json.dumps(entry.dict())
    return f"data: {payload}\n\n"
