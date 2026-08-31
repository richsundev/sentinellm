"""Mock alert-webhook receiver for local development.

`SENTINEL_ALERT_WEBHOOK_URL` in docker-compose points here by default, so
the alerting pipeline (worker/tasks/alerting.py) has a real HTTP endpoint to
POST to without requiring an external service like Slack/PagerDuty.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from sentinellm.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/_mock_webhook", tags=["internal"])


@router.post("")
async def receive_webhook(payload: dict[str, Any]) -> dict[str, str]:
    logger.info("mock_webhook_received", payload=payload)
    return {"status": "received"}
