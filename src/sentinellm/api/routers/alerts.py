from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.deps import RequireRead, RequireWrite, get_db, require_unscoped, scope_of
from sentinellm.api.schemas.alert import AlertOut, AlertRuleOut, AlertRuleUpdate, RegressionOut
from sentinellm.api.schemas.common import Page
from sentinellm.db.models import Alert, AlertRuleConfig, APIKey, Regression
from sentinellm.worker.tasks.alerting import ensure_default_alert_rules

alerts_router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
regressions_router = APIRouter(prefix="/api/v1/regressions", tags=["regressions"])


@alerts_router.get("/rules", response_model=list[AlertRuleOut], dependencies=[Depends(RequireRead)])
async def list_alert_rules(db: AsyncSession = Depends(get_db)) -> list[AlertRuleOut]:
    await ensure_default_alert_rules(db)
    rows = (
        (await db.execute(select(AlertRuleConfig).order_by(AlertRuleConfig.rule))).scalars().all()
    )
    return [AlertRuleOut.model_validate(r) for r in rows]


@alerts_router.patch("/rules/{rule}", response_model=AlertRuleOut)
async def update_alert_rule(
    rule: str,
    payload: AlertRuleUpdate,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireWrite),
) -> AlertRuleOut:
    require_unscoped(api_key)  # thresholds are global: they apply to every tenant
    await ensure_default_alert_rules(db)
    row = (
        await db.execute(select(AlertRuleConfig).where(AlertRuleConfig.rule == rule))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"alert rule '{rule}' not found")
    if payload.threshold is not None:
        row.threshold = payload.threshold
    if payload.enabled is not None:
        row.enabled = payload.enabled
    await db.flush()
    return AlertRuleOut.model_validate(row)


@alerts_router.get("", response_model=Page[AlertOut])
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireRead),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[AlertOut]:
    stmt = select(Alert)
    count_stmt = select(func.count()).select_from(Alert)
    scope = scope_of(api_key)
    if scope.ids is not None:
        # Alerts name what they concern in `affected_service`: `app:<name>` for a
        # cost-budget breach, `rollout:<application>` for an auto-rollback.
        # Platform-wide services ("sentinel-api", ...) aren't any tenant's.
        allowed = {f"app:{i}" for i in scope.ids} | {f"rollout:{i}" for i in scope.ids}
        stmt = stmt.where(Alert.affected_service.in_(allowed))
        count_stmt = count_stmt.where(Alert.affected_service.in_(allowed))

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        (await db.execute(stmt.order_by(Alert.timestamp.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return Page(
        items=[AlertOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


@regressions_router.get("", response_model=Page[RegressionOut])
async def list_regressions(
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(RequireRead),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[RegressionOut]:
    stmt = select(Regression)
    count_stmt = select(func.count()).select_from(Regression)
    scope = scope_of(api_key)
    if scope.ids is not None:
        stmt = stmt.where(Regression.application_id.in_(scope.ids))
        count_stmt = count_stmt.where(Regression.application_id.in_(scope.ids))

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        (await db.execute(stmt.order_by(Regression.detected_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return Page(
        items=[RegressionOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
