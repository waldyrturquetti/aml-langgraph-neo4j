import json

import pytest

from aml_alert_triage.config import AppConfig
from aml_alert_triage.llm import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_REASONING_EFFORT,
    AnthropicLLMAdapter,
    InsightRequest,
    OpenAILLMAdapter,
    RuleBasedLLMAdapter,
    compose_insight_prompt,
    create_llm_adapter,
)
from aml_alert_triage.models import AlertRecord, EvidenceItem


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeAnthropicResponse:
    def __init__(self, content: list[object]) -> None:
        self.content = content


class _FakeAnthropicMessages:
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
        self.messages = _FakeAnthropicMessages(response=response, exception=exception)


class _FakeOpenAIMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeOpenAIChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeOpenAIMessage(content)


class _FakeOpenAIResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeOpenAIChoice(content)]


class _FakeOpenAICompletions:
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


class _FakeOpenAIChat:
    def __init__(self, completions: _FakeOpenAICompletions) -> None:
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, response: object | None = None, exception: Exception | None = None) -> None:
        self.chat = _FakeOpenAIChat(_FakeOpenAICompletions(response=response, exception=exception))


def _make_request(
    evidence: list[EvidenceItem] | None = None,
    user_prompt: str = "",
    existing_alert: AlertRecord | None = None,
) -> InsightRequest:
    items = evidence if evidence is not None else []
    summary = "; ".join(item.details for item in items)
    return InsightRequest(
        customer_id="cust-100",
        user_prompt=user_prompt,
        evidence=items,
        evidence_summary=summary,
        existing_alert=existing_alert,
    )


def test_compose_insight_prompt_includes_evidence_details() -> None:
    evidence = [
        EvidenceItem(kind="transaction", subject="acct-001", details="Five cash deposits.", source="neo4j"),
    ]
    request = _make_request(evidence=evidence, user_prompt="Explain suspicious links")

    prompt = compose_insight_prompt(request)

    assert "cust-100" in prompt
    assert "Explain suspicious links" in prompt
    assert "transaction | acct-001 | Five cash deposits. | source=neo4j" in prompt
    assert "Existing alert: none on file" in prompt


def test_compose_insight_prompt_handles_no_evidence() -> None:
    request = _make_request(evidence=[], user_prompt="")

    prompt = compose_insight_prompt(request)

    assert "no-related-evidence" in prompt
    assert "General AML triage guidance" in prompt


def test_compose_insight_prompt_mentions_existing_alert() -> None:
    existing = AlertRecord(alert_id="alert-auto-cust-100", reason="cycle-detected", description="...")
    request = _make_request(existing_alert=existing)

    prompt = compose_insight_prompt(request)

    assert "alert-auto-cust-100" in prompt
    assert "do not recommend creating another one" in prompt


def test_create_llm_adapter_returns_rule_based_when_disabled() -> None:
    adapter = create_llm_adapter(AppConfig(llm_enabled=False))

    assert isinstance(adapter, RuleBasedLLMAdapter)


def test_create_llm_adapter_returns_anthropic_by_default_when_enabled() -> None:
    adapter = create_llm_adapter(AppConfig(llm_enabled=True))

    assert isinstance(adapter, AnthropicLLMAdapter)
    assert adapter.model == DEFAULT_ANTHROPIC_MODEL


def test_create_llm_adapter_returns_anthropic_adapter_with_custom_model() -> None:
    config = AppConfig(llm_enabled=True, llm_provider="anthropic", llm_model="claude-opus-5")

    adapter = create_llm_adapter(config)

    assert isinstance(adapter, AnthropicLLMAdapter)
    assert adapter.model == "claude-opus-5"


def test_create_llm_adapter_returns_openai_adapter_with_default_model() -> None:
    config = AppConfig(llm_enabled=True, llm_provider="openai")

    adapter = create_llm_adapter(config)

    assert isinstance(adapter, OpenAILLMAdapter)
    assert adapter.model == DEFAULT_OPENAI_MODEL
    assert adapter.reasoning_effort == DEFAULT_REASONING_EFFORT


def test_create_llm_adapter_returns_openai_adapter_with_custom_model() -> None:
    config = AppConfig(llm_enabled=True, llm_provider="openai", llm_model="gpt-5-mini")

    adapter = create_llm_adapter(config)

    assert isinstance(adapter, OpenAILLMAdapter)
    assert adapter.model == "gpt-5-mini"


def test_create_llm_adapter_respects_explicit_reasoning_effort() -> None:
    config = AppConfig(llm_enabled=True, llm_provider="openai", llm_reasoning_effort="high")

    adapter = create_llm_adapter(config)

    assert isinstance(adapter, OpenAILLMAdapter)
    assert adapter.reasoning_effort == "high"


def test_rule_based_adapter_recommends_alert_for_high_risk_evidence() -> None:
    evidence = [EvidenceItem(kind="cycle", subject="cust-300", details="4-hop cycle.", source="neo4j")]
    adapter = RuleBasedLLMAdapter(provider="rule-based", model="local-insight-summarizer")

    response = adapter.generate_insights(_make_request(evidence=evidence))

    assert response.recommend_alert is True
    assert "cycle" in response.alert_reason


def test_rule_based_adapter_does_not_recommend_alert_for_ordinary_evidence() -> None:
    evidence = [EvidenceItem(kind="pix", subject="acct-002", details="A pix transfer.", source="neo4j")]
    adapter = RuleBasedLLMAdapter(provider="rule-based", model="local-insight-summarizer")

    response = adapter.generate_insights(_make_request(evidence=evidence))

    assert response.recommend_alert is False
    assert response.alert_reason == ""


def test_anthropic_adapter_sends_expected_request_and_parses_response() -> None:
    payload = {
        "summary": "Linked activity suggests moderate escalation risk.",
        "key_observations": ["Observed repeated linked transactions."],
        "recommend_alert": True,
        "alert_reason": "Cycle detected in transfer graph.",
    }
    fake_client = _FakeAnthropicClient(
        response=_FakeAnthropicResponse(content=[_FakeTextBlock(json.dumps(payload))])
    )
    adapter = AnthropicLLMAdapter(model="claude-sonnet-5", timeout_seconds=5, client=fake_client)

    evidence = [EvidenceItem(kind="transaction", subject="acct-001", details="Five deposits.", source="neo4j")]
    request = _make_request(evidence=evidence, user_prompt="Summarize the risk")

    response = adapter.generate_insights(request)

    assert response.summary == payload["summary"]
    assert response.key_observations == payload["key_observations"]
    assert response.recommend_alert is True
    assert response.alert_reason == payload["alert_reason"]

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
    fake_client = _FakeAnthropicClient(response=_FakeAnthropicResponse(content=[_FakeTextBlock("not-json")]))
    adapter = AnthropicLLMAdapter(model="claude-sonnet-5", client=fake_client)

    with pytest.raises(json.JSONDecodeError):
        adapter.generate_insights(_make_request())


def test_openai_adapter_sends_expected_request_and_parses_response() -> None:
    payload = {
        "summary": "Structuring fan-out detected.",
        "key_observations": ["Six distinct beneficiaries just under threshold."],
        "recommend_alert": True,
        "alert_reason": "Structuring fan-out detected.",
    }
    fake_client = _FakeOpenAIClient(response=_FakeOpenAIResponse(json.dumps(payload)))
    adapter = OpenAILLMAdapter(model="gpt-5", timeout_seconds=5, reasoning_effort="medium", client=fake_client)

    evidence = [EvidenceItem(kind="structuring-fanout", subject="cust-207", details="6 beneficiaries.", source="neo4j")]
    request = _make_request(evidence=evidence, user_prompt="Summarize the risk")

    response = adapter.generate_insights(request)

    assert response.summary == payload["summary"]
    assert response.key_observations == payload["key_observations"]
    assert response.recommend_alert is True
    assert response.alert_reason == payload["alert_reason"]

    sent = fake_client.chat.completions.last_kwargs
    assert sent["model"] == "gpt-5"
    assert sent["reasoning_effort"] == "medium"
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][1]["role"] == "user"
    assert "cust-207" in sent["messages"][1]["content"]
    assert sent["response_format"]["type"] == "json_schema"


def test_openai_adapter_omits_reasoning_effort_when_unset() -> None:
    payload = {"summary": "x", "key_observations": [], "recommend_alert": False, "alert_reason": ""}
    fake_client = _FakeOpenAIClient(response=_FakeOpenAIResponse(json.dumps(payload)))
    adapter = OpenAILLMAdapter(model="gpt-5", client=fake_client)

    adapter.generate_insights(_make_request())

    assert "reasoning_effort" not in fake_client.chat.completions.last_kwargs


def test_openai_adapter_propagates_provider_errors() -> None:
    fake_client = _FakeOpenAIClient(exception=RuntimeError("provider timeout"))
    adapter = OpenAILLMAdapter(model="gpt-5", client=fake_client)

    with pytest.raises(RuntimeError, match="provider timeout"):
        adapter.generate_insights(_make_request())


def test_openai_adapter_propagates_malformed_response_errors() -> None:
    fake_client = _FakeOpenAIClient(response=_FakeOpenAIResponse("not-json"))
    adapter = OpenAILLMAdapter(model="gpt-5", client=fake_client)

    with pytest.raises(json.JSONDecodeError):
        adapter.generate_insights(_make_request())
