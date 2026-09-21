"""Worker process entrypoint: runs concurrent async loops — evaluation job
consumption, seven periodic passes (regression detection, alert-rule
evaluation, model-health monitoring, model and prompt canary-rollout
evaluation, lost-job recovery, cache expiry), and a queue-depth sampler for
`/metrics` — all inside a single process. See docs/design-decisions.md for why this isn't a fleet of separate Celery
workers.

Running several replicas is safe: the evaluation consumer is idempotent by
construction, and every periodic pass takes a cluster-wide advisory lock
(`core.locks`) so only one replica applies it at a time.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from prometheus_client import start_http_server
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.config import get_settings
from sentinellm.core.logging import configure_logging, get_logger
from sentinellm.core.queue import dequeue_evaluation, queue_depth
from sentinellm.db.session import get_sessionmaker
from sentinellm.observability.metrics import QUEUE_DEPTH
from sentinellm.observability.tracing import setup_tracing
from sentinellm.services.evaluation_factory import get_evaluation_pipeline
from sentinellm.worker.periodic import run_periodic
from sentinellm.worker.tasks.alerting import evaluate_alert_rules
from sentinellm.worker.tasks.cache_prune import prune_semantic_cache
from sentinellm.worker.tasks.evaluate import process_evaluation_job
from sentinellm.worker.tasks.evaluation_recovery import recover_evaluations
from sentinellm.worker.tasks.model_health import evaluate_model_health
from sentinellm.worker.tasks.prompt_rollout import evaluate_prompt_rollouts
from sentinellm.worker.tasks.regression import detect_regressions
from sentinellm.worker.tasks.rollout import evaluate_rollouts

logger = get_logger(__name__)

_QUEUE_DEPTH_INTERVAL_S = 15


async def evaluation_consumer_loop(stop_event: asyncio.Event) -> None:
    pipeline = get_evaluation_pipeline()
    session_factory = get_sessionmaker()
    logger.info("evaluation_consumer_started")
    while not stop_event.is_set():
        try:
            trace_db_id = await dequeue_evaluation(timeout=5)
        except Exception:
            # A transient Redis blip must not take the whole worker process
            # down — log it, back off briefly, and keep polling.
            logger.exception("evaluation_queue_poll_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=2)
            continue
        if trace_db_id is None:
            continue
        try:
            async with session_factory() as session:
                await process_evaluation_job(session, pipeline, trace_db_id)
        except Exception:
            # Claiming the trace is a database call that can fail (a dropped
            # connection, a deadlock). This loop is one of several under
            # `asyncio.gather`, so an escaping exception would end the whole
            # worker. The job isn't lost: the trace is still `pending`, and
            # `evaluation_recovery` re-queues it.
            logger.exception("evaluation_job_crashed", trace_db_id=trace_db_id)


async def _sample_queue_depth(_session: AsyncSession) -> None:
    QUEUE_DEPTH.set(await queue_depth())


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("sentinellm_worker_starting", env=settings.env)
    setup_tracing("sentinellm-worker", settings.otel_exporter_otlp_endpoint)

    if settings.worker_metrics_port:
        start_http_server(settings.worker_metrics_port)
        logger.info("worker_metrics_serving", port=settings.worker_metrics_port)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError):
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

    interval = settings.worker_interval_seconds
    await asyncio.gather(
        evaluation_consumer_loop(stop_event),
        run_periodic("regression", detect_regressions, interval_s=interval, stop_event=stop_event),
        run_periodic("alerting", evaluate_alert_rules, interval_s=interval, stop_event=stop_event),
        run_periodic(
            "model_health", evaluate_model_health, interval_s=interval, stop_event=stop_event
        ),
        run_periodic("rollout", evaluate_rollouts, interval_s=interval, stop_event=stop_event),
        run_periodic(
            "prompt_rollout", evaluate_prompt_rollouts, interval_s=interval, stop_event=stop_event
        ),
        run_periodic(
            "cache_prune", prune_semantic_cache, interval_s=interval, stop_event=stop_event
        ),
        run_periodic(
            "evaluation_recovery", recover_evaluations, interval_s=interval, stop_event=stop_event
        ),
        # Every replica reports the same shared queue, so this needs no lock.
        run_periodic(
            "queue_depth",
            _sample_queue_depth,
            interval_s=_QUEUE_DEPTH_INTERVAL_S,
            stop_event=stop_event,
            singleton=False,
        ),
    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
