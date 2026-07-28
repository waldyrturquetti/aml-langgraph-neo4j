from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AlertPayload:
    alert_id: str
    customer_id: str
    alert_type: str
    amount: float
    currency: str
    description: str


@dataclass(slots=True)
class EvidenceItem:
    kind: str
    subject: str
    details: str
    source: str


@dataclass(slots=True)
class TriageRecommendation:
    disposition: str
    rationale: str
    supporting_evidence: list[EvidenceItem] = field(default_factory=list)


@dataclass(slots=True)
class InsightResult:
    status: str = "not-requested"
    summary: str = ""
    key_observations: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class RiskAssessment:
    """Result of classifying retrieved evidence into AML typologies.

    `typologies` records which structural graph patterns were detected
    (e.g. "cycle", "structuring-fanout") so the recommendation and the
    LangGraph router can both react to the same evidence-derived signal.
    """

    level: str = "unknown"
    rationale: str = ""
    typologies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TriageState:
    alert: AlertPayload
    user_prompt: str = ""
    investigation_status: str = "pending"
    evidence: list[EvidenceItem] = field(default_factory=list)
    evidence_summary: str = ""
    hop_radius: int = 1
    enrichment_attempts: int = 0
    risk: RiskAssessment = field(default_factory=RiskAssessment)
    requires_human_review: bool = False
    analyst_decision: str | None = None
    insights: InsightResult = field(default_factory=InsightResult)
    recommendation: TriageRecommendation | None = None
    workflow_steps: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
