from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, RequireWrite, get_db, require_unscoped
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.prompt import (
    PromptPromoteRequest,
    PromptPromotionOut,
    PromptRenderOut,
    PromptRenderRequest,
    PromptStatusUpdate,
    PromptVersionCreate,
    PromptVersionOut,
)
from sentinellm.db.models import APIKey, PromptVersion
from sentinellm.services.prompts import (
    PromotionGateError,
    PromptNotFoundError,
    promote_prompt_version,
    render_template,
    resolve_prompt_version,
    template_placeholders,
)

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.post("", response_model=PromptVersionOut, status_code=status.HTTP_201_CREATED)
async def create_prompt_version(
    payload: PromptVersionCreate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireWrite),
) -> PromptVersionOut:
    """Creates the next version for `prompt_id` (version numbers are
    monotonically assigned per prompt_id, never reused)."""
    require_unscoped(api_key)
    used = template_placeholders(payload.template)
    undeclared = [name for name in used if payload.variables and name not in payload.variables]
    if undeclared:
        # It could only ever fail later, at serve time, for every caller.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "template uses undeclared variable(s): " + ", ".join(undeclared),
        )
    variables = payload.variables or used
    latest = (
        await db.execute(
            select(func.max(PromptVersion.version)).where(
                PromptVersion.prompt_id == payload.prompt_id
            )
        )
    ).scalar_one()
    next_version = (latest or 0) + 1
    row = PromptVersion(
        prompt_id=payload.prompt_id,
        version=next_version,
        template=payload.template,
        variables=variables,
        status=payload.status,
        author=payload.author,
        prompt_metadata=payload.metadata,
    )
    db.add(row)
    await db.flush()
    return PromptVersionOut.model_validate(row)


@router.get("", response_model=Page[PromptVersionOut], dependencies=[Depends(RequireRead)])
async def list_prompt_versions(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=2_147_483_647),
    prompt_id: str | None = None,
) -> Page[PromptVersionOut]:
    stmt = select(PromptVersion)
    count_stmt = select(func.count()).select_from(PromptVersion)
    if prompt_id:
        stmt = stmt.where(PromptVersion.prompt_id == prompt_id)
        count_stmt = count_stmt.where(PromptVersion.prompt_id == prompt_id)
    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(PromptVersion.prompt_id, PromptVersion.version.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return Page(
        items=[PromptVersionOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{prompt_id}/versions/{version}", response_model=PromptVersionOut)
async def update_prompt_status(
    prompt_id: str,
    version: Annotated[int, Path(ge=1, le=2_147_483_647)],
    payload: PromptStatusUpdate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireWrite),
) -> PromptVersionOut:
    require_unscoped(api_key)
    stmt = select(PromptVersion).where(
        PromptVersion.prompt_id == prompt_id, PromptVersion.version == version
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"prompt '{prompt_id}' v{version} not found")
    row.status = payload.status
    await db.flush()
    return PromptVersionOut.model_validate(row)


@router.post(
    "/{prompt_id}/versions/{version}/render",
    response_model=PromptRenderOut,
    dependencies=[Depends(RequireRead)],
)
async def render_prompt_version(
    prompt_id: str,
    version: Annotated[int, Path(ge=1, le=2_147_483_647)],
    payload: PromptRenderRequest,
    db: AsyncSession = Depends(get_db),
) -> PromptRenderOut:
    """Preview a version's template with the given variables. No model is
    called and nothing is stored, so it's safe for an editor UI to call on
    every keystroke. Unlike `/generate`, `question` and `context` are not
    filled in for you."""
    row = await resolve_prompt_version(db, prompt_id, version)
    missing = [n for n in template_placeholders(row.template) if n not in payload.variables]
    rendered = None if missing else render_template(row.template, payload.variables)
    return PromptRenderOut(
        prompt_id=prompt_id, version=row.version, rendered=rendered, missing=missing
    )


@router.post("/{prompt_id}/versions/{version}/promote", response_model=PromptPromotionOut)
async def promote_prompt_version_endpoint(
    prompt_id: str,
    version: Annotated[int, Path(ge=1, le=2_147_483_647)],
    payload: PromptPromoteRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireWrite),
) -> PromptPromotionOut:
    """Evidence-gated promotion: requires the latest experiment run for this
    exact prompt version to have `pass_rate >= quality_pass_threshold`, and
    demotes whatever was previously `production` for this `prompt_id`. See
    `services/prompts.py` for the full rationale.
    """
    require_unscoped(api_key)
    try:
        result = await promote_prompt_version(
            db, prompt_id, version, payload.quality_pass_threshold
        )
    except PromptNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PromotionGateError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return PromptPromotionOut(
        promoted=PromptVersionOut.model_validate(result.promoted),
        justifying_experiment_id=result.justifying_experiment.id,
        justifying_experiment_pass_rate=result.justifying_experiment.pass_rate,
        demoted_version=result.demoted_version,
    )
