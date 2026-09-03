from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import ColumnElement, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinellm.api.deps import RequireRead, RequireWrite, get_db
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.trace import (
    TraceCreate,
    TraceFeedbackIn,
    TraceFeedbackOut,
    TraceOut,
    TraceTagsIn,
    TraceTagsOut,
)
from sentinellm.core.config import get_settings
from sentinellm.core.ids import new_request_id, new_trace_id
from sentinellm.core.logging import get_logger
from sentinellm.core.queue import enqueue_evaluation
from sentinellm.db.models import Evaluation, Trace, TraceFeedback, TraceSpan
from sentinellm.pricing.calculator import calculate_cost
from sentinellm.security.pii import redact_pii

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/traces", tags=["traces"])

_LOAD_OPTS = (
    selectinload(Trace.spans),
    selectinload(Trace.evaluation).selectinload(Evaluation.metrics),
    selectinload(Trace.evaluation).selectinload(Evaluation.claims),
    selectinload(Trace.routing_decision),
    selectinload(Trace.feedback),
)
_EXPORT_ROW_CAP = 5000
_EXPORT_COLUMNS = [
    "trace_id",
    "created_at",
    "application_id",
    "environment",
    "model",
    "provider",
    "status",
    "latency_ms",
    "estimated_cost",
    "input_tokens",
    "output_tokens",
    "cache_hit",
    "tags",
    "overall_quality",
    "feedback_rating",
    "prompt",
    "response",
]


def _trace_filter_clauses(
    *,
    model: str | None,
    provider: str | None,
    application_id: str | None,
    environment: str | None,
    status_filter: str | None,
    q: str | None,
    tag: str | None,
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = []
    for column, value in (
        (Trace.model, model),
        (Trace.provider, provider),
        (Trace.application_id, application_id),
        (Trace.environment, environment),
        (Trace.status, status_filter),
    ):
        if value:
            clauses.append(column == value)
    if q:
        clauses.append(or_(Trace.prompt.ilike(f"%{q}%"), Trace.response.ilike(f"%{q}%")))
    if tag:
        # Generic JSON column has no portable containment operator across
        # SQLite (tests) and Postgres (prod), so match the quoted tag
        # substring in the column's text representation instead.
        clauses.append(cast(Trace.tags, String).ilike(f'%"{tag.strip().lower()}"%'))
    return clauses


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
    # Ingestion never attaches an evaluation, routing decision, or feedback
    # inline (those are produced later, by the worker, /generate, and a
    # reviewer respectively). Assigning None explicitly marks each
    # relationship as loaded so Pydantic's from_attributes read below
    # doesn't trigger an async lazy-load.
    trace.evaluation = None
    trace.routing_decision = None
    trace.feedback = None
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
    q: str | None = Query(
        default=None, description="Case-insensitive substring match over prompt + response"
    ),
    tag: str | None = None,
) -> Page[TraceOut]:
    clauses = _trace_filter_clauses(
        model=model,
        provider=provider,
        application_id=application_id,
        environment=environment,
        status_filter=status_filter,
        q=q,
        tag=tag,
    )
    total = (await db.execute(select(func.count()).select_from(Trace).where(*clauses))).scalar_one()
    stmt = (
        select(Trace)
        .where(*clauses)
        .options(*_LOAD_OPTS)
        .order_by(Trace.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).unique().scalars().all()
    return Page(
        items=[TraceOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@router.get("/export", dependencies=[Depends(RequireRead)])
async def export_traces(
    db: AsyncSession = Depends(get_db),
    model: str | None = None,
    provider: str | None = None,
    application_id: str | None = None,
    environment: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    tag: str | None = None,
) -> StreamingResponse:
    """Streams a CSV of traces matching the given filters (same filter set
    as `list_traces`, minus pagination), capped at `_EXPORT_ROW_CAP` rows.
    Must be declared before `GET /{trace_id}` so "export" isn't swallowed
    as a `trace_id` path parameter.
    """
    clauses = _trace_filter_clauses(
        model=model,
        provider=provider,
        application_id=application_id,
        environment=environment,
        status_filter=status_filter,
        q=q,
        tag=tag,
    )
    stmt = (
        select(Trace)
        .where(*clauses)
        .options(selectinload(Trace.evaluation), selectinload(Trace.feedback))
        .order_by(Trace.created_at.desc())
        .limit(_EXPORT_ROW_CAP)
    )
    rows = (await db.execute(stmt)).unique().scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_COLUMNS)
    for t in rows:
        writer.writerow(
            [
                t.trace_id,
                t.created_at.isoformat(),
                t.application_id,
                t.environment,
                t.model,
                t.provider,
                t.status,
                t.latency_ms,
                t.estimated_cost,
                t.input_tokens,
                t.output_tokens,
                t.cache_hit,
                ";".join(t.tags),
                t.evaluation.overall_quality if t.evaluation else "",
                t.feedback.rating if t.feedback else "",
                t.prompt,
                t.response,
            ]
        )

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="traces.csv"'},
    )


@router.get("/{trace_id}", response_model=TraceOut, dependencies=[Depends(RequireRead)])
async def get_trace(trace_id: str, db: AsyncSession = Depends(get_db)) -> TraceOut:
    stmt = select(Trace).where(Trace.trace_id == trace_id).options(*_LOAD_OPTS)
    row = (await db.execute(stmt)).unique().scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"trace '{trace_id}' not found")
    return TraceOut.model_validate(row)


@router.post(
    "/{trace_id}/feedback",
    response_model=TraceFeedbackOut,
    dependencies=[Depends(RequireWrite)],
)
async def submit_trace_feedback(
    trace_id: str, payload: TraceFeedbackIn, db: AsyncSession = Depends(get_db)
) -> TraceFeedbackOut:
    """Upserts a human reviewer's verdict on a trace — one row per trace,
    not a history, so re-submitting overwrites the previous rating/note
    rather than appending another entry (see `TraceFeedback` docstring).
    """
    trace_stmt = (
        select(Trace).where(Trace.trace_id == trace_id).options(selectinload(Trace.feedback))
    )
    trace = (await db.execute(trace_stmt)).unique().scalar_one_or_none()
    if trace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"trace '{trace_id}' not found")

    if trace.feedback is not None:
        trace.feedback.rating = payload.rating
        trace.feedback.note = payload.note
    else:
        trace.feedback = TraceFeedback(rating=payload.rating, note=payload.note)

    await db.flush()
    return TraceFeedbackOut.model_validate(trace.feedback)


@router.patch(
    "/{trace_id}/tags",
    response_model=TraceTagsOut,
    dependencies=[Depends(RequireWrite)],
)
async def update_trace_tags(
    trace_id: str, payload: TraceTagsIn, db: AsyncSession = Depends(get_db)
) -> TraceTagsOut:
    """Replaces the full tag set on a trace (not a merge/append)."""
    trace = (await db.execute(select(Trace).where(Trace.trace_id == trace_id))).scalar_one_or_none()
    if trace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"trace '{trace_id}' not found")

    # Normalized so filtering (`?tag=`) and display are consistent
    # regardless of how a reviewer capitalized or spaced the tag.
    trace.tags = sorted({t.strip().lower() for t in payload.tags if t.strip()})
    await db.flush()
    return TraceTagsOut(trace_id=trace.trace_id, tags=trace.tags)
