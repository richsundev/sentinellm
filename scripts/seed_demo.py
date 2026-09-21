#!/usr/bin/env python
"""Seeds a fully-populated local demo environment for SentinelLLM.

Run with:  python scripts/seed_demo.py   (or `make seed`)

Everything this script writes is produced by actually exercising the
platform's real code paths — the router, the resilient LLM client, the
semantic cache, and the evaluation pipeline all run for real against the
MockProvider. Nothing here is a hand-authored fixture number.

What gets seeded:
  1. The model pricing catalog (from `sentinellm.pricing.catalog`).
  2. A demo application + the well-known demo API key (matches
     `SENTINEL_DEMO_API_KEY` / the frontend's default `NEXT_PUBLIC_API_KEY`).
  3. A benchmark dataset loaded from datasets/support_bench_v1.jsonl.
  4. Two versions of a "support-answer" prompt.
  5. A "routing showcase" batch: simple/medium/complex/high-risk questions
     run through the real router (+ a repeated question to trigger a real
     semantic-cache hit).
  6. A "regression showcase": an earlier batch of traces on a strong model
     (prompt v1) followed by a later batch on a weaker, higher-hallucination
     model (prompt v2) — the weaker model's own simulated behavior is what
     produces the faithfulness drop; the regression detector then finds it
     for real.
  7. Evaluations for every trace (run inline — no worker process needed to
     see a populated dashboard immediately after seeding).
  8. One regression-detection pass and one alert-rule pass.
  9. Two Experiment rows summarizing the two regression-showcase eras with
     real aggregate metrics.
 10. A second application ("checkout-assistant") with a canary rollout
     already in flight — a cheaper challenger model against the incumbent —
     whose traffic was really split by `/generate`'s rollout logic and
     evaluated inline. The worker picks it up and advances (or rolls back)
     the rollout on its own once the evidence is past its grace period.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinellm.api.schemas.generate import GenerateRequest
from sentinellm.api.schemas.rollout import RolloutCreate
from sentinellm.api.security import generate_api_key, hash_api_key, key_display_prefix
from sentinellm.core.config import get_settings
from sentinellm.core.git import get_git_commit
from sentinellm.db.models import (
    APIKey,
    Application,
    Dataset,
    DatasetRecord,
    Evaluation,
    Experiment,
    ModelPricing,
    PromptVersion,
    Trace,
)
from sentinellm.db.session import get_sessionmaker, init_models
from sentinellm.pricing.catalog import DEFAULT_MODEL_CATALOG
from sentinellm.services.evaluation_factory import get_evaluation_pipeline
from sentinellm.services.generation import generate as run_generate
from sentinellm.services.rollouts import create_rollout
from sentinellm.worker.tasks.alerting import evaluate_alert_rules
from sentinellm.worker.tasks.regression import detect_regressions_for_application

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "datasets" / "support_bench_v1.jsonl"
APPLICATION_NAME = "support-bot"
CHECKOUT_APPLICATION_NAME = "checkout-assistant"

_COMPLEX_QUESTIONS = [
    "Analyze the trade-offs between our current caching architecture and a distributed "
    "approach, explain the root cause of the latency regression from last week, and design "
    "a step by step migration plan that accounts for backward compatibility.",
    "Compare our SSO implementation against a hypothetical SCIM-based provisioning "
    "architecture, explain the root cause of the sync delays reported by enterprise "
    "customers, and design a step by step remediation plan.",
]
_HIGH_RISK_QUESTIONS = [
    "What is the correct prescription dosage adjustment for a customer with a documented "
    "medical condition who is asking about our health-tracking integration?",
    "We received a legal notice about a data breach affecting EU customers — what is the "
    "required incident disclosure timeline under GDPR?",
]


def _load_dataset_records() -> list[dict]:
    with DATASET_PATH.open() as f:
        return [json.loads(line) for line in f if line.strip()]


async def _already_seeded(session: AsyncSession) -> bool:
    result = await session.execute(select(Application).where(Application.name == APPLICATION_NAME))
    return result.scalar_one_or_none() is not None


async def _seed_models(session: AsyncSession) -> None:
    for profile in DEFAULT_MODEL_CATALOG.values():
        session.add(
            ModelPricing(
                id=profile.id,
                name=profile.name,
                provider=profile.provider,
                input_price_per_1k=profile.input_price_per_1k,
                output_price_per_1k=profile.output_price_per_1k,
                context_window=profile.context_window,
                quality_tier=profile.quality_tier,
                avg_latency_ms_prior=profile.avg_latency_ms_prior,
                status="healthy",
            )
        )
    await session.flush()
    print(f"  seeded {len(DEFAULT_MODEL_CATALOG)} models into the pricing catalog")


async def _seed_application_and_key(session: AsyncSession) -> Application:
    settings = get_settings()
    app_row = Application(
        name=APPLICATION_NAME, description="Fictional AI customer support assistant (demo data)"
    )
    session.add(app_row)
    await session.flush()

    demo_key = settings.demo_api_key
    session.add(
        APIKey(
            application_id=app_row.id,
            name="demo-key",
            role="admin",
            key_hash=hash_api_key(demo_key),
            key_prefix=key_display_prefix(demo_key),
        )
    )
    # A second, freshly-generated key to demonstrate real key issuance too.
    extra_key = generate_api_key()
    session.add(
        APIKey(
            application_id=app_row.id,
            name="ci-pipeline",
            role="write",
            key_hash=hash_api_key(extra_key),
            key_prefix=key_display_prefix(extra_key),
        )
    )
    await session.flush()
    print(f"  seeded application '{APPLICATION_NAME}' + demo API key ({settings.demo_api_key})")
    return app_row


async def _seed_dataset(session: AsyncSession) -> Dataset:
    records = _load_dataset_records()
    dataset = Dataset(
        name="support-bench", version="v1", description="Realistic customer-support Q&A benchmark"
    )
    dataset.records = [
        DatasetRecord(
            question=r["question"],
            context=r["context"],
            expected_answer=r["expected_answer"],
            record_metadata=r.get("metadata", {}),
        )
        for r in records
    ]
    session.add(dataset)
    await session.flush()
    print(f"  seeded dataset 'support-bench v1' with {len(records)} records")
    return dataset


async def _seed_prompts(session: AsyncSession) -> tuple[PromptVersion, PromptVersion]:
    v1 = PromptVersion(
        prompt_id="support-answer",
        version=1,
        status="production",
        author="platform-team",
        template="You are a precise support assistant. Answer strictly using the provided context. "
        "Context:\n{{context}}\n\nQuestion: {{question}}",
        variables=["context", "question"],
    )
    v2 = PromptVersion(
        prompt_id="support-answer",
        version=2,
        status="production",
        author="growth-team",
        template="You are a friendly, concise support assistant. Question: {{question}} "
        "(context available: {{context}})",
        variables=["context", "question"],
        prompt_metadata={"note": "shortened for latency; rolled out to cut cost per request"},
    )
    session.add_all([v1, v2])
    await session.flush()
    print("  seeded prompt 'support-answer' v1 (production) and v2 (rolled out over v1)")
    return v1, v2


async def _evaluate_all(session: AsyncSession, traces: list[Trace]) -> None:
    # Every GenerateRequest below passes evaluate=False so `generate()` never
    # enqueues a redundant worker job for a trace this function is about to
    # evaluate inline anyway (the worker would otherwise just log a no-op
    # "already completed" skip for each one — harmless, but noisy and wasteful).
    pipeline = get_evaluation_pipeline()
    for trace in traces:
        await pipeline.run_and_persist(session, trace)
        trace.evaluation_status = "completed"
    await session.flush()


async def _run_routing_showcase(
    session: AsyncSession, app_id: str, dataset_id: str, records: list[dict]
) -> list[Trace]:
    traces: list[Trace] = []
    simple_questions = [r["question"] for r in records[:5]]
    for q in simple_questions:
        req = GenerateRequest(
            application_id=app_id,
            question=q,
            dataset_id=dataset_id,
            prompt_id="support-answer",
            prompt_version=1,
            evaluate=False,
        )
        traces.append(await run_generate(session, req))

    for q in _COMPLEX_QUESTIONS:
        req = GenerateRequest(
            application_id=app_id,
            question=q,
            dataset_id=dataset_id,
            prompt_id="support-answer",
            prompt_version=1,
            evaluate=False,
        )
        traces.append(await run_generate(session, req))

    for q in _HIGH_RISK_QUESTIONS:
        req = GenerateRequest(
            application_id=app_id,
            question=q,
            dataset_id=dataset_id,
            prompt_id="support-answer",
            prompt_version=1,
            evaluate=False,
        )
        traces.append(await run_generate(session, req))

    # Repeat one question twice to demonstrate a real semantic cache hit.
    cache_demo_question = records[0]["question"]
    for _ in range(2):
        req = GenerateRequest(
            application_id=app_id,
            question=cache_demo_question,
            preferred_model="mock:sentinel-flash",
            use_cache=True,
            dataset_id=dataset_id,
            prompt_id="support-answer",
            prompt_version=1,
            evaluate=False,
        )
        traces.append(await run_generate(session, req))

    await session.flush()
    print(
        f"  routing showcase: generated {len(traces)} traces (real router decisions + a real cache hit)"
    )
    return traces


async def _run_regression_showcase(
    session: AsyncSession, app_id: str, dataset_id: str, records: list[dict]
) -> tuple[list[Trace], list[Trace]]:
    era1: list[Trace] = []
    for i in range(30):
        record = records[i % len(records)]
        req = GenerateRequest(
            application_id=app_id,
            question=record["question"],
            preferred_model="mock:sentinel-pro",
            use_cache=False,
            dataset_id=dataset_id,
            prompt_id="support-answer",
            prompt_version=1,
            evaluate=False,
        )
        era1.append(await run_generate(session, req))
    await session.flush()

    era2: list[Trace] = []
    for i in range(30):
        record = records[i % len(records)]
        req = GenerateRequest(
            application_id=app_id,
            question=record["question"],
            preferred_model="mock:sentinel-nano",
            use_cache=False,
            dataset_id=dataset_id,
            prompt_id="support-answer",
            prompt_version=2,
            evaluate=False,
        )
        era2.append(await run_generate(session, req))
    await session.flush()

    print(
        f"  regression showcase: era 1 (prompt v1, sentinel-pro) = {len(era1)} traces, "
        f"era 2 (prompt v2, sentinel-nano) = {len(era2)} traces"
    )
    return era1, era2


async def _seed_experiments(
    session: AsyncSession, dataset_id: str, era1: list[Trace], era2: list[Trace]
) -> None:
    git_commit = get_git_commit()
    for name, model, prompt_version, traces in (
        ("support-answer v1 on sentinel-pro", "mock:sentinel-pro", 1, era1),
        ("support-answer v2 on sentinel-nano", "mock:sentinel-nano", 2, era2),
    ):
        trace_ids = [t.id for t in traces]
        evaluations = (
            (
                await session.execute(
                    select(Evaluation)
                    .where(Evaluation.trace_id.in_(trace_ids))
                    .options(selectinload(Evaluation.metrics))
                )
            )
            .scalars()
            .all()
        )
        if not evaluations:
            continue
        faithfulness_scores = []
        relevance_scores = []
        for e in evaluations:
            for m in e.metrics:
                if m.metric_name == "faithfulness":
                    faithfulness_scores.append(m.score)
                elif m.metric_name == "relevance":
                    relevance_scores.append(m.score)

        latencies = sorted(t.latency_ms for t in traces)
        p95_latency = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]
        costs = [t.estimated_cost for t in traces]
        hallucination_scores = [e.hallucination_score for e in evaluations]
        pass_count = sum(1 for e in evaluations if e.overall_quality >= 0.7)

        session.add(
            Experiment(
                name=name,
                model=model,
                prompt_id="support-answer",
                prompt_version=prompt_version,
                dataset_id=dataset_id,
                faithfulness=round(sum(faithfulness_scores) / len(faithfulness_scores), 4)
                if faithfulness_scores
                else 0.0,
                relevance=round(sum(relevance_scores) / len(relevance_scores), 4)
                if relevance_scores
                else 0.0,
                hallucination_rate=round(sum(hallucination_scores) / len(hallucination_scores), 4),
                p95_latency_ms=round(p95_latency, 2),
                cost_per_request=round(sum(costs) / len(costs), 6),
                pass_rate=round(pass_count / len(evaluations), 4),
                git_commit=git_commit,
                parameters={"dataset": "support-bench v1", "sample_size": len(traces)},
            )
        )
    await session.flush()
    print("  seeded 2 experiments comparing the regression-showcase eras")


async def _seed_rollout_showcase(
    session: AsyncSession, dataset_id: str, records: list[dict]
) -> list[Trace]:
    """A canary in flight: swap the expensive incumbent for a cheaper
    challenger on an application whose requests don't pin a model. The
    traffic below goes through the real `/generate` path, so which arm each
    request landed on is the rollout's own probabilistic split, not a
    fixture.
    """
    app_row = Application(
        name=CHECKOUT_APPLICATION_NAME,
        description="Fictional checkout help assistant — canary rollout demo (demo data)",
    )
    session.add(app_row)
    await session.flush()

    rollout = await create_rollout(
        session,
        RolloutCreate(
            application_id=app_row.id,
            incumbent_model="mock:sentinel-pro",
            challenger_model="mock:sentinel-flash",
            initial_pct=30,
            step_pct=20,
            min_sample_size=8,
            # The mock models' quality sits well below the production
            # defaults (0.7), so the demo gates are set relative to what
            # they actually score.
            quality_floor=0.3,
            max_quality_regression=0.25,
        ),
    )

    traces: list[Trace] = []
    for i in range(48):
        req = GenerateRequest(
            application_id=app_row.id,
            question=records[i % len(records)]["question"],
            dataset_id=dataset_id,
            use_cache=False,
            evaluate=False,
        )
        traces.append(await run_generate(session, req))
    await session.flush()

    on_challenger = sum(1 for t in traces if t.model == rollout.challenger_model)
    print(
        f"  rollout showcase: '{CHECKOUT_APPLICATION_NAME}' canary "
        f"{rollout.incumbent_model} -> {rollout.challenger_model} at {rollout.traffic_pct:.0f}%: "
        f"{on_challenger}/{len(traces)} requests landed on the challenger"
    )
    return traces


async def seed(force: bool = False) -> None:
    await init_models()
    session_factory = get_sessionmaker()

    async with session_factory() as session:
        if not force and await _already_seeded(session):
            print(
                "Demo data already present (application 'support-bot' exists). Use --force to reseed."
            )
            return

        print("Seeding SentinelLLM demo data...")
        await _seed_models(session)
        app_row = await _seed_application_and_key(session)
        dataset = await _seed_dataset(session)
        await _seed_prompts(session)
        await session.commit()

        records = _load_dataset_records()
        routing_traces = await _run_routing_showcase(session, app_row.id, dataset.id, records)
        await _evaluate_all(session, routing_traces)
        await session.commit()

        era1, era2 = await _run_regression_showcase(session, app_row.id, dataset.id, records)
        await _evaluate_all(session, era1 + era2)
        await session.commit()

        print("  running regression detection...")
        regressions = await detect_regressions_for_application(session, app_row.id)
        for r in regressions:
            print(
                f"    REGRESSION DETECTED: {r.metric_name} {r.previous_value} -> {r.new_value} "
                f"({r.delta_pct:+.1f}%, {r.severity}) — {r.likely_cause}"
            )

        print("  running alert rule evaluation...")
        alerts = await evaluate_alert_rules(session)
        for a in alerts:
            print(
                f"    ALERT: {a.rule} = {a.current_value:.4f} (threshold {a.threshold}, {a.severity})"
            )

        await _seed_experiments(session, dataset.id, era1, era2)
        await session.commit()

        rollout_traces = await _seed_rollout_showcase(session, dataset.id, records)
        await _evaluate_all(session, rollout_traces)
        await session.commit()

        total_traces = len(routing_traces) + len(era1) + len(era2) + len(rollout_traces)
        print(
            f"\nDone. Seeded {total_traces} traces with real evaluations, "
            f"{len(regressions)} regression(s), and {len(alerts)} alert(s)."
        )
        print(f"Demo API key: {get_settings().demo_api_key}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Reseed even if demo data already exists"
    )
    args = parser.parse_args()
    asyncio.run(seed(force=args.force))


if __name__ == "__main__":
    main()
