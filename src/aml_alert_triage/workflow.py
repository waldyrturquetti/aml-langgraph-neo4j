from __future__ import annotations

from dataclasses import replace
from typing import Any
import logging

from .models import AlertPayload, EvidenceItem, TriageRecommendation, TriageState
from .repository import Neo4jAlertRepository, summarize_evidence

logger = logging.getLogger(__name__)


def initialize_state(alert: AlertPayload) -> TriageState:
    state = TriageState(
        alert=alert,
        investigation_status="initialized",
        workflow_steps=["initialized"],
        metadata={"alert_id": alert.alert_id, "customer_id": alert.customer_id},
    )
    logger.info("Initialized triage state for alert %s", alert.alert_id)
    return state


def enrich_state(state: TriageState, repository: Neo4jAlertRepository) -> TriageState:
    evidence = repository.fetch_connected_context(state.alert.customer_id)
    next_status = "enriched" if evidence else "enriched-without-graph-evidence"
    logger.info(
        "Loaded %s evidence items for customer %s",
        len(evidence),
        state.alert.customer_id,
    )
    return replace(
        state,
        evidence=evidence,
        investigation_status=next_status,
        workflow_steps=[*state.workflow_steps, "enriched"],
    )


def review_evidence(state: TriageState) -> TriageRecommendation:
    evidence_summary = summarize_evidence(state.evidence) if state.evidence else "No connected evidence was found in Neo4j."
    if state.evidence:
        disposition = "review"
        rationale = f"The alert is supported by related graph evidence: {evidence_summary}"
    else:
        disposition = "monitor"
        rationale = "The alert could not be substantiated by connected graph evidence, so it should be monitored for now."

    recommendation = TriageRecommendation(
        disposition=disposition,
        rationale=rationale,
        supporting_evidence=list(state.evidence),
    )
    logger.info("Generated recommendation %s for alert %s", disposition, state.alert.alert_id)
    return recommendation


def finalize_state(state: TriageState, recommendation: TriageRecommendation) -> TriageState:
    return replace(
        state,
        recommendation=recommendation,
        investigation_status="completed",
        workflow_steps=[*state.workflow_steps, "reviewed", "completed"],
    )


def build_langgraph(repository: Neo4jAlertRepository):
    try:
        from langgraph.graph import END, StateGraph
    except Exception:  # pragma: no cover - optional dependency fallback
        return None

    graph = StateGraph(TriageState)

    def node_initialize(state: TriageState) -> TriageState:
        return initialize_state(state.alert)

    def node_enrich(state: TriageState) -> TriageState:
        return enrich_state(state, repository)

    def node_review(state: TriageState) -> TriageState:
        recommendation = review_evidence(state)
        return finalize_state(state, recommendation)

    graph.add_node("initialize", node_initialize)
    graph.add_node("enrich", node_enrich)
    graph.add_node("review", node_review)
    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "enrich")
    graph.add_edge("enrich", "review")
    graph.add_edge("review", END)
    return graph.compile()


def run_triage(alert: AlertPayload, repository: Neo4jAlertRepository) -> TriageState:
    state = initialize_state(alert)
    state = enrich_state(state, repository)
    recommendation = review_evidence(state)
    return finalize_state(state, recommendation)
