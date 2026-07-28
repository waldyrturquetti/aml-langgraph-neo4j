"""Tests specific to the compiled LangGraph path (build_langgraph).

These exercise behavior a plain function chain cannot express on its own:
the bounded enrich <-> widen_search cycle, conditional routing driven by
computed risk, and a real interrupt/resume pause for human review.
"""

from langgraph.types import Command

from aml_alert_triage.config import AppConfig
from aml_alert_triage.llm import InsightResponse
from aml_alert_triage.models import TriageState
from aml_alert_triage.repository import Neo4jAlertRepository
from aml_alert_triage.sample_data import SAMPLE_ALERTS
from aml_alert_triage.workflow import build_langgraph, state_from_mapping


class _StaticAdapter:
    def generate_insights(self, request):
        return InsightResponse(summary="Static insight.", key_observations=["Static observation."])


def _build_graph(config: AppConfig | None = None):
    config = config or AppConfig()
    repository = Neo4jAlertRepository.offline(config)
    graph = build_langgraph(repository, _StaticAdapter(), config)
    assert graph is not None, "LangGraph must be installed for these tests"
    return graph


def _invoke(graph, alert, thread_id: str, user_prompt: str = ""):
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(TriageState(alert=alert, user_prompt=user_prompt), config=config), config


def test_langgraph_runs_straight_through_for_ordinary_evidence() -> None:
    graph = _build_graph()
    alert = SAMPLE_ALERTS["alert-001"]

    result, _ = _invoke(graph, alert, thread_id="test-ordinary")

    assert "__interrupt__" not in result
    state = state_from_mapping(result)
    assert state.recommendation.disposition == "review"
    assert state.hop_radius == 1
    assert state.requires_human_review is False


def test_langgraph_widen_search_cycle_recovers_evidence() -> None:
    graph = _build_graph()
    alert = SAMPLE_ALERTS["alert-005"]

    result, _ = _invoke(graph, alert, thread_id="test-widen")

    assert "__interrupt__" not in result
    state = state_from_mapping(result)
    assert state.hop_radius == 2
    assert state.enrichment_attempts == 2
    assert len(state.evidence) > 1
    assert "widened-search-radius" in state.workflow_steps


def test_langgraph_retry_loop_terminates_without_evidence() -> None:
    config = AppConfig()
    graph = _build_graph(config)
    alert = SAMPLE_ALERTS["alert-002"]

    result, _ = _invoke(graph, alert, thread_id="test-no-evidence")

    assert "__interrupt__" not in result
    state = state_from_mapping(result)
    assert not state.evidence
    assert state.hop_radius == config.neo4j_max_hops
    assert state.enrichment_attempts == config.max_enrichment_attempts
    assert state.recommendation.disposition == "monitor"


def test_langgraph_pauses_and_resumes_confirming_escalation() -> None:
    graph = _build_graph()
    alert = SAMPLE_ALERTS["alert-003"]

    paused, thread_config = _invoke(graph, alert, thread_id="test-cycle-confirm")

    assert "__interrupt__" in paused
    interrupt_payload = paused["__interrupt__"][0].value
    assert interrupt_payload["risk_level"] == "high"
    assert interrupt_payload["typologies"] == ["cycle"]
    assert interrupt_payload["alert_id"] == alert.alert_id

    resumed = graph.invoke(Command(resume="confirm-escalation"), config=thread_config)

    assert "__interrupt__" not in resumed
    state = state_from_mapping(resumed)
    assert state.analyst_decision == "confirm-escalation"
    assert state.recommendation.disposition == "escalate"


def test_langgraph_pauses_and_resumes_rejecting_escalation() -> None:
    graph = _build_graph()
    alert = SAMPLE_ALERTS["alert-004"]

    paused, thread_config = _invoke(graph, alert, thread_id="test-fanout-reject")
    assert "__interrupt__" in paused

    resumed = graph.invoke(Command(resume="reject-escalation"), config=thread_config)

    assert "__interrupt__" not in resumed
    state = state_from_mapping(resumed)
    assert state.analyst_decision == "reject-escalation"
    assert state.recommendation.disposition == "review"


def test_langgraph_pauses_for_structuring_fanin() -> None:
    graph = _build_graph()
    alert = SAMPLE_ALERTS["alert-006"]

    paused, _ = _invoke(graph, alert, thread_id="test-fanin")

    assert "__interrupt__" in paused
    interrupt_payload = paused["__interrupt__"][0].value
    assert interrupt_payload["typologies"] == ["structuring-fanin"]
