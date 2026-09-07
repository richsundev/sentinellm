"""Worker process entrypoint: runs three concurrent async loops —
evaluation job consumption, periodic regression detection, and periodic
alert-rule evaluation — inside a single process. See
docs/design-decisions.md for why this isn't three separate Celery workers.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from sentinellm.core.config import get_settings
from sentinellm.core.logging import configure_logging, get_logger
from sentinellm.core.queue import dequeue_evaluation
from sentinellm.db.session import get_sessionmaker
from sentinellm.services.evaluation_factory import get_evaluation_pipeline
from sentinellm.worker.tasks.alerting import evaluate_alert_rules
from sentinellm.worker.tasks.evaluate import process_evaluation_job
from sentinellm.worker.tasks.model_health import evaluate_model_health
from sentinellm.worker.tasks.regression import detect_regressions

logger = get_logger(__name__)

_REGRESSION_INTERVAL_S = 60
_ALERTING_INTERVAL_S = 60
_MODEL_HEALTH_INTERVAL_S = 60


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
        async with session_factory() as session:
            await process_evaluation_job(session, pipeline, trace_db_id)


async def regression_loop(stop_event: asyncio.Event) -> None:
    session_factory = get_sessionmaker()
    while not stop_event.is_set():
        async with session_factory() as session:
            try:
                await detect_regressions(session)
            except Exception:
                logger.exception("regression_loop_error")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=_REGRESSION_INTERVAL_S)


async def alerting_loop(stop_event: asyncio.Event) -> None:
    session_factory = get_sessionmaker()
    while not stop_event.is_set():
        async with session_factory() as session:
            try:
                await evaluate_alert_rules(session)
            except Exception:
                logger.exception("alerting_loop_error")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=_ALERTING_INTERVAL_S)


async def model_health_loop(stop_event: asyncio.Event) -> None:
    session_factory = get_sessionmaker()
    while not stop_event.is_set():
        async with session_factory() as session:
            try:
                await evaluate_model_health(session)
            except Exception:
                logger.exception("model_health_loop_error")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=_MODEL_HEALTH_INTERVAL_S)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("sentinellm_worker_starting", env=settings.env)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    with contextlib.suppress(NotImplementedError):
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop_event.set)

    await asyncio.gather(
        evaluation_consumer_loop(stop_event),
        regression_loop(stop_event),
        alerting_loop(stop_event),
        model_health_loop(stop_event),
    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
