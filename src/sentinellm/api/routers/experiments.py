from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, RequireWrite, get_db, scope_of
from sentinellm.api.schemas.common import Page
from sentinellm.api.schemas.experiment import (
    ExperimentComparisonOut,
    ExperimentOut,
    ExperimentRunRequest,
)
from sentinellm.db.models import APIKey, Experiment
from sentinellm.services.experiments import (
    ExperimentInputError,
    compare_experiments,
    run_experiment,
)

router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])


@router.post("/run", response_model=ExperimentOut, status_code=status.HTTP_201_CREATED)
async def run_experiment_endpoint(
    payload: ExperimentRunRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireWrite),
) -> ExperimentOut:
    """Runs `model` + `prompt_id`/`prompt_version` against every record (or
    `sample_size` of them) in `dataset_id` through the real generation and
    evaluation pipelines, and stores the aggregate result. Synchronous —
    see `services/experiments.py` for why.
    """
    scope = scope_of(api_key)
    if scope.ids is not None:
        # The run writes one trace per record into `application_id`, so a
        # scoped key may only target its own — and defaults to it rather than
        # to the shared "experiment-runner" application.
        if "application_id" not in payload.model_fields_set:
            payload = payload.model_copy(update={"application_id": api_key.application_id})
        elif not scope.contains(payload.application_id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "API key is scoped to a different application"
            )
    try:
        experiment = await run_experiment(db, payload)
    except ExperimentInputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return ExperimentOut.model_validate(experiment)


@router.get("/compare", response_model=ExperimentComparisonOut, dependencies=[Depends(RequireRead)])
async def compare_experiments_endpoint(
    a: str, b: str, db: AsyncSession = Depends(get_db)
) -> ExperimentComparisonOut:
    experiment_a = await db.get(Experiment, a)
    experiment_b = await db.get(Experiment, b)
    if experiment_a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"experiment '{a}' not found")
    if experiment_b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"experiment '{b}' not found")

    return ExperimentComparisonOut(
        experiment_a=ExperimentOut.model_validate(experiment_a),
        experiment_b=ExperimentOut.model_validate(experiment_b),
        metrics=compare_experiments(experiment_a, experiment_b),
    )


@router.get("", response_model=Page[ExperimentOut], dependencies=[Depends(RequireRead)])
async def list_experiments(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[ExperimentOut]:
    total = (await db.execute(select(func.count()).select_from(Experiment))).scalar_one()
    stmt = select(Experiment).order_by(Experiment.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return Page(
        items=[ExperimentOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{experiment_id}", response_model=ExperimentOut, dependencies=[Depends(RequireRead)])
async def get_experiment(experiment_id: str, db: AsyncSession = Depends(get_db)) -> ExperimentOut:
    row = await db.get(Experiment, experiment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"experiment '{experiment_id}' not found")
    return ExperimentOut.model_validate(row)
