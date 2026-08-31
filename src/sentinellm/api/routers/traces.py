from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinellm.api.deps import RequireRead, RequireWrite, get_db
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.trace import TraceCreate, TraceOut
from sentinellm.core.config import get_settings
from sentinellm.core.ids import new_request_id, new_trace_id
from sentinellm.core.logging import get_logger
from sentinellm.core.queue import enqueue_evaluation
from sentinellm.db.models import Evaluation, Trace, TraceSpan
from sentinellm.pricing.calculator import calculate_cost
from sentinellm.security.pii import redact_pii

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/traces", tags=["traces"])

_LOAD_OPTS = (
    selectinload(Trace.spans),
    selectinload(Trace.evaluation).selectinload(Evaluation.metrics),
    selectinload(Trace.evaluation).selectinload(Evaluation.claims),
    selectinload(Trace.routing_decision),
)


@router.post(
    "",
    response_model=TraceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequireWrite)],
)
async def ingest_trace(payload: TraceCreate, db: AsyncSession = Depends(get_db)) -> TraceOut:
    """Ingest a trace already produced by a client application (post-hoc
    reporting via the SDK, as opposed to `/generate`, which SentinelLLM
    executes itself). Idempotent on `trace_id`: re-submitting the same
    `trace_id` returns the original trace unchanged rather than creating a
    duplicate or re-queuing evaluation.
    """
    trace_id = payload.trace_id or new_trace_id()
    existing = await db.execute(
        select(Trace).where(Trace.trace_id == trace_id).options(*_LOAD_OPTS)
    )
    if (row := existing.scalar_one_or_none()) is not None:
        return TraceOut.model_validate(row)

    cost = payload.estimated_cost
    if cost is None:
        cost = calculate_cost(payload.model, payload.input_tokens, payload.output_tokens)

    prompt, system_prompt, response = payload.prompt, payload.system_prompt, payload.response
    if get_settings().pii_redaction_enabled:
        prompt = redact_pii(prompt)
        system_prompt = redact_pii(system_prompt) if system_prompt else system_prompt
        response = redact_pii(response)

    trace = Trace(
        trace_id=trace_id,
        request_id=payload.request_id or new_request_id(),
        application_id=payload.application_id,
        environment=payload.environment,
        model=payload.model,
        provider=payload.provider,
        prompt=prompt,
        system_prompt=system_prompt,
        response=response,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        latency_ms=payload.latency_ms,
        estimated_cost=cost,
        retrieved_documents=[d.model_dump() for d in payload.retrieved_documents],
        trace_metadata=payload.metadata,
        status=payload.status,
        error=payload.error,
        prompt_id=payload.prompt_id,
        prompt_version=payload.prompt_version,
        evaluation_status="pending" if (payload.evaluate and payload.status == "ok") else "skipped",
    )
    trace.spans = [
        TraceSpan(
            name=s.name,
            start_ms=s.start_ms,
            duration_ms=s.duration_ms,
            status=s.status,
            span_metadata=s.metadata,
        )
        for s in payload.spans
    ]
    # Ingestion never attaches an evaluation or routing decision inline (those
    # are produced later, by the worker and by /generate respectively).
    # Assigning None explicitly marks the relationship as loaded so Pydantic's
    # from_attributes read below doesn't trigger an async lazy-load.
    trace.evaluation = None
    trace.routing_decision = None
    db.add(trace)
    await db.flush()

    if payload.evaluate and payload.status == "ok":
        try:
            await enqueue_evaluation(trace.id)
        except Exception:
            logger.warning("enqueue_evaluation_failed", trace_id=trace.trace_id)

    return TraceOut.model_validate(trace)


@router.get("", response_model=Page[TraceOut], dependencies=[Depends(RequireRead)])
async def list_traces(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    model: str | None = None,
    provider: str | None = None,
    application_id: str | None = None,
    environment: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
) -> Page[TraceOut]:
    stmt = select(Trace)
    count_stmt = select(func.count()).select_from(Trace)
    for column, value in (
        (Trace.model, model),
        (Trace.provider, provider),
        (Trace.application_id, application_id),
        (Trace.environment, environment),
        (Trace.status, status_filter),
    ):
        if value:
            stmt = stmt.where(column == value)
            count_stmt = count_stmt.where(column == value)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = stmt.options(*_LOAD_OPTS).order_by(Trace.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).unique().scalars().all()
    return Page(
        items=[TraceOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{trace_id}", response_model=TraceOut, dependencies=[Depends(RequireRead)])
async def get_trace(trace_id: str, db: AsyncSession = Depends(get_db)) -> TraceOut:
    stmt = select(Trace).where(Trace.trace_id == trace_id).options(*_LOAD_OPTS)
    row = (await db.execute(stmt)).unique().scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"trace '{trace_id}' not found")
    return TraceOut.model_validate(row)
