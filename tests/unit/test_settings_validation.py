"""Settings that used to accept values which then failed obscurely (or spun)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinellm.core.config import Settings
from sentinellm.core.logging import configure_logging


@pytest.mark.parametrize("level", ["info", "Debug", "WARNING"])
def test_log_level_is_case_insensitive(level: str) -> None:
    """`SENTINEL_LOG_LEVEL=info` is the natural spelling; it used to crash
    startup inside logging with an unrelated-looking ValueError."""
    settings = Settings(log_level=level)
    assert settings.log_level == level.upper()
    configure_logging(settings.log_level)


def test_an_unknown_log_level_is_rejected_up_front() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="loud")


@pytest.mark.parametrize(
    "bad",
    [
        {"worker_interval_seconds": 0},  # a zero interval is a busy loop hammering the DB
        {"worker_interval_seconds": -5},
        {"rate_limit_per_minute": 0},
        {"cache_similarity_threshold": 1.5},
        {"cache_similarity_threshold": -0.1},
        {"regression_threshold_pct": -1},
        {"max_request_bytes": 0},
    ],
)
def test_nonsensical_numeric_settings_are_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**bad)
