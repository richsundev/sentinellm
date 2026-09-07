from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireWrite, get_db, scope_of
from sentinellm.api.schemas.generate import GenerateRequest
from sentinellm.api.schemas.trace import TraceOut
from sentinellm.db.models import APIKey
from sentinellm.services.generation import generate as generate_service

router = APIRouter(prefix="/api/v1/generate", tags=["generate"])


@router.post("", response_model=TraceOut)
async def generate(
    request: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireWrite),
) -> TraceOut:
    """Run the full retrieval -> routing -> cache -> generation -> cost
    pipeline for a single request and persist the resulting trace.
    """
    if not scope_of(api_key).contains(request.application_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "API key is scoped to a different application"
        )
    trace = await generate_service(db, request)
    return TraceOut.model_validate(trace)
