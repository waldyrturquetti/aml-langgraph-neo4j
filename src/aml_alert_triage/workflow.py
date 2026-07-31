from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable
import logging

from .config import AppConfig
from .llm import LLMAdapter, InsightRequest, compose_insight_prompt
from .models import AlertOutcome, InsightResult, RiskAssessment, TriageRecommendation, TriageState, HIGH_RISK_EVIDENCE_KINDS
from .repository import Neo4jAlertRepository, summarize_evidence
from .snapshot_store import AlertSnapshot, AlertSnapshotStore

logger = logging.getLogger(__name__)


def initialize_state(customer_id: str, user_prompt: str = "") -> TriageState:
    state = TriageState(
        customer_id=customer_id,
        user_prompt=user_prompt,
        investigation_status="initialized",
        workflow_steps=["initialized"],
        metadata={
            "customer_id": customer_id,
            "user_prompt": user_prompt,
        },
    )
    logger.info("Initialized triage state for customer %s", customer_id)
    return state


def enrich_state(state: TriageState, repository: Neo4jAlertRepository) -> TriageState:
    evidence = repository.fetch_connected_context(state.customer_id, hop_radius=state.hop_radius)
    evidence_summary = summarize_evidence(evidence) if evidence else "No connected evidence was found in Neo4j."
    next_status = "enriched" if evidence else "enriched-without-graph-evidence"
    existing_alert = repository.find_alert_for_customer(state.customer_id)
    logger.info(
        "Loaded %s evidence items for customer %s at hop radius %s",
        len(evidence),
        state.customer_id,
        state.hop_radius,
    )
    return replace(
        state,
        evidence=evidence,
        evidence_summary=evidence_summary,
        investigation_status=next_status,
        enrichment_attempts=state.enrichment_attempts + 1,
        existing_alert=existing_alert,
        workflow_steps=[*state.workflow_steps, f"enriched-hop-{state.hop_radius}"],
    )


def should_widen_search(state: TriageState, config: AppConfig) -> bool:
    """Decide whether to retry enrichment with a wider Neo4j hop radius.

    Retries while evidence is thinner than `min_evidence_for_conclusion`
    (not just literally empty - a single ordinary-looking transaction isn't
    enough to conclude anything either), the attempt budget is not
    exhausted, and there is still hop radius left to widen into - so the
    loop is always bounded and terminates deterministically.
    """
    return (
        len(state.evidence) < config.min_evidence_for_conclusion
        and state.enrichment_attempts < config.max_enrichment_attempts
        and state.hop_radius < config.neo4j_max_hops
    )


def widen_search(state: TriageState) -> TriageState:
    return replace(
        state,
        hop_radius=state.hop_radius + 1,
        workflow_steps=[*state.workflow_steps, "widened-search-radius"],
    )


def generate_insights(state: TriageState, llm_adapter: LLMAdapter) -> TriageState:
    request = InsightRequest(
        customer_id=state.customer_id,
        existing_alert=state.existing_alert,
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
            recommend_alert=insight_response.recommend_alert,
            alert_reason=insight_response.alert_reason,
        )
        step = "insights-generated"
    except Exception as exc:
        insights = InsightResult(
            status="fallback",
            summary="No LLM insights are available. Continue with evidence-only triage guidance.",
            key_observations=["LLM insights are unavailable for this run."],
            error=str(exc),
            recommend_alert=False,
            alert_reason="",
        )
        step = "insights-fallback"

    logger.info("Processed insight stage for customer %s with status %s", state.customer_id, insights.status)
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


def _insight_mode(config: AppConfig) -> str:
    return "static" if not config.llm_enabled else config.llm_provider


def register_alert(
    state: TriageState,
    repository: Neo4jAlertRepository,
    config: AppConfig,
    snapshot_store: AlertSnapshotStore | None = None,
) -> TriageState:
    """Idempotent alert write-back: if the customer already has an alert,
    report it unchanged; otherwise create one only when insight generation
    (static or real LLM, whichever ran) recommended it. This is
    deliberately independent of `assess_risk`'s structural risk level - it
    reacts to the insight's own grounded judgment, not the cycle/structuring
    classification (see design.md for why the two signals stay separate).

    On a newly-created alert, also persists an immutable evidence/insight
    snapshot (best-effort - a snapshot failure never breaks the
    investigation, only later report generation for that alert)."""
    if state.existing_alert is not None:
        outcome = AlertOutcome(
            action="existing", alert_id=state.existing_alert.alert_id, reason=state.existing_alert.reason
        )
        step = "alert-existing"
    elif state.insights.recommend_alert:
        record = repository.create_alert(
            state.customer_id,
            reason=state.insights.alert_reason or "Insight generation recommended an alert.",
            description=state.insights.summary,
        )
        outcome = AlertOutcome(action="created", alert_id=record.alert_id, reason=record.reason)
        step = "alert-created"

        if snapshot_store is not None:
            try:
                # register_alert runs before assess_risk in the pipeline
                # (the alert-creation decision is independent of risk.level -
                # see design.md), so state.risk isn't populated yet here;
                # compute it locally, purely for the snapshot, without
                # changing the actual node ordering.
                snapshot_risk = assess_risk(state).risk
                snapshot_store.save_snapshot(
                    AlertSnapshot(
                        alert_id=record.alert_id,
                        customer_id=state.customer_id,
                        reason=record.reason,
                        description=record.description,
                        evidence=list(state.evidence),
                        risk=snapshot_risk,
                        insight_mode=_insight_mode(config),
                        insight_summary=state.insights.summary,
                        insight_key_observations=list(state.insights.key_observations),
                        alert_reason=state.insights.alert_reason,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to persist alert snapshot for %s: %s", record.alert_id, exc)
    else:
        outcome = AlertOutcome(action="none")
        step = "alert-not-required"

    logger.info("Alert outcome for customer %s: %s", state.customer_id, outcome.action)
    return replace(state, alert_outcome=outcome, workflow_steps=[*state.workflow_steps, step])


def assess_risk(state: TriageState) -> TriageState:
    """Classify the retrieved evidence into an AML risk level.

    A "cycle", "structuring-fanout"/"structuring-fanin", or
    "alert-proximity" evidence item - all produced by dedicated Cypher
    graph-pattern queries in repository.py - is treated as high risk
    regardless of how much other evidence is present, since those are
    specific laundering typologies (or association with an already-flagged
    customer) rather than general connectedness.
    """
    typologies = sorted({item.kind for item in state.evidence if item.kind in HIGH_RISK_EVIDENCE_KINDS})

    if typologies:
        level = "high"
        rationale = "Structural graph pattern(s) detected: " + ", ".join(typologies) + "."
    elif state.evidence:
        level = "elevated"
        rationale = "Connected evidence was found but no high-risk structural pattern was detected."
    else:
        level = "low"
        rationale = "No connected evidence was found after exhausting the enrichment retry budget."

    risk = RiskAssessment(level=level, rationale=rationale, typologies=typologies)
    logger.info("Assessed risk level %s for customer %s", level, state.customer_id)
    return replace(
        state,
        risk=risk,
        requires_human_review=level == "high",
        workflow_steps=[*state.workflow_steps, f"risk-assessed-{level}"],
    )


def build_human_review_payload(state: TriageState) -> dict[str, Any]:
    return {
        "reason": "High-risk AML structural pattern detected; analyst confirmation is required.",
        "customer_id": state.customer_id,
        "risk_level": state.risk.level,
        "typologies": list(state.risk.typologies),
        "evidence_summary": state.evidence_summary,
    }


def apply_analyst_decision(state: TriageState, decision: str) -> TriageState:
    return replace(
        state,
        analyst_decision=decision,
        workflow_steps=[*state.workflow_steps, "analyst-reviewed"],
    )


def review_evidence(state: TriageState) -> TriageRecommendation:
    evidence_summary = state.evidence_summary or "No connected evidence was found in Neo4j."
    insights_summary = state.insights.summary or "No interpretive insights were generated."
    risk_note = f"Structural risk signal: {state.risk.rationale}" if state.risk.typologies else ""

    if state.risk.level == "high" and state.analyst_decision != "reject-escalation":
        disposition = "escalate"
        decision_note = (
            f"An analyst confirmed the escalation (decision: {state.analyst_decision})."
            if state.analyst_decision
            else "This disposition is awaiting analyst confirmation."
        )
        rationale = (
            f"Factual evidence: {evidence_summary} {risk_note} {decision_note} "
            f"Interpretive LLM insights: {insights_summary}"
        )
    elif state.risk.level == "high" and state.analyst_decision == "reject-escalation":
        disposition = "review"
        rationale = (
            f"Factual evidence: {evidence_summary} {risk_note} "
            "An analyst reviewed the automatic high-risk classification and downgraded it to "
            f"standard review. Interpretive LLM insights: {insights_summary}"
        )
    elif state.evidence:
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
        rationale=" ".join(rationale.split()),
        supporting_evidence=list(state.evidence),
    )
    logger.info("Generated recommendation %s for customer %s", disposition, state.customer_id)
    return recommendation


def finalize_state(state: TriageState, recommendation: TriageRecommendation) -> TriageState:
    return replace(
        state,
        recommendation=recommendation,
        investigation_status="completed",
        workflow_steps=[*state.workflow_steps, "reviewed", "completed"],
    )


def state_from_mapping(mapping: dict[str, Any]) -> TriageState:
    """Reconstruct a `TriageState` from a compiled LangGraph `invoke()` result.

    LangGraph always returns a plain dict of channel values (one per
    `TriageState` field) even though the graph was built with a dataclass
    state schema, plus a `__interrupt__` key while paused. Nested dataclass
    values (evidence items, insights, risk, recommendation, ...) survive the
    round trip unchanged, so this just filters to known fields and rebuilds
    the dataclass.
    """
    known_fields = TriageState.__dataclass_fields__
    return TriageState(**{key: value for key, value in mapping.items() if key in known_fields})


def build_triage_response(state: TriageState) -> dict[str, Any]:
    return {
        "customer_id": state.customer_id,
        "status": state.investigation_status,
        "workflow_steps": list(state.workflow_steps),
        "disposition": state.recommendation.disposition if state.recommendation else None,
        "rationale": state.recommendation.rationale if state.recommendation else None,
        "evidence_count": len(state.evidence),
        "evidence_summary": state.evidence_summary,
        "hop_radius": state.hop_radius,
        "enrichment_attempts": state.enrichment_attempts,
        "risk": {
            "level": state.risk.level,
            "rationale": state.risk.rationale,
            "typologies": list(state.risk.typologies),
        },
        "requires_human_review": state.requires_human_review,
        "analyst_decision": state.analyst_decision,
        "insights": {
            "status": state.insights.status,
            "summary": state.insights.summary,
            "key_observations": list(state.insights.key_observations),
            "error": state.insights.error,
            "recommend_alert": state.insights.recommend_alert,
        },
        "alert": {
            "action": state.alert_outcome.action,
            "alert_id": state.alert_outcome.alert_id,
            "reason": state.alert_outcome.reason,
        },
    }


def build_langgraph(
    repository: Neo4jAlertRepository,
    llm_adapter: LLMAdapter,
    config: AppConfig,
    snapshot_store: AlertSnapshotStore | None = None,
):
    """Compile the AML triage workflow as a LangGraph `StateGraph`.

    Unlike the linear `run_triage` function, this graph has real branching
    behavior a plain call chain cannot express on its own:

    - a bounded cycle (`enrich` <-> `widen_search`) that retries evidence
      retrieval with a wider Neo4j hop radius when nothing is found;
    - a conditional edge after risk assessment that only routes through
      `human_review` for high-risk structural patterns (cycles, fan-out/
      fan-in structuring, or proximity to an already-alerted customer);
    - a real pause/resume interrupt in `human_review`, backed by a
      checkpointer, so a high-risk triage run can stop and wait for an
      analyst decision instead of guessing or blocking a thread.
    """
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, StateGraph
        from langgraph.types import interrupt
    except Exception:  # pragma: no cover - optional dependency fallback
        return None

    graph = StateGraph(TriageState)

    def node_initialize(state: TriageState) -> TriageState:
        return initialize_state(state.customer_id, state.user_prompt)

    def node_enrich(state: TriageState) -> TriageState:
        return enrich_state(state, repository)

    def node_widen_search(state: TriageState) -> TriageState:
        return widen_search(state)

    def node_insights(state: TriageState) -> TriageState:
        return generate_insights(state, llm_adapter)

    def node_register_alert(state: TriageState) -> TriageState:
        return register_alert(state, repository, config, snapshot_store)

    def node_assess_risk(state: TriageState) -> TriageState:
        return assess_risk(state)

    def node_human_review(state: TriageState) -> TriageState:
        decision = interrupt(build_human_review_payload(state))
        return apply_analyst_decision(state, str(decision))

    def node_review(state: TriageState) -> TriageState:
        recommendation = review_evidence(state)
        return finalize_state(state, recommendation)

    def route_after_enrich(state: TriageState) -> str:
        return "widen_search" if should_widen_search(state, config) else "insights"

    def route_after_risk(state: TriageState) -> str:
        return "human_review" if state.requires_human_review else "review"

    graph.add_node("initialize", node_initialize)
    graph.add_node("enrich", node_enrich)
    graph.add_node("widen_search", node_widen_search)
    graph.add_node("insights", node_insights)
    graph.add_node("register_alert", node_register_alert)
    graph.add_node("assess_risk", node_assess_risk)
    graph.add_node("human_review", node_human_review)
    graph.add_node("review", node_review)

    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "enrich")
    graph.add_conditional_edges(
        "enrich",
        route_after_enrich,
        {"widen_search": "widen_search", "insights": "insights"},
    )
    graph.add_edge("widen_search", "enrich")
    graph.add_edge("insights", "register_alert")
    graph.add_edge("register_alert", "assess_risk")
    graph.add_conditional_edges(
        "assess_risk",
        route_after_risk,
        {"human_review": "human_review", "review": "review"},
    )
    graph.add_edge("human_review", "review")
    graph.add_edge("review", END)

    return graph.compile(checkpointer=MemorySaver())


def run_triage(
    customer_id: str,
    repository: Neo4jAlertRepository,
    llm_adapter: LLMAdapter,
    config: AppConfig,
    user_prompt: str = "",
    human_review_callback: Callable[[TriageState], str] | None = None,
    snapshot_store: AlertSnapshotStore | None = None,
) -> TriageState:
    """Run the same workflow as `build_langgraph`, but as a plain call chain.

    This is the offline/CLI-friendly counterpart to the compiled LangGraph:
    it retries enrichment with a bounded while-loop instead of a graph
    cycle, and resolves high-risk human review synchronously via
    `human_review_callback` instead of a real interrupt - a linear function
    chain has no way to pause and later resume mid-execution the way a
    checkpointed graph can. Without a callback, high-risk alerts are left
    with an explicit "pending-manual-review" decision rather than guessing.
    """
    state = initialize_state(customer_id, user_prompt=user_prompt)

    state = enrich_state(state, repository)
    while should_widen_search(state, config):
        state = widen_search(state)
        state = enrich_state(state, repository)

    state = generate_insights(state, llm_adapter)
    state = register_alert(state, repository, config, snapshot_store)
    state = assess_risk(state)

    if state.requires_human_review:
        decision = human_review_callback(state) if human_review_callback else "pending-manual-review"
        state = apply_analyst_decision(state, decision)

    recommendation = review_evidence(state)
    return finalize_state(state, recommendation)
