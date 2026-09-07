import json
from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from sentinellm.core.config import Settings
from sentinellm.core.ids import new_trace_id
from sentinellm.db.models import Trace
from sentinellm.worker.tasks import alerting
from sentinellm.worker.tasks.alerting import _slack_payload, evaluate_alert_rules


def test_slack_payload_is_a_plain_text_message() -> None:
    payload = _slack_payload("error_rate", 0.42, 0.05, "high", "sentinel-api", None)
    assert list(payload.keys()) == ["text"]
    text = payload["text"]
    assert isinstance(text, str)
    assert "error_rate" in text
    assert "0.42" in text
    assert "0.05" in text
    assert "sentinel-api" in text


def test_slack_payload_includes_model_when_present() -> None:
    payload = _slack_payload("quality_score", 0.5, 0.85, "high", "sentinel-evaluator", "mock:x")
    assert "mock:x" in payload["text"]


async def _make_error_traces(db_session: AsyncSession, count: int) -> None:
    for _ in range(count):
        db_session.add(
            Trace(
                trace_id=new_trace_id(),
                request_id="req",
                application_id="app-1",
                model="mock:sentinel-flash",
                provider="mock",
                prompt="q",
                response="a",
                status="error",
                latency_ms=100.0,
                estimated_cost=0.001,
                evaluation_status="pending",
                created_at=datetime.now(UTC),
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
@respx.mock
async def test_alert_delivers_slack_format_when_configured(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    route = respx.post("http://example.test/hook").mock(return_value=httpx.Response(200))
    monkeypatch.setattr(
        alerting,
        "get_settings",
        lambda: Settings(
            alert_webhook_url="http://example.test/hook", alert_webhook_format="slack"
        ),
    )

    await _make_error_traces(db_session, 20)
    await evaluate_alert_rules(db_session)

    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert list(sent.keys()) == ["text"]


@pytest.mark.asyncio
@respx.mock
async def test_alert_delivers_generic_format_by_default(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    route = respx.post("http://example.test/hook").mock(return_value=httpx.Response(200))
    monkeypatch.setattr(
        alerting,
        "get_settings",
        lambda: Settings(alert_webhook_url="http://example.test/hook"),
    )

    await _make_error_traces(db_session, 20)
    await evaluate_alert_rules(db_session)

    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent["rule"] == "error_rate"
