from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .config import AppConfig
from .models import AlertPayload, EvidenceItem


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
    return RuleBasedLLMAdapter(provider=config.llm_provider, model=config.llm_model)
