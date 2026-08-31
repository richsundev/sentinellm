"""Structured JSON logging with request correlation IDs.

Plain-text logs are unsearchable at scale. Every log line is emitted as JSON so
it can be shipped to any log aggregator and filtered by `trace_id`/`request_id`
without regex parsing.
"""

from __future__ import annotations

import contextvars
import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)


def _inject_correlation_ids(
    _logger: object, _method: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    request_id = request_id_var.get()
    trace_id = trace_id_var.get()
    if request_id:
        event_dict["request_id"] = request_id
    if trace_id:
        event_dict["trace_id"] = trace_id
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _inject_correlation_ids,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
