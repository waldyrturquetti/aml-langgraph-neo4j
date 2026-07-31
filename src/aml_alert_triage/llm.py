from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Protocol

from .config import AppConfig
from .models import AlertRecord, HIGH_RISK_EVIDENCE_KINDS, EvidenceItem

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_OPENAI_MODEL = "gpt-5"
DEFAULT_REASONING_EFFORT = "medium"


@dataclass(slots=True)
class InsightRequest:
    customer_id: str
    user_prompt: str
    evidence: list[EvidenceItem]
    evidence_summary: str
    existing_alert: AlertRecord | None = None


@dataclass(slots=True)
class InsightResponse:
    summary: str
    key_observations: list[str]
    recommend_alert: bool = False
    alert_reason: str = ""
    # Portuguese (pt-BR) counterparts of summary/key_observations/alert_reason
    # - same facts and conclusion, translated - used only by the alert
    # investigation report (report.py), never by the CLI JSON response or
    # what gets written to Neo4j, which stay in English.
    summary_pt: str = ""
    key_observations_pt: list[str] = field(default_factory=list)
    alert_reason_pt: str = ""


class LLMAdapter(Protocol):
    def generate_insights(self, request: InsightRequest) -> InsightResponse:
        """Generate normalized insights from triage context."""


@dataclass(slots=True)
class RuleBasedLLMAdapter:
    """Deterministic, offline "static" insight adapter - no network call.

    Used whenever AML_ALERT_LLM_ENABLED=false. Its alert recommendation
    directly mirrors the same structural signal `workflow.assess_risk`
    uses (HIGH_RISK_EVIDENCE_KINDS membership), since a template has no
    reasoning of its own to add beyond what the graph queries already found.
    """

    provider: str
    model: str

    def generate_insights(self, request: InsightRequest) -> InsightResponse:
        from .i18n_pt import KIND_LABELS_PT, translate_evidence_summary_pt

        high_risk_items = [item for item in request.evidence if item.kind in HIGH_RISK_EVIDENCE_KINDS]

        if request.evidence:
            summary = (
                f"Evidence indicates connected activity for customer {request.customer_id}; "
                "analyst review should prioritize linked parties and repeated transactions."
            )
            summary_pt = (
                f"As evidências indicam atividade conectada para o cliente {request.customer_id}; "
                "a revisão do analista deve priorizar partes relacionadas e transações repetidas."
            )
            observations = [
                f"Analyzed {len(request.evidence)} related evidence item(s).",
                f"Top evidence summary: {request.evidence_summary}",
            ]
            observations_pt = [
                f"Analisados {len(request.evidence)} item(ns) de evidência relacionados.",
                f"Resumo principal da evidência: {translate_evidence_summary_pt(request.evidence)}",
            ]
        else:
            summary = (
                f"No connected graph evidence was found for customer {request.customer_id}; "
                "continue monitoring and collect additional context before escalation."
            )
            summary_pt = (
                f"Nenhuma evidência de grafo conectada foi encontrada para o cliente {request.customer_id}; "
                "continue monitorando e colete mais contexto antes de escalar."
            )
            observations = [
                "Graph query returned no related entities for this alert.",
                "Disposition should remain evidence-conservative.",
            ]
            observations_pt = [
                "A consulta ao grafo não retornou entidades relacionadas para este alerta.",
                "A disposição deve permanecer conservadora quanto à evidência.",
            ]

        if request.user_prompt:
            observations.append(f"User prompt focus: {request.user_prompt}")
            observations_pt.append(f"Foco solicitado pelo usuário: {request.user_prompt}")

        recommend_alert = bool(high_risk_items)
        detected_kinds = sorted({item.kind for item in high_risk_items})
        alert_reason = "Structural pattern(s) detected: " + ", ".join(detected_kinds) + "." if recommend_alert else ""
        alert_reason_pt = (
            "Padrão(ões) estrutural(is) detectado(s): "
            + ", ".join(sorted({KIND_LABELS_PT.get(kind, kind) for kind in detected_kinds}))
            + "."
            if recommend_alert
            else ""
        )

        return InsightResponse(
            summary=summary,
            key_observations=observations,
            recommend_alert=recommend_alert,
            alert_reason=alert_reason,
            summary_pt=summary_pt,
            key_observations_pt=observations_pt,
            alert_reason_pt=alert_reason_pt,
        )


INSIGHT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_observations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommend_alert": {"type": "boolean"},
        "alert_reason": {"type": "string"},
        "summary_pt": {"type": "string"},
        "key_observations_pt": {
            "type": "array",
            "items": {"type": "string"},
        },
        "alert_reason_pt": {"type": "string"},
    },
    "required": [
        "summary",
        "key_observations",
        "recommend_alert",
        "alert_reason",
        "summary_pt",
        "key_observations_pt",
        "alert_reason_pt",
    ],
    "additionalProperties": False,
}

ANTHROPIC_SYSTEM_PROMPT = (
    "You are an AML learning assistant reviewing fictional data only. "
    "Use only the evidence supplied in the request, never invent facts, and "
    "respond with concise, evidence-grounded insights. "
    "Only set recommend_alert to true when the supplied evidence shows a concrete "
    "suspicious pattern (e.g. a transfer cycle, structuring, or proximity to an "
    "already-alerted customer); never recommend an alert from absence of evidence "
    "or speculation. When recommend_alert is true, alert_reason must briefly cite "
    "the specific evidence that justifies it. "
    "In addition to the English summary/key_observations/alert_reason fields, also "
    "provide summary_pt, key_observations_pt, and alert_reason_pt: faithful Brazilian "
    "Portuguese (pt-BR) translations of that same content - the same facts and "
    "conclusion, not a different analysis - for a Brazilian analyst-facing report."
)

OPENAI_SYSTEM_PROMPT = ANTHROPIC_SYSTEM_PROMPT


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
            recommend_alert=bool(payload.get("recommend_alert", False)),
            alert_reason=str(payload.get("alert_reason", "")),
            summary_pt=str(payload.get("summary_pt", "")),
            key_observations_pt=[str(item) for item in payload.get("key_observations_pt", [])],
            alert_reason_pt=str(payload.get("alert_reason_pt", "")),
        )


@dataclass(slots=True)
class OpenAILLMAdapter:
    """LLM adapter backed by the OpenAI Chat Completions API.

    A client can be injected for testing; otherwise one is lazily created
    from the `openai` package and standard OpenAI credential resolution
    (e.g. the OPENAI_API_KEY environment variable). When `reasoning_effort`
    is set, it is forwarded to the API so reasoning-capable models (e.g.
    the `o` series or `gpt-5`) think before answering.
    """

    model: str = DEFAULT_OPENAI_MODEL
    timeout_seconds: int = 15
    # Reasoning-capable models (o-series, gpt-5) spend part of this budget on
    # internal "thinking" tokens before producing the visible JSON answer -
    # with reasoning_effort set, 1024 total tokens can be entirely consumed
    # by reasoning, leaving an empty response and a confusing JSON-parse
    # failure. 4096 leaves enough headroom for reasoning plus the (small)
    # structured answer.
    max_tokens: int = 4096
    reasoning_effort: str | None = None
    client: object | None = None

    def _get_client(self) -> object:
        if self.client is not None:
            return self.client

        try:
            import openai
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is required for the openai LLM provider. "
                "Install it with `pip install openai` (or `pip install -e .[llm]`)."
            ) from exc

        self.client = openai.OpenAI(timeout=self.timeout_seconds)
        return self.client

    def generate_insights(self, request: InsightRequest) -> InsightResponse:
        client = self._get_client()
        prompt = compose_insight_prompt(request)

        kwargs: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": OPENAI_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": self.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "insight_response",
                    "schema": INSIGHT_RESPONSE_SCHEMA,
                    "strict": True,
                },
            },
        }
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort

        response = client.chat.completions.create(**kwargs)

        text = response.choices[0].message.content
        if not text:
            finish_reason = response.choices[0].finish_reason
            raise RuntimeError(
                f"OpenAI returned an empty response (finish_reason={finish_reason!r}). "
                "This usually means max_tokens was too small for the model's reasoning "
                "budget - try raising it."
            )
        payload = json.loads(text)

        return InsightResponse(
            summary=str(payload["summary"]),
            key_observations=[str(item) for item in payload["key_observations"]],
            recommend_alert=bool(payload.get("recommend_alert", False)),
            alert_reason=str(payload.get("alert_reason", "")),
            summary_pt=str(payload.get("summary_pt", "")),
            key_observations_pt=[str(item) for item in payload.get("key_observations_pt", [])],
            alert_reason_pt=str(payload.get("alert_reason_pt", "")),
        )


def compose_insight_prompt(request: InsightRequest) -> str:
    evidence_lines = [
        f"- {item.kind} | {item.subject} | {item.details} | source={item.source}"
        for item in request.evidence
    ]
    evidence_block = "\n".join(evidence_lines) if evidence_lines else "- no-related-evidence"

    if request.existing_alert is not None:
        existing_alert_line = (
            f"Existing alert: {request.existing_alert.alert_id} (reason: {request.existing_alert.reason}) "
            "already exists for this customer - do not recommend creating another one."
        )
    else:
        existing_alert_line = "Existing alert: none on file for this customer."

    return (
        "You are an AML learning assistant. Use only the supplied fictional evidence. "
        "Do not invent facts. Return concise insights, separate interpretation from facts, "
        "and decide whether an alert should be recommended based solely on the evidence below.\n"
        f"User prompt: {request.user_prompt or 'General AML triage guidance'}\n"
        f"Customer ID: {request.customer_id}\n"
        f"{existing_alert_line}\n"
        f"Evidence summary: {request.evidence_summary}\n"
        f"Evidence items:\n{evidence_block}"
    )


def create_llm_adapter(config: AppConfig) -> LLMAdapter:
    if not config.llm_enabled:
        return RuleBasedLLMAdapter(provider="rule-based", model=config.llm_model)

    if config.llm_provider == "openai":
        default_model_configured = config.llm_model == AppConfig().llm_model
        model = DEFAULT_OPENAI_MODEL if default_model_configured else config.llm_model
        reasoning_effort = config.llm_reasoning_effort or DEFAULT_REASONING_EFFORT
        return OpenAILLMAdapter(
            model=model,
            timeout_seconds=config.llm_timeout_seconds,
            reasoning_effort=reasoning_effort,
        )

    default_model_configured = config.llm_model == AppConfig().llm_model
    model = DEFAULT_ANTHROPIC_MODEL if default_model_configured else config.llm_model
    return AnthropicLLMAdapter(model=model, timeout_seconds=config.llm_timeout_seconds)
