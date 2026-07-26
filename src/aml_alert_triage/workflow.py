from __future__ import annotations

from dataclasses import replace
from typing import Any
import logging

from .llm import LLMAdapter, InsightRequest, compose_insight_prompt
from .models import AlertPayload, InsightResult, TriageRecommendation, TriageState
from .repository import Neo4jAlertRepository, summarize_evidence

logger = logging.getLogger(__name__)


def initialize_state(alert: AlertPayload, user_prompt: str = "") -> TriageState:
    state = TriageState(
        alert=alert,
        user_prompt=user_prompt,
        investigation_status="initialized",
        workflow_steps=["initialized"],
        metadata={
            "alert_id": alert.alert_id,
            "customer_id": alert.customer_id,
            "user_prompt": user_prompt,
        },
    )
    logger.info("Initialized triage state for alert %s", alert.alert_id)
    return state


def enrich_state(state: TriageState, repository: Neo4jAlertRepository) -> TriageState:
    evidence = repository.fetch_connected_context(state.alert.customer_id)
    evidence_summary = summarize_evidence(evidence) if evidence else "No connected evidence was found in Neo4j."
    next_status = "enriched" if evidence else "enriched-without-graph-evidence"
    logger.info(
        "Loaded %s evidence items for customer %s",
        len(evidence),
        state.alert.customer_id,
    )
    return replace(
        state,
        evidence=evidence,
        evidence_summary=evidence_summary,
        investigation_status=next_status,
        workflow_steps=[*state.workflow_steps, "enriched"],
    )


def generate_insights(state: TriageState, llm_adapter: LLMAdapter) -> TriageState:
    request = InsightRequest(
        alert=state.alert,
        user_prompt=state.user_prompt,
        evidence=list(state.evidence),
        evidence_summary=state.evidence_summary,
    )
    prompt = compose_insight_prompt(request)

    try:
        insight_response = llm_adapter.generate_insights(request)
        insights = InsightResult(
            status="generated",
            summary=insight_response.summary,
            key_observations=insight_response.key_observations,
            error=None,
        )
        step = "insights-generated"
    except Exception as exc:
        insights = InsightResult(
            status="fallback",
            summary="No LLM insights are available. Continue with evidence-only triage guidance.",
            key_observations=["LLM insights are unavailable for this run."],
            error=str(exc),
        )
        step = "insights-fallback"

    logger.info("Processed insight stage for alert %s with status %s", state.alert.alert_id, insights.status)
    return replace(
        state,
        insights=insights,
        workflow_steps=[*state.workflow_steps, step],
        metadata={
            **state.metadata,
            "insight_prompt": prompt,
            "insight_status": insights.status,
        },
    )


def review_evidence(state: TriageState) -> TriageRecommendation:
    evidence_summary = state.evidence_summary or "No connected evidence was found in Neo4j."
    insights_summary = state.insights.summary or "No interpretive insights were generated."
    if state.evidence:
        disposition = "review"
        rationale = (
            f"Factual evidence: {evidence_summary} "
            f"Interpretive LLM insights: {insights_summary}"
        )
    else:
        disposition = "monitor"
        rationale = (
            "Factual evidence: no connected graph evidence was found. "
            f"Interpretive LLM insights: {insights_summary}"
        )

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


def build_triage_response(state: TriageState) -> dict[str, Any]:
    return {
        "alert_id": state.alert.alert_id,
        "status": state.investigation_status,
        "workflow_steps": list(state.workflow_steps),
        "disposition": state.recommendation.disposition if state.recommendation else None,
        "rationale": state.recommendation.rationale if state.recommendation else None,
        "evidence_count": len(state.evidence),
        "evidence_summary": state.evidence_summary,
        "insights": {
            "status": state.insights.status,
            "summary": state.insights.summary,
            "key_observations": list(state.insights.key_observations),
            "error": state.insights.error,
        },
    }


def build_langgraph(repository: Neo4jAlertRepository, llm_adapter: LLMAdapter):
    try:
        from langgraph.graph import END, StateGraph
    except Exception:  # pragma: no cover - optional dependency fallback
        return None

    graph = StateGraph(TriageState)

    def node_initialize(state: TriageState) -> TriageState:
        return initialize_state(state.alert, state.user_prompt)

    def node_enrich(state: TriageState) -> TriageState:
        return enrich_state(state, repository)

    def node_insights(state: TriageState) -> TriageState:
        return generate_insights(state, llm_adapter)

    def node_review(state: TriageState) -> TriageState:
        recommendation = review_evidence(state)
        return finalize_state(state, recommendation)

    graph.add_node("initialize", node_initialize)
    graph.add_node("enrich", node_enrich)
    graph.add_node("insights", node_insights)
    graph.add_node("review", node_review)
    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "enrich")
    graph.add_edge("enrich", "insights")
    graph.add_edge("insights", "review")
    graph.add_edge("review", END)
    return graph.compile()


def run_triage(
    alert: AlertPayload,
    repository: Neo4jAlertRepository,
    llm_adapter: LLMAdapter,
    user_prompt: str = "",
) -> TriageState:
    state = initialize_state(alert, user_prompt=user_prompt)
    state = enrich_state(state, repository)
    state = generate_insights(state, llm_adapter)
    recommendation = review_evidence(state)
    return finalize_state(state, recommendation)
