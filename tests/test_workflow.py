from aml_alert_triage.config import AppConfig
from aml_alert_triage.llm import InsightResponse
from aml_alert_triage.repository import Neo4jAlertRepository
from aml_alert_triage.workflow import (
    assess_risk,
    build_triage_response,
    enrich_state,
    finalize_state,
    generate_insights,
    initialize_state,
    register_alert,
    review_evidence,
    run_triage,
    should_widen_search,
    widen_search,
)

# cust-100 has exactly 1 direct transaction (below min_evidence_for_conclusion),
# so it exercises the enrich<->widen_search retry loop.
THIN_FILE_CUSTOMER = "cust-100"
# Ordinary organic customer with several direct transactions and no
# structural pattern.
ORDINARY_CUSTOMER = "cust-101"
# Not present in the dataset at all - genuinely zero evidence at any hop.
UNKNOWN_CUSTOMER = "cust-999"
CYCLE_CUSTOMER = "cust-200"  # pre-registered alert
FANOUT_CUSTOMER = "cust-208"  # undiscovered
FANIN_CUSTOMER = "cust-214"  # undiscovered
PROXIMITY_CUSTOMER = "cust-129"  # 2 hops from cust-200 (pre-registered alert)


class _StaticAdapter:
    def generate_insights(self, request):
        return InsightResponse(
            summary="Linked activity suggests moderate escalation risk.",
            key_observations=["Observed repeated linked transactions."],
        )


class _RecommendingAdapter:
    def generate_insights(self, request):
        return InsightResponse(
            summary="High risk pattern found.",
            key_observations=["Structural pattern detected."],
            recommend_alert=True,
            alert_reason="Structural pattern detected.",
        )


class _FailingAdapter:
    def generate_insights(self, request):
        raise RuntimeError("provider timeout")


def _run_full_enrichment(customer_id, repository, config):
    state = enrich_state(initialize_state(customer_id), repository)
    while should_widen_search(state, config):
        state = widen_search(state)
        state = enrich_state(state, repository)
    return state


def test_initialize_state_records_customer_metadata() -> None:
    state = initialize_state(THIN_FILE_CUSTOMER, user_prompt="Explain suspicious links")

    assert state.customer_id == THIN_FILE_CUSTOMER
    assert state.investigation_status == "initialized"
    assert state.metadata["customer_id"] == THIN_FILE_CUSTOMER
    assert state.user_prompt == "Explain suspicious links"
    assert state.hop_radius == 1
    assert state.enrichment_attempts == 0


def test_enrichment_loads_fictional_graph_evidence() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(ORDINARY_CUSTOMER), repository)

    assert state.investigation_status == "enriched"
    assert len(state.evidence) > 0
    assert state.enrichment_attempts == 1
    assert state.workflow_steps[-1] == "enriched-hop-1"


def test_enrichment_loads_existing_alert_for_pre_registered_customer() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(CYCLE_CUSTOMER), repository)

    assert state.existing_alert is not None
    assert state.existing_alert.alert_id == "alert-auto-cust-200"


def test_enrichment_has_no_existing_alert_for_undiscovered_customer() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(FANOUT_CUSTOMER), repository)

    assert state.existing_alert is None


def test_review_generates_structured_recommendation() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(ORDINARY_CUSTOMER), repository)
    state = generate_insights(state, _StaticAdapter())
    recommendation = review_evidence(state)

    assert recommendation.disposition == "review"
    assert recommendation.supporting_evidence
    assert "Factual evidence:" in recommendation.rationale
    assert "Interpretive LLM insights:" in recommendation.rationale


def test_finalize_state_marks_workflow_complete() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(UNKNOWN_CUSTOMER), repository)
    state = generate_insights(state, _StaticAdapter())
    final_state = finalize_state(state, review_evidence(state))

    assert final_state.investigation_status == "completed"
    assert final_state.recommendation is not None
    assert final_state.workflow_steps[-1] == "completed"


def test_run_triage_returns_deterministic_structure() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()

    adapter = _StaticAdapter()
    first = run_triage(
        ORDINARY_CUSTOMER, repository, llm_adapter=adapter, config=config, user_prompt="Focus on connected entities"
    )
    second = run_triage(
        ORDINARY_CUSTOMER, repository, llm_adapter=adapter, config=config, user_prompt="Focus on connected entities"
    )

    assert first.recommendation is not None
    assert second.recommendation is not None
    assert first.recommendation.disposition == second.recommendation.disposition
    assert first.recommendation.rationale == second.recommendation.rationale
    assert first.workflow_steps == second.workflow_steps


def test_insight_generation_fallback_keeps_workflow_safe() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(UNKNOWN_CUSTOMER), repository)

    state = generate_insights(state, _FailingAdapter())
    recommendation = review_evidence(state)
    final_state = finalize_state(state, recommendation)

    assert state.insights.status == "fallback"
    assert state.insights.error is not None
    assert state.insights.recommend_alert is False
    assert final_state.investigation_status == "completed"


def test_build_triage_response_includes_insight_and_alert_fields() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = run_triage(
        ORDINARY_CUSTOMER, repository, llm_adapter=_StaticAdapter(), config=AppConfig(), user_prompt="Summarize the risk"
    )

    payload = build_triage_response(state)

    assert payload["customer_id"] == ORDINARY_CUSTOMER
    assert payload["workflow_steps"][-1] == "completed"
    assert payload["insights"]["status"] == "generated"
    assert isinstance(payload["insights"]["key_observations"], list)
    assert payload["risk"]["level"] == "elevated"
    assert payload["requires_human_review"] is False
    assert payload["analyst_decision"] is None
    assert payload["alert"]["action"] == "none"


# --- Widen-search retry loop -------------------------------------------------


def test_should_widen_search_true_when_evidence_empty_and_budget_remains() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()
    state = enrich_state(initialize_state(UNKNOWN_CUSTOMER), repository)

    assert not state.evidence
    assert should_widen_search(state, config) is True


def test_widen_search_increments_hop_radius_and_logs_step() -> None:
    state = initialize_state(UNKNOWN_CUSTOMER)

    widened = widen_search(state)

    assert widened.hop_radius == 2
    assert widened.workflow_steps[-1] == "widened-search-radius"


def test_retry_loop_recovers_evidence_at_wider_hop_radius() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()

    state = _run_full_enrichment(THIN_FILE_CUSTOMER, repository, config)

    assert state.hop_radius == 2
    assert state.enrichment_attempts == 2
    assert len(state.evidence) > 1


def test_retry_loop_terminates_when_no_evidence_exists_anywhere() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()

    state = _run_full_enrichment(UNKNOWN_CUSTOMER, repository, config)

    assert not state.evidence
    assert state.enrichment_attempts == config.max_enrichment_attempts
    assert state.hop_radius == config.neo4j_max_hops
    assert should_widen_search(state, config) is False


# --- Risk assessment (cycle / structuring / alert-proximity typologies) -----


def test_assess_risk_flags_cycle_as_high_risk() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(CYCLE_CUSTOMER), repository)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "high"
    assert "cycle" in risk_state.risk.typologies
    assert risk_state.requires_human_review is True


def test_assess_risk_flags_structuring_fanout_as_high_risk() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(FANOUT_CUSTOMER), repository)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "high"
    assert "structuring-fanout" in risk_state.risk.typologies
    assert risk_state.requires_human_review is True


def test_assess_risk_flags_structuring_fanin_as_high_risk() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(FANIN_CUSTOMER), repository)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "high"
    assert "structuring-fanin" in risk_state.risk.typologies
    assert risk_state.requires_human_review is True


def test_assess_risk_flags_alert_proximity_as_high_risk() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(PROXIMITY_CUSTOMER), repository)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "high"
    assert "alert-proximity" in risk_state.risk.typologies
    assert any(item.kind == "alert-proximity" and "cust-200" in item.details for item in state.evidence)
    assert risk_state.requires_human_review is True


def test_assess_risk_is_elevated_for_ordinary_evidence() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(ORDINARY_CUSTOMER), repository)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "elevated"
    assert risk_state.risk.typologies == []
    assert risk_state.requires_human_review is False


def test_assess_risk_is_low_when_no_evidence_after_retries() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()
    state = _run_full_enrichment(UNKNOWN_CUSTOMER, repository, config)

    risk_state = assess_risk(state)

    assert risk_state.risk.level == "low"
    assert risk_state.requires_human_review is False


# --- Alert registration (idempotent write-back) ------------------------------


def test_register_alert_creates_new_alert_when_recommended_and_none_exists() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(FANIN_CUSTOMER), repository)
    state = generate_insights(state, _RecommendingAdapter())

    result = register_alert(state, repository, AppConfig())

    assert result.alert_outcome.action == "created"
    assert result.alert_outcome.alert_id == f"alert-auto-{FANIN_CUSTOMER}"
    assert "alert-created" in result.workflow_steps
    # The repository now reports this customer as having an alert.
    assert repository.find_alert_for_customer(FANIN_CUSTOMER) is not None


def test_register_alert_reports_existing_alert_without_duplicating() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(CYCLE_CUSTOMER), repository)
    state = generate_insights(state, _RecommendingAdapter())

    result = register_alert(state, repository, AppConfig())

    assert result.alert_outcome.action == "existing"
    assert result.alert_outcome.alert_id == "alert-auto-cust-200"


def test_register_alert_does_nothing_when_not_recommended() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    state = enrich_state(initialize_state(ORDINARY_CUSTOMER), repository)
    state = generate_insights(state, _StaticAdapter())

    result = register_alert(state, repository, AppConfig())

    assert result.alert_outcome.action == "none"
    assert repository.find_alert_for_customer(ORDINARY_CUSTOMER) is None


def test_run_triage_second_investigation_does_not_duplicate_alert() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())
    config = AppConfig()

    first = run_triage(FANIN_CUSTOMER, repository, llm_adapter=_RecommendingAdapter(), config=config)
    second = run_triage(FANIN_CUSTOMER, repository, llm_adapter=_RecommendingAdapter(), config=config)

    assert first.alert_outcome.action == "created"
    assert second.alert_outcome.action == "existing"
    assert second.alert_outcome.alert_id == first.alert_outcome.alert_id


# --- Human-review escalation path (linear run_triage) ------------------------


def test_run_triage_escalates_high_risk_without_callback() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())

    state = run_triage(CYCLE_CUSTOMER, repository, llm_adapter=_StaticAdapter(), config=AppConfig())

    assert state.requires_human_review is True
    assert state.analyst_decision == "pending-manual-review"
    assert state.recommendation.disposition == "escalate"
    assert "analyst-reviewed" in state.workflow_steps


def test_run_triage_confirms_escalation_via_callback() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())

    state = run_triage(
        CYCLE_CUSTOMER,
        repository,
        llm_adapter=_StaticAdapter(),
        config=AppConfig(),
        human_review_callback=lambda triage_state: "confirm-escalation",
    )

    assert state.analyst_decision == "confirm-escalation"
    assert state.recommendation.disposition == "escalate"
    assert "confirmed the escalation" in state.recommendation.rationale


def test_run_triage_downgrades_on_analyst_rejection() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())

    state = run_triage(
        FANOUT_CUSTOMER,
        repository,
        llm_adapter=_StaticAdapter(),
        config=AppConfig(),
        human_review_callback=lambda triage_state: "reject-escalation",
    )

    assert state.analyst_decision == "reject-escalation"
    assert state.recommendation.disposition == "review"
    assert "downgraded" in state.recommendation.rationale


def test_run_triage_does_not_trigger_review_for_ordinary_evidence() -> None:
    repository = Neo4jAlertRepository.offline(AppConfig())

    state = run_triage(ORDINARY_CUSTOMER, repository, llm_adapter=_StaticAdapter(), config=AppConfig())

    assert state.requires_human_review is False
    assert state.analyst_decision is None
    assert "analyst-reviewed" not in state.workflow_steps
