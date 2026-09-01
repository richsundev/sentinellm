from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, RequireWrite, get_db
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.dataset import DatasetCreate, DatasetOut, DatasetRecordOut
from sentinellm.db.models import Dataset, DatasetRecord
from sentinellm.services.dataset_import import DatasetImportError, parse_dataset_file

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])
_MAX_IMPORT_BYTES = 5 * 1024 * 1024


async def _to_out(db: AsyncSession, row: Dataset) -> DatasetOut:
    count = (
        await db.execute(
            select(func.count())
            .select_from(DatasetRecord)
            .where(DatasetRecord.dataset_id == row.id)
        )
    ).scalar_one()
    out = DatasetOut.model_validate(row)
    out.record_count = count
    return out


@router.post(
    "",
    response_model=DatasetOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireWrite)],
)
async def create_dataset(payload: DatasetCreate, db: AsyncSession = Depends(get_db)) -> DatasetOut:
    dataset = Dataset(name=payload.name, version=payload.version, description=payload.description)
    dataset.records = [
        DatasetRecord(
            question=r.question,
            context=r.context,
            expected_answer=r.expected_answer,
            record_metadata=r.metadata,
        )
        for r in payload.records
    ]
    db.add(dataset)
    await db.flush()
    return await _to_out(db, dataset)


@router.post(
    "/import",
    response_model=DatasetOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireWrite)],
)
async def import_dataset(
    name: str = Form(...),
    version: str = Form(...),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> DatasetOut:
    """Bulk dataset creation from an uploaded `.jsonl` or `.csv` file — the
    file-based counterpart to `POST /datasets`' inline JSON records, for
    importing an existing benchmark set instead of hand-typing it.
    """
    raw = await file.read()
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file exceeds the 5MB import limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"file is not valid UTF-8: {exc}") from exc

    try:
        records = parse_dataset_file(file.filename or "", text)
    except DatasetImportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    dataset = Dataset(name=name, version=version, description=description)
    dataset.records = [
        DatasetRecord(
            question=r.question,
            context=r.context,
            expected_answer=r.expected_answer,
            record_metadata=r.metadata,
        )
        for r in records
    ]
    db.add(dataset)
    await db.flush()
    return await _to_out(db, dataset)


@router.get("", response_model=Page[DatasetOut], dependencies=[Depends(RequireRead)])
async def list_datasets(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[DatasetOut]:
    total = (await db.execute(select(func.count()).select_from(Dataset))).scalar_one()
    rows = (
        (
            await db.execute(
                select(Dataset).order_by(Dataset.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    items = [await _to_out(db, r) for r in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{dataset_id}", response_model=DatasetOut, dependencies=[Depends(RequireRead)])
async def get_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)) -> DatasetOut:
    row = await db.get(Dataset, dataset_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset '{dataset_id}' not found")
    return await _to_out(db, row)


@router.get(
    "/{dataset_id}/records",
    response_model=Page[DatasetRecordOut],
    dependencies=[Depends(RequireRead)],
)
async def list_dataset_records(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[DatasetRecordOut]:
    count_stmt = (
        select(func.count())
        .select_from(DatasetRecord)
        .where(DatasetRecord.dataset_id == dataset_id)
    )
    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        select(DatasetRecord)
        .where(DatasetRecord.dataset_id == dataset_id)
        .order_by(DatasetRecord.id)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return Page(
        items=[DatasetRecordOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
