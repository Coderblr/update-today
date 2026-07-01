from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agents.locator_file_parsers import LocatorFileParseError
from app.agents.locator_usage_agent import compute_usage_stats
from app.agents.locator_validation_agent import validate as run_validation
from app.core.database import get_db
from app.models.locator import LocatorEntry
from app.schemas.crawl import LocatorEntryResponse
from app.schemas.locator_repository import (
    LocatorEntryUpdateRequest,
    LocatorRepositoryVersionResponse,
    LocatorUsageStatsResponse,
    MergeVersionsRequest,
    ValidationReportResponse,
    ValidationRequest,
)
from app.services import locator_repository_service

router = APIRouter(prefix="/locator-repository", tags=["locator-repository"])


@router.post("/upload", response_model=list[LocatorRepositoryVersionResponse])
async def upload_locator_files(files: list[UploadFile], db: Session = Depends(get_db)):
    created_versions = []
    for file in files:
        raw_bytes = await file.read()
        try:
            created_versions.extend(locator_repository_service.ingest_locator_file(db, file.filename, raw_bytes))
        except LocatorFileParseError as exc:
            raise HTTPException(status_code=400, detail=f"{file.filename}: {exc}") from exc
    return created_versions


@router.post("/upload-java-po", response_model=list[LocatorRepositoryVersionResponse])
async def upload_java_po_file(
    file: UploadFile,
    transaction_number: str = Form(...),
    screen_name: str = Form(...),
    db: Session = Depends(get_db),
):
    raw_bytes = await file.read()
    try:
        return locator_repository_service.ingest_java_po_file(
            db, file.filename, raw_bytes, transaction_number, screen_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/versions", response_model=list[LocatorRepositoryVersionResponse])
def get_versions(transaction_number: str, db: Session = Depends(get_db)):
    return locator_repository_service.list_versions(db, transaction_number)


@router.post("/versions/{version_id}/activate", response_model=LocatorRepositoryVersionResponse)
def activate_version(version_id: str, transaction_number: str, db: Session = Depends(get_db)):
    try:
        return locator_repository_service.set_active_version(db, transaction_number, version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/entries/{entry_id}", response_model=LocatorEntryResponse)
def update_entry(entry_id: str, payload: LocatorEntryUpdateRequest, db: Session = Depends(get_db)):
    entry = db.get(LocatorEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Locator entry not found")
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field_name, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, db: Session = Depends(get_db)):
    entry = db.get(LocatorEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Locator entry not found")
    db.delete(entry)
    db.commit()
    return {"status": "deleted"}


@router.post("/validate", response_model=ValidationReportResponse)
def validate_repository(payload: ValidationRequest, db: Session = Depends(get_db)):
    report = run_validation(db, payload.transaction_number, payload.feature_files)
    return ValidationReportResponse(**report.__dict__)


@router.get("/stats", response_model=list[LocatorUsageStatsResponse])
def get_usage_stats(transaction_number: str, db: Session = Depends(get_db)):
    stats = compute_usage_stats(db, transaction_number)
    return [LocatorUsageStatsResponse(**s.__dict__) for s in stats]


@router.post("/merge", response_model=LocatorRepositoryVersionResponse)
def merge_versions(payload: MergeVersionsRequest, db: Session = Depends(get_db)):
    try:
        return locator_repository_service.merge_versions(db, payload.transaction_number, payload.version_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
