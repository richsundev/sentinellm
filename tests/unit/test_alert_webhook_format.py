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


@pytest.mark.asyncio
@respx.mock
async def test_a_webhook_that_rejects_the_alert_is_reported_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 4xx/5xx is a delivery failure (a revoked Slack URL, a bad payload);
    only transport errors used to be logged, so it looked like it had worked."""
    from structlog.testing import capture_logs

    from sentinellm.db.models import Alert

    respx.post("http://example.test/hook").mock(return_value=httpx.Response(410))
    monkeypatch.setattr(
        alerting, "get_settings", lambda: Settings(alert_webhook_url="http://example.test/hook")
    )
    alert = Alert(
        rule="error_rate", current_value=1, threshold=0.5, severity="high", affected_service="s"
    )

    with capture_logs() as logs:
        await alerting.deliver_alert_webhook(alert)

    failed = [entry for entry in logs if entry["event"] == "alert_webhook_delivery_failed"]
    assert failed and failed[0]["status"] == 410


@pytest.mark.asyncio
async def test_a_malformed_webhook_url_cannot_break_the_alert_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delivery runs inside the pass that persists the alert; anything it
    raised aborted the pass, so the alert was never stored and re-failed
    forever."""
    from sentinellm.db.models import Alert

    monkeypatch.setattr(alerting, "get_settings", lambda: Settings(alert_webhook_url="http://[::1"))
    alert = Alert(
        rule="error_rate", current_value=1, threshold=0.5, severity="high", affected_service="s"
    )

    await alerting.deliver_alert_webhook(alert)  # must not raise
