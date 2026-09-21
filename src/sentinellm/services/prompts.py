"""Prompt version promotion: a guardrail on top of the plain `status` field.

Setting `status="production"` directly (`PATCH /prompts/{id}/versions/{v}`)
is still allowed — it's how the demo seed data gets there without running a
real experiment first. `promote_prompt_version` is the *evidence-gated*
path: it requires a passing experiment result for this exact prompt version
before flipping its status, and demotes whatever was previously production
for the same `prompt_id` (only one production version at a time). This is
what turns the prompt registry and the experiment runner — two features
that otherwise don't know about each other — into an actual promotion
workflow.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.db.models import Experiment, PromptVersion


class PromptNotFoundError(ValueError):
    pass


class PromptRenderError(ValueError):
    """A template can't be rendered from the variables supplied — the caller's
    to fix, so it surfaces as a 422, not a 500."""


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def template_placeholders(template: str) -> list[str]:
    """The `{{name}}` placeholders in a template, in first-appearance order."""
    return list(dict.fromkeys(_PLACEHOLDER_RE.findall(template)))


def render_template(template: str, values: Mapping[str, str], *, strict: bool = True) -> str:
    """Substitutes `{{name}}` placeholders.

    One pass over the *template*: substituting variable-by-variable would
    re-scan text already inserted, so a document containing `{{question}}`
    would be expanded into the question (and a caller could smuggle a
    placeholder into another variable's value).

    `strict` raises `PromptRenderError` naming every placeholder with no value;
    otherwise an unknown placeholder is left as written.
    """
    if strict:
        missing = [name for name in template_placeholders(template) if name not in values]
        if missing:
            raise PromptRenderError(
                "missing value(s) for template variable(s): " + ", ".join(missing)
            )
    return _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), template)


async def resolve_prompt_version(
    session: AsyncSession, prompt_id: str, version: int | None = None
) -> PromptVersion:
    """The version to serve: `version` if given, else the newest version whose
    status is `production`."""
    stmt = select(PromptVersion).where(PromptVersion.prompt_id == prompt_id)
    if version is not None:
        row = (
            await session.execute(stmt.where(PromptVersion.version == version))
        ).scalar_one_or_none()
        if row is None:
            raise PromptNotFoundError(f"prompt '{prompt_id}' v{version} not found")
        return row
    row = (
        await session.execute(
            stmt.where(PromptVersion.status == "production")
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise PromptNotFoundError(
            f"prompt '{prompt_id}' has no production version — promote one, or pass prompt_version"
        )
    return row


class PromotionGateError(ValueError):
    """Raised when there's no evidence, or the evidence doesn't clear the
    bar — the router translates this to 400, not 500."""


class PromptPromotionResult:
    __slots__ = ("demoted_version", "justifying_experiment", "promoted")

    def __init__(
        self,
        promoted: PromptVersion,
        justifying_experiment: Experiment,
        demoted_version: int | None,
    ) -> None:
        self.promoted = promoted
        self.justifying_experiment = justifying_experiment
        self.demoted_version = demoted_version


async def promote_prompt_version(
    session: AsyncSession, prompt_id: str, version: int, quality_pass_threshold: float
) -> PromptPromotionResult:
    target = (
        await session.execute(
            select(PromptVersion).where(
                PromptVersion.prompt_id == prompt_id, PromptVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise PromptNotFoundError(f"prompt '{prompt_id}' v{version} not found")

    latest_experiment = (
        await session.execute(
            select(Experiment)
            .where(Experiment.prompt_id == prompt_id, Experiment.prompt_version == version)
            .order_by(Experiment.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_experiment is None:
        raise PromotionGateError(
            f"no experiment found for '{prompt_id}' v{version} — run POST /api/v1/experiments/run "
            "against this prompt version before promoting it"
        )
    if latest_experiment.pass_rate < quality_pass_threshold:
        raise PromotionGateError(
            f"latest experiment '{latest_experiment.name}' has pass_rate="
            f"{latest_experiment.pass_rate:.2f}, below the {quality_pass_threshold:.2f} promotion threshold"
        )

    demoted_version: int | None = None
    current_production = (
        (
            await session.execute(
                select(PromptVersion).where(
                    PromptVersion.prompt_id == prompt_id,
                    PromptVersion.status == "production",
                    PromptVersion.version != version,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in current_production:
        row.status = "deprecated"
        demoted_version = row.version

    target.status = "production"
    await session.flush()
    return PromptPromotionResult(target, latest_experiment, demoted_version)
