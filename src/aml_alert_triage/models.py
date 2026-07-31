from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Evidence kinds that repository.py's targeted detection queries (cycle,
# structuring, and alert-proximity) can produce. Their mere presence is
# treated as a high-risk structural signal, regardless of how many
# "ordinary" evidence items were also found. Shared between
# workflow.assess_risk and llm.RuleBasedLLMAdapter, so it lives here rather
# than in workflow.py (which llm.py cannot import without a cycle).
HIGH_RISK_EVIDENCE_KINDS = {"cycle", "structuring-fanout", "structuring-fanin", "alert-proximity"}


@dataclass(slots=True)
class EvidenceItem:
    kind: str
    subject: str
    details: str
    source: str


@dataclass(slots=True)
class AlertRecord:
    alert_id: str
    reason: str
    description: str


@dataclass(slots=True)
class AlertOutcome:
    action: str = "none"  # "none" | "existing" | "created"
    alert_id: str | None = None
    reason: str | None = None


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
    recommend_alert: bool = False
    alert_reason: str = ""


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
    customer_id: str
    user_prompt: str = ""
    investigation_status: str = "pending"
    evidence: list[EvidenceItem] = field(default_factory=list)
    evidence_summary: str = ""
    hop_radius: int = 1
    enrichment_attempts: int = 0
    existing_alert: AlertRecord | None = None
    risk: RiskAssessment = field(default_factory=RiskAssessment)
    requires_human_review: bool = False
    analyst_decision: str | None = None
    insights: InsightResult = field(default_factory=InsightResult)
    alert_outcome: AlertOutcome = field(default_factory=AlertOutcome)
    recommendation: TriageRecommendation | None = None
    workflow_steps: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
