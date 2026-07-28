from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

from .config import AppConfig
from .models import AlertPayload, EvidenceItem

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"


@dataclass(slots=True)
class InsightRequest:
    alert: AlertPayload
    user_prompt: str
    evidence: list[EvidenceItem]
    evidence_summary: str


@dataclass(slots=True)
class InsightResponse:
    summary: str
    key_observations: list[str]


class LLMAdapter(Protocol):
    def generate_insights(self, request: InsightRequest) -> InsightResponse:
        """Generate normalized insights from triage context."""


class DisabledLLMAdapter:
    def generate_insights(self, request: InsightRequest) -> InsightResponse:
        raise RuntimeError("LLM generation is disabled by configuration.")


@dataclass(slots=True)
class RuleBasedLLMAdapter:
    provider: str
    model: str

    def generate_insights(self, request: InsightRequest) -> InsightResponse:
        if request.evidence:
            summary = (
                f"Evidence indicates connected activity for customer {request.alert.customer_id}; "
                "analyst review should prioritize linked parties and repeated transactions."
            )
            observations = [
                f"Analyzed {len(request.evidence)} related evidence item(s).",
                f"Top evidence summary: {request.evidence_summary}",
            ]
        else:
            summary = (
                f"No connected graph evidence was found for customer {request.alert.customer_id}; "
                "continue monitoring and collect additional context before escalation."
            )
            observations = [
                "Graph query returned no related entities for this alert.",
                "Disposition should remain evidence-conservative.",
            ]

        if request.user_prompt:
            observations.append(f"User prompt focus: {request.user_prompt}")

        return InsightResponse(summary=summary, key_observations=observations)


INSIGHT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_observations": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["summary", "key_observations"],
    "additionalProperties": False,
}

ANTHROPIC_SYSTEM_PROMPT = (
    "You are an AML learning assistant reviewing fictional data only. "
    "Use only the evidence supplied in the request, never invent facts, and "
    "respond with concise, evidence-grounded insights."
)


@dataclass(slots=True)
class AnthropicLLMAdapter:
    """LLM adapter backed by the real Anthropic Claude API.

    A client can be injected for testing; otherwise one is lazily created
    from the `anthropic` package and standard Anthropic credential resolution
    (e.g. the ANTHROPIC_API_KEY environment variable).
    """

    model: str = DEFAULT_ANTHROPIC_MODEL
    timeout_seconds: int = 15
    max_tokens: int = 1024
    client: object | None = None

    def _get_client(self) -> object:
        if self.client is not None:
            return self.client

        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The 'anthropic' package is required for the anthropic LLM provider. "
                "Install it with `pip install anthropic` (or `pip install -e .[llm]`)."
            ) from exc

        self.client = anthropic.Anthropic(timeout=self.timeout_seconds)
        return self.client

    def generate_insights(self, request: InsightRequest) -> InsightResponse:
        client = self._get_client()
        prompt = compose_insight_prompt(request)

        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=ANTHROPIC_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": INSIGHT_RESPONSE_SCHEMA}},
        )

        text = next(block.text for block in response.content if block.type == "text")
        payload = json.loads(text)

        return InsightResponse(
            summary=str(payload["summary"]),
            key_observations=[str(item) for item in payload["key_observations"]],
        )


def compose_insight_prompt(request: InsightRequest) -> str:
    evidence_lines = [
        f"- {item.kind} | {item.subject} | {item.details} | source={item.source}"
        for item in request.evidence
    ]
    evidence_block = "\n".join(evidence_lines) if evidence_lines else "- no-related-evidence"

    return (
        "You are an AML learning assistant. Use only the supplied fictional evidence. "
        "Do not invent facts. Return concise insights and separate interpretation from facts.\n"
        f"User prompt: {request.user_prompt or 'General AML triage guidance'}\n"
        f"Alert ID: {request.alert.alert_id}\n"
        f"Customer ID: {request.alert.customer_id}\n"
        f"Evidence summary: {request.evidence_summary}\n"
        f"Evidence items:\n{evidence_block}"
    )


def create_llm_adapter(config: AppConfig) -> LLMAdapter:
    if not config.llm_enabled:
        return DisabledLLMAdapter()

    if config.llm_provider == "anthropic":
        model = config.llm_model if config.llm_model != AppConfig().llm_model else DEFAULT_ANTHROPIC_MODEL
        return AnthropicLLMAdapter(model=model, timeout_seconds=config.llm_timeout_seconds)

    return RuleBasedLLMAdapter(provider=config.llm_provider, model=config.llm_model)
