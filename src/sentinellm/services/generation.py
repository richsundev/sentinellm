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

import json
import random
import time
from dataclasses import asdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.api.schemas.common import strip_nul
from sentinellm.api.schemas.generate import GenerateRequest
from sentinellm.api.schemas.trace import RetrievedDocumentIn
from sentinellm.caching.semantic_cache import SemanticCache, context_key_for
from sentinellm.core.config import get_settings
from sentinellm.core.ids import new_request_id, new_trace_id
from sentinellm.core.logging import get_logger, trace_id_var
from sentinellm.core.queue import enqueue_evaluation
from sentinellm.db.models import DatasetRecord, ModelPricing, Trace, TraceSpan
from sentinellm.embeddings.base import EmbeddingProvider
from sentinellm.embeddings.factory import get_embedding_provider
from sentinellm.embeddings.similarity import normalized
from sentinellm.llm.base import LLMErrorKind, LLMMessage, LLMRequest
from sentinellm.llm.factory import get_provider_for_model, provider_name_for_model
from sentinellm.llm.resilient import AllModelsFailedError, FallbackAttempt, ResilientLLMClient
from sentinellm.observability.metrics import (
    BUDGET_ENFORCED_TOTAL,
    CACHE_HITS_TOTAL,
    LLM_COST_TOTAL,
    LLM_ERRORS_TOTAL,
    LLM_REQUESTS_TOTAL,
    ROUTING_DECISIONS_TOTAL,
)
from sentinellm.observability.tracing import get_tracer
from sentinellm.pricing.calculator import calculate_cost
from sentinellm.retrieval import corpus_cache
from sentinellm.retrieval.corpus_cache import CorpusIndex
from sentinellm.retrieval.reranker import ScoreJitterReranker
from sentinellm.retrieval.retriever import Document, EmbeddingRetriever
from sentinellm.routing.router import ModelCandidate, NoHealthyCandidateError, Router
from sentinellm.routing.stats import DBModelStatsProvider
from sentinellm.security.pii import redact_documents, redact_pii
from sentinellm.services.budget import BudgetExceededError, enforced_budget
from sentinellm.services.prompt_rollouts import choose_arm, get_latest_prompt_rollout
from sentinellm.services.prompts import render_template, resolve_prompt_version
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


async def _corpus_index(
    session: AsyncSession, dataset_id: str, embeddings: EmbeddingProvider
) -> CorpusIndex:
    """The dataset's documents and their embeddings, built once and reused (see
    `retrieval.corpus_cache`). The record count in the key is one cheap query
    that keeps a dataset which gained records from being served stale."""
    count = (
        await session.execute(
            select(func.count())
            .select_from(DatasetRecord)
            .where(DatasetRecord.dataset_id == dataset_id)
        )
    ).scalar_one()
    key = (dataset_id, embeddings.name, count)
    if (cached := corpus_cache.get(key)) is not None:
        return cached

    rows = (
        (await session.execute(select(DatasetRecord).where(DatasetRecord.dataset_id == dataset_id)))
        .scalars()
        .all()
    )
    documents = tuple(
        Document(doc_id=r.id, content=(r.context or r.expected_answer))
        for r in rows
        if (r.context or r.expected_answer)
    )
    vectors = tuple(
        normalized(v) for v in await embeddings.embed_batch([d.content for d in documents])
    )
    index = CorpusIndex(documents, vectors)
    corpus_cache.put(key, index)
    return index


async def _retrieve_and_rerank(
    session: AsyncSession, dataset_id: str, question: str, top_k: int
) -> tuple[list[RetrievedDocumentIn], float, float]:
    settings = get_settings()
    embeddings = get_embedding_provider(settings.embedding_provider)
    index = await _corpus_index(session, dataset_id, embeddings)
    if not index.documents:
        return [], 0.0, 0.0

    t_retrieval = time.perf_counter()
    retrieved = await EmbeddingRetriever(
        embeddings, index.documents, vectors=index.vectors, unit_vectors=True
    ).retrieve(question, top_k=top_k)
    retrieval_ms = (time.perf_counter() - t_retrieval) * 1000

    t_rerank = time.perf_counter()
    reranked = ScoreJitterReranker().rerank(question, retrieved)
    rerank_ms = (time.perf_counter() - t_rerank) * 1000

    docs = [
        RetrievedDocumentIn(doc_id=r.doc_id, content=r.content, score=r.score, rank=r.rank)
        for r in reranked
    ]
    return docs, retrieval_ms, rerank_ms


def _failed_attempts(
    attempts: list[FallbackAttempt], *, exclude: str
) -> list[dict[str, str | None]]:
    """Calls that failed on the way to (or instead of) an answer — what model
    health needs to see. A context overflow is the request's fault, not the
    model's, so it isn't evidence of ill health."""
    return [
        {"model": a.model, "error_kind": a.error_kind}
        for a in attempts
        if not a.succeeded
        and a.model != exclude
        and a.error_kind != LLMErrorKind.CONTEXT_OVERFLOW.value
    ]


def _blended_price(candidate: ModelCandidate) -> float:
    return (candidate.input_price_per_1k + candidate.output_price_per_1k) / 2


def _system_content(system_prompt: str | None, retrieved: list[RetrievedDocumentIn]) -> str:
    """The system message: instructions and retrieved context together.

    A system prompt used to *replace* the retrieved documents in the prompt, so
    a RAG request that also set one (the usual case) was evaluated for
    faithfulness against documents the model never saw.
    """
    context = "\n".join(d.content for d in retrieved)
    if system_prompt and context:
        return f"{system_prompt}\n\nContext:\n{context}"
    return system_prompt or context


async def generate(session: AsyncSession, request: GenerateRequest) -> Trace:
    with get_tracer(__name__).start_as_current_span("sentinel.generate") as span:
        span.set_attribute("sentinel.application_id", request.application_id)
        trace = await _generate(session, request)
        span.set_attribute("sentinel.model", trace.model)
        span.set_attribute("sentinel.cache_hit", trace.cache_hit)
        span.set_attribute("sentinel.status", trace.status)
        return trace


async def _generate(session: AsyncSession, request: GenerateRequest) -> Trace:
    settings = get_settings()
    # Allocated up front so every log line from retrieval to persistence can be
    # found by the id the caller will get back.
    trace_public_id = new_trace_id()
    trace_id_var.set(trace_public_id)
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

    # Admission: an application that has spent its daily budget and asked for it
    # to be enforced is stopped (or made cheaper) before anything else costs money.
    t_budget = time.perf_counter()
    budget = await enforced_budget(session, request.application_id)
    downgrade = budget is not None and budget.exceeded
    if budget is not None and downgrade and budget.action == "block":
        BUDGET_ENFORCED_TOTAL.labels(action="block").inc()
        raise BudgetExceededError(budget.application_name, budget.budget or 0.0, budget.spent)
    budget_ms = (time.perf_counter() - t_budget) * 1000

    retrieved: list[RetrievedDocumentIn] = list(request.retrieved_documents or [])
    if not retrieved and request.dataset_id:
        t_start = (time.perf_counter() - t0) * 1000
        docs, retrieval_ms, rerank_ms = await _retrieve_and_rerank(
            session, request.dataset_id, request.question, request.top_k
        )
        retrieved = docs
        mark("retrieval", t_start, retrieval_ms, documents_found=len(docs))
        mark("reranking", t_start + retrieval_ms, rerank_ms, documents_reranked=len(docs))

    docs_text = "\n".join(d.content for d in retrieved)
    context_text = docs_text or (request.system_prompt or "")

    served_prompt_version = request.prompt_version
    rendered_prompt: str | None = None
    prompt_rollout = None
    prompt_arm: str | None = None
    if request.prompt_variables is not None and request.prompt_id:
        t_start = (time.perf_counter() - t0) * 1000
        t_render = time.perf_counter()
        requested_version = request.prompt_version
        if requested_version is None:
            # No version pinned: an application-level canary of this prompt, if
            # there is one, decides which version this request is served.
            prompt_rollout = await get_latest_prompt_rollout(
                session, request.application_id, request.prompt_id
            )
            if prompt_rollout is not None:
                requested_version, prompt_arm = choose_arm(prompt_rollout)
        prompt_row = await resolve_prompt_version(session, request.prompt_id, requested_version)
        served_prompt_version = prompt_row.version
        rendered_prompt = render_template(
            prompt_row.template,
            {"question": request.question, "context": docs_text, **request.prompt_variables},
        )
        system_content = (
            f"{request.system_prompt}\n\n{rendered_prompt}"
            if request.system_prompt
            else rendered_prompt
        )
        mark(
            "prompt_render",
            t_start,
            (time.perf_counter() - t_render) * 1000,
            prompt_id=request.prompt_id,
            version=served_prompt_version,
        )
        # What shaped the answer besides the question: the caller's system
        # prompt, *which* template, the caller's own variables, and the
        # documents. (The rendered text itself contains the question, so it
        # can't be the key — every rephrasing would then miss.)
        cache_context_key = context_key_for(
            request.system_prompt,
            f"prompt:{request.prompt_id}@{served_prompt_version}",
            json.dumps(request.prompt_variables, sort_keys=True),
            docs_text,
        )
    else:
        system_content = _system_content(request.system_prompt, retrieved)
        cache_context_key = context_key_for(system_content)

    routing_decision = None
    rollout = None
    rollout_arm: str | None = None
    downgrade_to: str | None = None
    if downgrade and budget is not None:
        candidates = await _load_candidates(session)
        if candidates:
            cheapest = min(candidates, key=_blended_price)
            pinned = next((c for c in candidates if c.model_id == request.preferred_model), None)
            # Never move a request to a *dearer* model: one already pinned to the
            # cheapest (or cheaper than it) stays as it is.
            if pinned is None or _blended_price(cheapest) < _blended_price(pinned):
                downgrade_to = cheapest.model_id
                BUDGET_ENFORCED_TOTAL.labels(action="downgrade").inc()
                mark(
                    "budget_guard",
                    0.0,
                    budget_ms,
                    action="downgrade",
                    budget=budget.budget,
                    spent=round(budget.spent, 6),
                    model=downgrade_to,
                )
    if downgrade_to is None and not request.preferred_model:
        rollout = await get_active_rollout(session, request.application_id)

    if downgrade_to is not None:
        candidate_chain = [downgrade_to]
    elif rollout is not None:
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
            raise NoHealthyCandidateError(
                "no model is available to route to: none are registered, or all are flagged down"
            )
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
    failed_attempts: list[dict[str, str | None]] = []

    cache = SemanticCache(
        get_embedding_provider(settings.embedding_provider),
        settings.cache_similarity_threshold,
        settings.cache_ttl_seconds,
    )
    redact = settings.pii_redaction_enabled
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
            context_key=cache_context_key,
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
        if system_content:
            messages.append(LLMMessage(role="system", content=system_content))
        messages.append(LLMMessage(role="user", content=request.question))
        mark("prompt_construction", t_start, (time.perf_counter() - t_prompt) * 1000)

        t_start = (time.perf_counter() - t0) * 1000
        t_llm = time.perf_counter()
        client = ResilientLLMClient(get_provider_for_model)
        llm_request = LLMRequest(model=selected_model, messages=messages, metadata=request.metadata)
        try:
            resilient_result = await client.complete_with_fallback(llm_request, candidate_chain[1:])
            # Model output isn't validated like a request body, and Postgres
            # cannot store NUL — losing the trace after paying for the call
            # would be the worst outcome, so drop the character instead.
            response_text = strip_nul(resilient_result.response.content)
            input_tokens = resilient_result.response.input_tokens
            output_tokens = resilient_result.response.output_tokens
            selected_model = resilient_result.model_used
            failed_attempts = _failed_attempts(
                resilient_result.attempts_log, exclude=selected_model
            )
            LLM_REQUESTS_TOTAL.labels(
                model=selected_model, provider=provider_name_for_model(selected_model), status="ok"
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
            # The trace itself is the first-choice model's failure; the rest of
            # the chain failed too and is recorded alongside it.
            failed_attempts = _failed_attempts(exc.attempts_log, exclude=selected_model)
            for attempt in exc.attempts_log:
                if attempt.error_kind:
                    LLM_ERRORS_TOTAL.labels(
                        model=attempt.model,
                        provider=provider_name_for_model(attempt.model),
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
                # The entry outlives the request and is served to other callers.
                query_text=redact_pii(request.question) if redact else request.question,
                response=redact_pii(response_text) if redact else response_text,
                context_key=cache_context_key,
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
    if failed_attempts:
        trace_metadata["failed_attempts"] = failed_attempts
    if rendered_prompt is not None and request.prompt_variables is not None:
        # Recorded so the trace shows exactly what the model was given, and so a
        # replay can re-render (possibly with another version).
        trace_metadata["rendered_prompt"] = (
            redact_pii(rendered_prompt) if redact else rendered_prompt
        )
        trace_metadata["prompt_variables"] = (
            {k: redact_pii(v) for k, v in request.prompt_variables.items()}
            if redact
            else dict(request.prompt_variables)
        )
    if rollout is not None:
        trace_metadata["rollout_id"] = rollout.id
        trace_metadata["rollout_arm"] = rollout_arm
    if downgrade_to is not None and budget is not None:
        trace_metadata["budget_downgrade"] = {
            "to": downgrade_to,
            "budget": budget.budget,
            "spent": round(budget.spent, 6),
        }
    if prompt_rollout is not None:
        trace_metadata["prompt_rollout_id"] = prompt_rollout.id
        trace_metadata["prompt_rollout_arm"] = prompt_arm

    trace = Trace(
        trace_id=trace_public_id,
        request_id=new_request_id(),
        application_id=request.application_id,
        environment=request.environment,
        model=selected_model,
        provider=provider_name_for_model(selected_model),
        prompt=redact_pii(request.question) if redact else request.question,
        system_prompt=(
            redact_pii(request.system_prompt)
            if redact and request.system_prompt
            else request.system_prompt
        ),
        response=redact_pii(response_text) if redact else response_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=total_latency_ms,
        estimated_cost=cost,
        retrieved_documents=(
            redact_documents([d.model_dump() for d in retrieved])
            if redact
            else [d.model_dump() for d in retrieved]
        ),
        trace_metadata=trace_metadata,
        status=status,
        error=error,
        cache_hit=cache_hit,
        similarity_score=similarity_score,
        prompt_id=request.prompt_id,
        prompt_version=served_prompt_version,
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
