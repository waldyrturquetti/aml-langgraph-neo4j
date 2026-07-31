"""Tests specific to the compiled LangGraph path (build_langgraph).

These exercise behavior a plain function chain cannot express on its own:
the bounded enrich <-> widen_search cycle, conditional routing driven by
computed risk, and a real interrupt/resume pause for human review.
"""

from langgraph.types import Command

from aml_alert_triage.config import AppConfig
from aml_alert_triage.llm import InsightResponse, RuleBasedLLMAdapter
from aml_alert_triage.models import TriageState
from aml_alert_triage.repository import Neo4jAlertRepository
from aml_alert_triage.workflow import build_langgraph, state_from_mapping

ORDINARY_CUSTOMER = "cust-101"
THIN_FILE_CUSTOMER = "cust-100"
UNKNOWN_CUSTOMER = "cust-999"
CYCLE_CUSTOMER = "cust-200"
FANOUT_CUSTOMER = "cust-208"
FANIN_CUSTOMER = "cust-214"


class _StaticAdapter:
    def generate_insights(self, request):
        return InsightResponse(summary="Static insight.", key_observations=["Static observation."])


def _build_graph(config: AppConfig | None = None):
    config = config or AppConfig()
    repository = Neo4jAlertRepository.offline(config)
    graph = build_langgraph(repository, _StaticAdapter(), config)
    assert graph is not None, "LangGraph must be installed for these tests"
    return graph


def _invoke(graph, customer_id: str, thread_id: str, user_prompt: str = ""):
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(TriageState(customer_id=customer_id, user_prompt=user_prompt), config=config), config


def test_langgraph_runs_straight_through_for_ordinary_evidence() -> None:
    graph = _build_graph()

    result, _ = _invoke(graph, ORDINARY_CUSTOMER, thread_id="test-ordinary")

    assert "__interrupt__" not in result
    state = state_from_mapping(result)
    assert state.recommendation.disposition == "review"
    assert state.hop_radius == 1
    assert state.requires_human_review is False


def test_langgraph_widen_search_cycle_recovers_evidence() -> None:
    graph = _build_graph()

    result, _ = _invoke(graph, THIN_FILE_CUSTOMER, thread_id="test-widen")

    assert "__interrupt__" not in result
    state = state_from_mapping(result)
    assert state.hop_radius == 2
    assert state.enrichment_attempts == 2
    assert len(state.evidence) > 1
    assert "widened-search-radius" in state.workflow_steps


def test_langgraph_retry_loop_terminates_without_evidence() -> None:
    config = AppConfig()
    graph = _build_graph(config)

    result, _ = _invoke(graph, UNKNOWN_CUSTOMER, thread_id="test-no-evidence")

    assert "__interrupt__" not in result
    state = state_from_mapping(result)
    assert not state.evidence
    assert state.hop_radius == config.neo4j_max_hops
    assert state.enrichment_attempts == config.max_enrichment_attempts
    assert state.recommendation.disposition == "monitor"


def test_langgraph_pauses_and_resumes_confirming_escalation() -> None:
    graph = _build_graph()

    paused, thread_config = _invoke(graph, CYCLE_CUSTOMER, thread_id="test-cycle-confirm")

    assert "__interrupt__" in paused
    interrupt_payload = paused["__interrupt__"][0].value
    assert interrupt_payload["risk_level"] == "high"
    assert "cycle" in interrupt_payload["typologies"]
    assert interrupt_payload["customer_id"] == CYCLE_CUSTOMER

    resumed = graph.invoke(Command(resume="confirm-escalation"), config=thread_config)

    assert "__interrupt__" not in resumed
    state = state_from_mapping(resumed)
    assert state.analyst_decision == "confirm-escalation"
    assert state.recommendation.disposition == "escalate"


def test_langgraph_pauses_and_resumes_rejecting_escalation() -> None:
    graph = _build_graph()

    paused, thread_config = _invoke(graph, FANOUT_CUSTOMER, thread_id="test-fanout-reject")
    assert "__interrupt__" in paused

    resumed = graph.invoke(Command(resume="reject-escalation"), config=thread_config)

    assert "__interrupt__" not in resumed
    state = state_from_mapping(resumed)
    assert state.analyst_decision == "reject-escalation"
    assert state.recommendation.disposition == "review"


def test_langgraph_pauses_for_structuring_fanin() -> None:
    graph = _build_graph()

    paused, _ = _invoke(graph, FANIN_CUSTOMER, thread_id="test-fanin")

    assert "__interrupt__" in paused
    interrupt_payload = paused["__interrupt__"][0].value
    assert "structuring-fanin" in interrupt_payload["typologies"]


def test_langgraph_creates_alert_for_undiscovered_high_risk_customer() -> None:
    config = AppConfig()
    repository = Neo4jAlertRepository.offline(config)
    # Uses the real rule-based adapter (not the dummy _StaticAdapter, which
    # never recommends an alert) so register_alert has something to act on.
    graph = build_langgraph(repository, RuleBasedLLMAdapter(provider="rule-based", model="x"), config)
    assert graph is not None

    result, _ = _invoke(graph, FANIN_CUSTOMER, thread_id="test-fanin-alert")

    assert "__interrupt__" in result
    # register_alert runs before assess_risk/human_review in the graph, so
    # the alert is already created by the time the interrupt fires.
    created = repository.find_alert_for_customer(FANIN_CUSTOMER)
    assert created is not None
    assert created.alert_id == f"alert-auto-{FANIN_CUSTOMER}"
