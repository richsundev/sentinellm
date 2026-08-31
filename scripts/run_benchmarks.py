#!/usr/bin/env python
"""Performance benchmark suite.

Measures, against a real (temporary, file-backed SQLite) database and the
real code paths — nothing here is a synthetic/invented number:

  1. Trace ingestion throughput (raw DB insert cost of a trace + spans)
  2. Evaluation pipeline throughput (deterministic evaluators + hallucination
     detection + judge, using TimingMockProvider so the benchmark measures
     the pipeline's own overhead rather than the mock's simulated network
     latency)
  3. Router decision latency
  4. Semantic cache lookup latency (against a pre-populated cache)
  5. Database query latency (a realistic filtered trace list query)

Run with: python scripts/run_benchmarks.py [--iterations N]

Methodology: each benchmark runs a short warmup (10% of --iterations,
discarded) then times `iterations` sequential runs, reporting throughput
(ops/sec) plus p50/p95/p99 latency in milliseconds. Everything runs
single-process/single-connection — this measures the cost of the code path
itself, not a production deployment's achievable concurrency (see
docs/performance.md for that discussion).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sentinellm.caching.semantic_cache import SemanticCache
from sentinellm.core.ids import new_request_id, new_trace_id
from sentinellm.db.base import Base
from sentinellm.db.models import ModelPricing, Trace, TraceSpan
from sentinellm.embeddings.mock_provider import MockEmbeddingProvider
from sentinellm.evaluation.base import EvaluationContext
from sentinellm.evaluation.pipeline import EvaluationPipeline
from sentinellm.llm.mock_provider import TimingMockProvider
from sentinellm.pricing.catalog import DEFAULT_MODEL_CATALOG
from sentinellm.routing.router import ModelCandidate, Router
from sentinellm.routing.stats import StaticModelStatsProvider

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class BenchmarkResult:
    name: str
    iterations: int
    throughput_per_sec: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(p * len(sorted_values)))
    return round(sorted_values[idx], 4)


def _summarize(name: str, durations_s: list[float]) -> BenchmarkResult:
    ms = sorted(d * 1000 for d in durations_s)
    total_s = sum(durations_s)
    throughput = len(durations_s) / total_s if total_s > 0 else 0.0
    return BenchmarkResult(
        name=name,
        iterations=len(durations_s),
        throughput_per_sec=round(throughput, 2),
        p50_ms=_percentile(ms, 0.50),
        p95_ms=_percentile(ms, 0.95),
        p99_ms=_percentile(ms, 0.99),
    )


async def _time_async(fn, iterations: int, warmup: int) -> list[float]:
    for _ in range(warmup):
        await fn()
    durations = []
    for _ in range(iterations):
        start = time.perf_counter()
        await fn()
        durations.append(time.perf_counter() - start)
    return durations


async def bench_trace_ingestion(
    session: AsyncSession, iterations: int, warmup: int
) -> BenchmarkResult:
    async def _insert() -> None:
        trace = Trace(
            trace_id=new_trace_id(),
            request_id=new_request_id(),
            application_id="bench-app",
            model="mock:sentinel-flash",
            provider="mock",
            prompt="benchmark question",
            response="benchmark response",
            input_tokens=50,
            output_tokens=40,
            latency_ms=100.0,
            estimated_cost=0.0001,
        )
        trace.spans = [TraceSpan(name="llm_generation", start_ms=0, duration_ms=100, status="ok")]
        session.add(trace)
        await session.flush()

    durations = await _time_async(_insert, iterations, warmup)
    await session.commit()
    return _summarize("trace_ingestion (DB insert, trace + 1 span)", durations)


async def bench_evaluation_pipeline(iterations: int, warmup: int) -> BenchmarkResult:
    pipeline = EvaluationPipeline(
        MockEmbeddingProvider(), judge_provider=TimingMockProvider(), run_judge=True
    )
    ctx = EvaluationContext(
        question="What is the refund policy?",
        answer="Refunds are issued within 30 days of purchase, per our standard policy.",
        context="Refunds are issued within 30 days of purchase for all standard plans.",
    )

    async def _evaluate() -> None:
        await pipeline.evaluate(ctx)

    durations = await _time_async(_evaluate, iterations, warmup)
    return _summarize("evaluation_pipeline (7 deterministic + hallucination + judge)", durations)


async def bench_routing_decision(iterations: int, warmup: int) -> BenchmarkResult:
    candidates = [
        ModelCandidate(p.id, p.input_price_per_1k, p.output_price_per_1k, p.context_window)
        for p in DEFAULT_MODEL_CATALOG.values()
        if "judge" not in p.id
    ]
    router = Router(
        candidates,
        StaticModelStatsProvider(),
        quality_weight=0.35,
        cost_weight=0.35,
        latency_weight=0.15,
        risk_weight=0.15,
    )

    async def _route() -> None:
        await router.route("What is your refund policy for annual plans?")

    durations = await _time_async(_route, iterations, warmup)
    return _summarize("router_decision (route() over 4 candidates)", durations)


async def bench_semantic_cache_lookup(
    session: AsyncSession, iterations: int, warmup: int
) -> BenchmarkResult:
    cache = SemanticCache(MockEmbeddingProvider(), similarity_threshold=0.9)
    for i in range(200):
        await cache.store(
            session,
            application_id="bench-app",
            model="mock:sentinel-flash",
            query_text=f"benchmark seed query number {i} about topic {i % 17}",
            response="cached response",
        )
    await session.commit()

    async def _lookup() -> None:
        await cache.lookup(
            session,
            application_id="bench-app",
            model="mock:sentinel-flash",
            query_text="benchmark seed query number 5 about topic 5",
        )

    durations = await _time_async(_lookup, iterations, warmup)
    return _summarize("semantic_cache_lookup (scan of 200 candidate entries)", durations)


async def bench_db_query(session: AsyncSession, iterations: int, warmup: int) -> BenchmarkResult:
    async def _query() -> None:
        stmt = (
            select(Trace)
            .where(Trace.application_id == "bench-app")
            .order_by(Trace.created_at.desc())
            .limit(25)
        )
        (await session.execute(stmt)).scalars().all()

    durations = await _time_async(_query, iterations, warmup)
    return _summarize("db_query (filtered trace list, limit 25)", durations)


async def run(iterations: int, output_path: Path | None) -> None:
    db_path = REPO_ROOT / ".bench.db"
    db_path.unlink(missing_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    warmup = max(1, iterations // 10)
    results: list[BenchmarkResult] = []

    async with session_factory() as session:
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
                )
            )
        await session.commit()

        results.append(await bench_trace_ingestion(session, iterations, warmup))
        results.append(await bench_evaluation_pipeline(iterations, warmup))
        results.append(await bench_routing_decision(iterations, warmup))
        results.append(await bench_semantic_cache_lookup(session, iterations, warmup))
        results.append(await bench_db_query(session, iterations, warmup))

    await engine.dispose()
    db_path.unlink(missing_ok=True)

    header = f"{'benchmark':<55} {'ops/sec':>10} {'p50 ms':>9} {'p95 ms':>9} {'p99 ms':>9}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.name:<55} {r.throughput_per_sec:>10.1f} {r.p50_ms:>9.3f} {r.p95_ms:>9.3f} {r.p99_ms:>9.3f}"
        )

    if output_path:
        output_path.write_text(json.dumps([asdict(r) for r in results], indent=2))
        print(f"\nWrote raw results to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations", type=int, default=200, help="Iterations per benchmark (default: 200)"
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Optional path to write JSON results"
    )
    args = parser.parse_args()
    asyncio.run(run(args.iterations, args.output))


if __name__ == "__main__":
    main()
