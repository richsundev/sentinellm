from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireWrite, get_db
from sentinellm.api.schemas.generate import GenerateRequest
from sentinellm.api.schemas.trace import TraceOut
from sentinellm.services.generation import generate as generate_service

router = APIRouter(prefix="/api/v1/generate", tags=["generate"])


@router.post("", response_model=TraceOut, dependencies=[Depends(RequireWrite)])
async def generate(request: GenerateRequest, db: AsyncSession = Depends(get_db)) -> TraceOut:
    """Run the full retrieval -> routing -> cache -> generation -> cost
    pipeline for a single request and persist the resulting trace.
    """
    trace = await generate_service(db, request)
    return TraceOut.model_validate(trace)
