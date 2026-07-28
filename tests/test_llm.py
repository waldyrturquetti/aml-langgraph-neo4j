import json

import pytest

from aml_alert_triage.config import AppConfig
from aml_alert_triage.llm import (
    DEFAULT_ANTHROPIC_MODEL,
    AnthropicLLMAdapter,
    DisabledLLMAdapter,
    InsightRequest,
    RuleBasedLLMAdapter,
    compose_insight_prompt,
    create_llm_adapter,
)
from aml_alert_triage.models import AlertPayload, EvidenceItem

ALERT = AlertPayload(
    alert_id="alert-001",
    customer_id="cust-100",
    alert_type="cash-structuring",
    amount=12800.0,
    currency="USD",
    description="Multiple cash deposits below the reporting threshold.",
)


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, content: list[object]) -> None:
        self.content = content


class _FakeMessages:
    def __init__(self, response: object | None = None, exception: Exception | None = None) -> None:
        self._response = response
        self._exception = exception
        self.last_kwargs: dict[str, object] | None = None

    def create(self, **kwargs: object) -> object:
        self.last_kwargs = kwargs
        if self._exception is not None:
            raise self._exception
        assert self._response is not None
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response: object | None = None, exception: Exception | None = None) -> None:
        self.messages = _FakeMessages(response=response, exception=exception)


def _make_request(evidence: list[EvidenceItem] | None = None, user_prompt: str = "") -> InsightRequest:
    items = evidence if evidence is not None else []
    summary = "; ".join(item.details for item in items)
    return InsightRequest(
        alert=ALERT,
        user_prompt=user_prompt,
        evidence=items,
        evidence_summary=summary,
    )


def test_compose_insight_prompt_includes_evidence_details() -> None:
    evidence = [
        EvidenceItem(kind="transaction", subject="acct-001", details="Five cash deposits.", source="neo4j"),
    ]
    request = _make_request(evidence=evidence, user_prompt="Explain suspicious links")

    prompt = compose_insight_prompt(request)

    assert "alert-001" in prompt
    assert "cust-100" in prompt
    assert "Explain suspicious links" in prompt
    assert "transaction | acct-001 | Five cash deposits. | source=neo4j" in prompt


def test_compose_insight_prompt_handles_no_evidence() -> None:
    request = _make_request(evidence=[], user_prompt="")

    prompt = compose_insight_prompt(request)

    assert "no-related-evidence" in prompt
    assert "General AML triage guidance" in prompt


def test_create_llm_adapter_returns_disabled_when_llm_disabled() -> None:
    adapter = create_llm_adapter(AppConfig(llm_enabled=False))

    assert isinstance(adapter, DisabledLLMAdapter)
    with pytest.raises(RuntimeError, match="disabled by configuration"):
        adapter.generate_insights(_make_request())


def test_create_llm_adapter_returns_rule_based_by_default() -> None:
    adapter = create_llm_adapter(AppConfig(llm_enabled=True))

    assert isinstance(adapter, RuleBasedLLMAdapter)
    assert adapter.provider == "rule-based"


def test_create_llm_adapter_returns_anthropic_adapter_with_default_model() -> None:
    config = AppConfig(llm_enabled=True, llm_provider="anthropic")

    adapter = create_llm_adapter(config)

    assert isinstance(adapter, AnthropicLLMAdapter)
    assert adapter.model == DEFAULT_ANTHROPIC_MODEL


def test_create_llm_adapter_returns_anthropic_adapter_with_custom_model() -> None:
    config = AppConfig(llm_enabled=True, llm_provider="anthropic", llm_model="claude-opus-5")

    adapter = create_llm_adapter(config)

    assert isinstance(adapter, AnthropicLLMAdapter)
    assert adapter.model == "claude-opus-5"


def test_anthropic_adapter_sends_expected_request_and_parses_response() -> None:
    payload = {
        "summary": "Linked activity suggests moderate escalation risk.",
        "key_observations": ["Observed repeated linked transactions."],
    }
    fake_client = _FakeAnthropicClient(response=_FakeResponse(content=[_FakeTextBlock(json.dumps(payload))]))
    adapter = AnthropicLLMAdapter(model="claude-sonnet-5", timeout_seconds=5, client=fake_client)

    evidence = [EvidenceItem(kind="transaction", subject="acct-001", details="Five deposits.", source="neo4j")]
    request = _make_request(evidence=evidence, user_prompt="Summarize the risk")

    response = adapter.generate_insights(request)

    assert response.summary == payload["summary"]
    assert response.key_observations == payload["key_observations"]

    sent = fake_client.messages.last_kwargs
    assert sent["model"] == "claude-sonnet-5"
    assert sent["messages"][0]["role"] == "user"
    assert "acct-001" in sent["messages"][0]["content"]
    assert sent["output_config"]["format"]["type"] == "json_schema"


def test_anthropic_adapter_propagates_provider_errors() -> None:
    fake_client = _FakeAnthropicClient(exception=RuntimeError("provider timeout"))
    adapter = AnthropicLLMAdapter(model="claude-sonnet-5", client=fake_client)

    with pytest.raises(RuntimeError, match="provider timeout"):
        adapter.generate_insights(_make_request())


def test_anthropic_adapter_propagates_malformed_response_errors() -> None:
    fake_client = _FakeAnthropicClient(response=_FakeResponse(content=[_FakeTextBlock("not-json")]))
    adapter = AnthropicLLMAdapter(model="claude-sonnet-5", client=fake_client)

    with pytest.raises(json.JSONDecodeError):
        adapter.generate_insights(_make_request())
