"""Orchestrates the full request lifecycle for `POST /api/v1/generate`:

retrieval -> reranking -> routing (or an active canary rollout) -> semantic
cache -> prompt construction -> resilient LLM generation (with fallback) ->
cost calculation -> persistence -> async evaluation enqueue.

This is the one place all the platform's "showcase" subsystems (router,
resilient fallback, semantic cache, rollouts) compose into a single request,
and it is what `scripts/seed_demo.py` calls repeatedly to generate realistic
trace history with genuine routing decisions and genuine cache hits — every
number the dashboard shows comes from this code path actually running,
never from hand-authored fixtures.
"""

from __future__ import annotations

import random
import time
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.schemas.generate import GenerateRequest
from sentinellm.api.schemas.trace import RetrievedDocumentIn
from sentinellm.caching.semantic_cache import SemanticCache
from sentinellm.core.config import get_settings
from sentinellm.core.ids import new_request_id, new_trace_id
from sentinellm.core.logging import get_logger
from sentinellm.core.queue import enqueue_evaluation
from sentinellm.db.models import DatasetRecord, ModelPricing, Trace, TraceSpan
from sentinellm.embeddings.factory import get_embedding_provider
from sentinellm.llm.base import LLMMessage, LLMRequest
from sentinellm.llm.factory import get_provider_for_model
from sentinellm.llm.resilient import AllModelsFailedError, ResilientLLMClient
from sentinellm.observability.metrics import (
    CACHE_HITS_TOTAL,
    LLM_COST_TOTAL,
    LLM_ERRORS_TOTAL,
    LLM_REQUESTS_TOTAL,
    ROUTING_DECISIONS_TOTAL,
)
from sentinellm.pricing.calculator import calculate_cost
from sentinellm.retrieval.reranker import ScoreJitterReranker
from sentinellm.retrieval.retriever import Document, EmbeddingRetriever
from sentinellm.routing.router import ModelCandidate, Router
from sentinellm.routing.stats import DBModelStatsProvider
from sentinellm.services.rollouts import get_active_rollout

logger = get_logger(__name__)


async def _load_candidates(session: AsyncSession) -> list[ModelCandidate]:
    """Judge-only models (id contains "judge") are excluded from generation
    routing — they exist in the pricing catalog purely to be called by the
    LLM-as-judge evaluator, not to serve end-user requests."""
    rows = (
        (await session.execute(select(ModelPricing).where(ModelPricing.status != "down")))
        .scalars()
        .all()
    )
    return [
        ModelCandidate(r.id, r.input_price_per_1k, r.output_price_per_1k, r.context_window)
        for r in rows
        if "judge" not in r.id
    ]


async def _retrieve_and_rerank(
    session: AsyncSession, dataset_id: str, question: str, top_k: int
) -> tuple[list[RetrievedDocumentIn], float, float]:
    rows = (
        (await session.execute(select(DatasetRecord).where(DatasetRecord.dataset_id == dataset_id)))
        .scalars()
        .all()
    )
    corpus = [
        Document(doc_id=r.id, content=(r.context or r.expected_answer))
        for r in rows
        if (r.context or r.expected_answer)
    ]
    if not corpus:
        return [], 0.0, 0.0

    settings = get_settings()
    embeddings = get_embedding_provider(settings.embedding_provider)

    t_retrieval = time.perf_counter()
    retrieved = await EmbeddingRetriever(embeddings, corpus).retrieve(question, top_k=top_k)
    retrieval_ms = (time.perf_counter() - t_retrieval) * 1000

    t_rerank = time.perf_counter()
    reranked = ScoreJitterReranker().rerank(question, retrieved)
    rerank_ms = (time.perf_counter() - t_rerank) * 1000

    docs = [
        RetrievedDocumentIn(doc_id=r.doc_id, content=r.content, score=r.score, rank=r.rank)
        for r in reranked
    ]
    return docs, retrieval_ms, rerank_ms


async def generate(session: AsyncSession, request: GenerateRequest) -> Trace:
    settings = get_settings()
    t0 = time.perf_counter()
    spans: list[TraceSpan] = []

    def mark(
        name: str, start_ms: float, duration_ms: float, status: str = "ok", **meta: object
    ) -> None:
        spans.append(
            TraceSpan(
                name=name,
                start_ms=round(start_ms, 2),
                duration_ms=round(duration_ms, 2),
                status=status,
                span_metadata=meta,
            )
        )

    retrieved: list[RetrievedDocumentIn] = list(request.retrieved_documents or [])
    if not retrieved and request.dataset_id:
        t_start = (time.perf_counter() - t0) * 1000
        docs, retrieval_ms, rerank_ms = await _retrieve_and_rerank(
            session, request.dataset_id, request.question, request.top_k
        )
        retrieved = docs
        mark("retrieval", t_start, retrieval_ms, documents_found=len(docs))
        mark("reranking", t_start + retrieval_ms, rerank_ms, documents_reranked=len(docs))

    context_text = "\n".join(d.content for d in retrieved) or (request.system_prompt or "")

    routing_decision = None
    rollout = None
    rollout_arm: str | None = None
    if not request.preferred_model:
        rollout = await get_active_rollout(session, request.application_id)

    if rollout is not None:
        is_challenger = random.random() < (rollout.traffic_pct / 100.0)
        rollout_arm = "challenger" if is_challenger else "incumbent"
        candidate_chain = [rollout.challenger_model if is_challenger else rollout.incumbent_model]
    elif request.preferred_model:
        candidate_chain = [request.preferred_model, *request.fallback_models]
    else:
        t_start = (time.perf_counter() - t0) * 1000
        t_routing = time.perf_counter()
        candidates = await _load_candidates(session)
        if not candidates:
            raise ValueError("no models registered in the model pricing catalog")
        router = Router(
            candidates,
            DBModelStatsProvider(session),
            quality_weight=settings.router_quality_weight,
            cost_weight=settings.router_cost_weight,
            latency_weight=settings.router_latency_weight,
            risk_weight=settings.router_risk_weight,
        )
        result = await router.route(
            request.question, context_length=len(context_text.split()), metadata=request.metadata
        )
        mark(
            "routing",
            t_start,
            (time.perf_counter() - t_routing) * 1000,
            selected_model=result.selected_model,
        )

        ranked = sorted(
            (c for c in result.candidates if c.excluded_reason is None),
            key=lambda c: -c.routing_score,
        )
        candidate_chain = [c.model for c in ranked] or [candidates[0].model_id]
        routing_decision = {
            "selected_model": result.selected_model,
            "reason": result.reason,
            "candidates": [asdict(c) for c in result.candidates],
            "task_complexity": result.task_complexity.value,
            "risk_level": result.risk_level,
        }
        ROUTING_DECISIONS_TOTAL.labels(
            selected_model=result.selected_model, task_complexity=result.task_complexity.value
        ).inc()

    selected_model = candidate_chain[0]

    cache = SemanticCache(
        get_embedding_provider(settings.embedding_provider), settings.cache_similarity_threshold
    )
    cache_hit = False
    similarity_score: float | None = None
    response_text = ""
    input_tokens = output_tokens = 0
    status = "ok"
    error: str | None = None

    if settings.cache_enabled and request.use_cache:
        t_start = (time.perf_counter() - t0) * 1000
        t_cache = time.perf_counter()
        cache_result = await cache.lookup(
            session,
            application_id=request.application_id,
            model=selected_model,
            query_text=request.question,
        )
        mark(
            "semantic_cache_lookup",
            t_start,
            (time.perf_counter() - t_cache) * 1000,
            hit=cache_result is not None,
        )
        if cache_result is not None:
            cache_hit = True
            similarity_score = cache_result.similarity_score
            response_text = cache_result.response
            CACHE_HITS_TOTAL.labels(result="hit").inc()
        else:
            CACHE_HITS_TOTAL.labels(result="miss").inc()

    if not cache_hit:
        t_start = (time.perf_counter() - t0) * 1000
        t_prompt = time.perf_counter()
        messages: list[LLMMessage] = []
        if request.system_prompt or context_text:
            messages.append(
                LLMMessage(role="system", content=request.system_prompt or context_text)
            )
        messages.append(LLMMessage(role="user", content=request.question))
        mark("prompt_construction", t_start, (time.perf_counter() - t_prompt) * 1000)

        t_start = (time.perf_counter() - t0) * 1000
        t_llm = time.perf_counter()
        client = ResilientLLMClient(get_provider_for_model)
        llm_request = LLMRequest(model=selected_model, messages=messages, metadata=request.metadata)
        try:
            resilient_result = await client.complete_with_fallback(llm_request, candidate_chain[1:])
            response_text = resilient_result.response.content
            input_tokens = resilient_result.response.input_tokens
            output_tokens = resilient_result.response.output_tokens
            selected_model = resilient_result.model_used
            LLM_REQUESTS_TOTAL.labels(
                model=selected_model, provider=selected_model.split(":")[0], status="ok"
            ).inc()
            mark(
                "llm_generation",
                t_start,
                (time.perf_counter() - t_llm) * 1000,
                model=selected_model,
                fallback_used=selected_model != candidate_chain[0],
            )
        except AllModelsFailedError as exc:
            status, error = "error", str(exc)
            for attempt in exc.attempts_log:
                if attempt.error_kind:
                    LLM_ERRORS_TOTAL.labels(
                        model=attempt.model,
                        provider=attempt.model.split(":")[0],
                        kind=attempt.error_kind,
                    ).inc()
            mark(
                "llm_generation",
                t_start,
                (time.perf_counter() - t_llm) * 1000,
                status="error",
                error=error,
            )

        if status == "ok" and settings.cache_enabled and request.use_cache:
            await cache.store(
                session,
                application_id=request.application_id,
                model=selected_model,
                query_text=request.question,
                response=response_text,
            )

    cost = 0.0
    if not cache_hit and status == "ok":
        pricing_row = await session.get(ModelPricing, selected_model)
        cost = calculate_cost(
            selected_model,
            input_tokens,
            output_tokens,
            input_price_per_1k=pricing_row.input_price_per_1k if pricing_row else None,
            output_price_per_1k=pricing_row.output_price_per_1k if pricing_row else None,
        )
        LLM_COST_TOTAL.labels(model=selected_model, application_id=request.application_id).inc(cost)

    total_latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    trace_metadata = dict(request.metadata)
    if rollout is not None:
        trace_metadata["rollout_id"] = rollout.id
        trace_metadata["rollout_arm"] = rollout_arm

    trace = Trace(
        trace_id=new_trace_id(),
        request_id=new_request_id(),
        application_id=request.application_id,
        environment=request.environment,
        model=selected_model,
        provider=selected_model.split(":")[0],
        prompt=request.question,
        system_prompt=request.system_prompt,
        response=response_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=total_latency_ms,
        estimated_cost=cost,
        retrieved_documents=[d.model_dump() for d in retrieved],
        trace_metadata=trace_metadata,
        status=status,
        error=error,
        cache_hit=cache_hit,
        similarity_score=similarity_score,
        prompt_id=request.prompt_id,
        prompt_version=request.prompt_version,
        evaluation_status="pending" if (request.evaluate and status == "ok") else "skipped",
    )
    trace.spans = spans
    # No evaluation or feedback is attached inline — the worker creates the
    # former asynchronously, and a human hasn't reviewed this trace yet.
    # Explicit None (rather than leaving the relationship untouched) avoids an
    # async lazy-load when this object is later read back via TraceOut.
    trace.evaluation = None
    trace.feedback = None

    if routing_decision is not None:
        from sentinellm.db.models import RoutingDecision as RoutingDecisionModel

        trace.routing_decision = RoutingDecisionModel(**routing_decision)
    else:
        trace.routing_decision = None

    session.add(trace)
    await session.flush()

    if request.evaluate and status == "ok":
        try:
            await enqueue_evaluation(trace.id)
        except Exception:
            logger.warning("enqueue_evaluation_failed", trace_id=trace.trace_id)

    return trace
