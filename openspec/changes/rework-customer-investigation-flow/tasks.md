## 1. Data Model

- [ ] 1.1 Remove `AlertPayload` from `models.py`; add `AlertRecord` (`alert_id`, `reason`, `description`) and `AlertOutcome` (`action`, `alert_id`, `reason`).
- [ ] 1.2 Move `HIGH_RISK_EVIDENCE_KINDS` from `workflow.py` to `models.py`, extended with `"alert-proximity"` alongside `"cycle"`, `"structuring-fanout"`, `"structuring-fanin"`; update `workflow.py`'s import.
- [ ] 1.3 Replace `TriageState.alert: AlertPayload` with `customer_id: str`; add `existing_alert: AlertRecord | None` and `alert_outcome: AlertOutcome`.
- [ ] 1.4 Update `InsightResult` with `recommend_alert: bool = False` and `alert_reason: str = ""`.

## 2. Dataset Generation

- [ ] 2.1 Write `scripts/generate_dataset.py`: deterministic fixed-seed generator producing 30 organic customers (self-validated acyclic/capped fan-out, as today) and 20 suspicious customers split across cycle, structuring fan-out, and structuring fan-in typologies.
- [ ] 2.2 Pick and hardcode exact per-typology counts for the 20 suspicious customers in the generator (documented in a code comment), and select exactly 2 of them to receive a pre-registered alert.
- [ ] 2.3 Generate `ALERTS: list[AlertSeed]` (alert_id, customer_id, reason, description) for the 2 pre-registered cases and emit it into `src/aml_alert_triage/graph_dataset.py` alongside `CUSTOMERS`/`ACCOUNTS`/`TRANSACTIONS`.
- [ ] 2.4 Emit the matching `data/neo4j/seed.cypher`, including `MERGE (:Alert {...})-[:TARGETS]->(:Customer {...})` only for the 2 pre-registered cases.
- [ ] 2.5 Run the generator and commit the regenerated `graph_dataset.py` and `seed.cypher`.

## 3. Generalized Hop Traversal

- [ ] 3.1 In `graph_engine.py`, replace `direct_transactions`/`second_hop_transactions` with a frontier-expansion helper that walks up to `max_hop` hops over the in-memory dataset, tracking visited accounts.
- [ ] 3.2 Update `evidence_for_customer` to use the new helper; verify hop-1 and hop-2 output is unchanged from today for existing scenarios.
- [ ] 3.3 In `repository.py`, replace `_fetch_direct_evidence`/`_fetch_second_hop_evidence` with a `_fetch_hop_evidence` helper that issues one simple Cypher query per hop against the current frontier, bounded by `hop_radius`.
- [ ] 3.4 Confirm `_fetch_cycle_evidence`/`_fetch_structuring_evidence` and their `cycle_max_hops`/fan-in/fan-out thresholds are untouched by this change.

## 4. Alert-Proximity Detection

- [ ] 4.1 Add `alert_proximity_max_hops: int = 3` to `AppConfig`, read from `AML_ALERT_PROXIMITY_MAX_HOPS`, clamped the same way `cycle_max_hops` is (literal-interpolated into the variable-length Cypher pattern, never a bind parameter).
- [ ] 4.2 In `repository.py`, add a targeted `_fetch_alert_proximity_evidence(customer_id)` query: `MATCH (customer {customer_id})-[:OWNS]->(account) MATCH path = (account)-[:TRANSFERRED_TO*1..N]-(other_account) MATCH (other_customer)-[:OWNS]->(other_account) MATCH (a:Alert)-[:TARGETS]->(other_customer) WHERE other_customer.customer_id <> $customer_id WITH other_customer, a, min(length(path)) AS hops RETURN ... ORDER BY hops LIMIT $limit`; call it from `_fetch_evidence_from_neo4j` alongside the cycle/structuring queries.
- [ ] 4.3 Produce one `EvidenceItem(kind="alert-proximity", subject=customer_id, details="Connected within {hops} hop(s) to customer {linked_customer_id}, who already has alert {linked_alert_id}.", source="neo4j")` per linked customer found (capped like the existing fan-pattern sample list).
- [ ] 4.4 In `graph_engine.py`, add the offline equivalent: a BFS from the customer's accounts up to `alert_proximity_max_hops` checking membership against the set of currently-alerted customer ids.
- [ ] 4.5 Give the offline `Neo4jAlertRepository` (force_offline mode) a process-local "alerted customer ids" set, seeded from `ALERTS` and updated whenever the offline path's `create_alert` runs, so proximity detection sees alerts created earlier in the same process — mirroring how live Neo4j naturally accumulates `Alert` nodes across investigations.
- [ ] 4.6 Confirm `assess_risk` (unchanged code, now iterating a 4-member `HIGH_RISK_EVIDENCE_KINDS`) classifies a customer with only `alert-proximity` evidence as `high` risk, same as cycle/structuring.

## 5. Alert Lookup and Registration (Repository)

- [ ] 5.1 Add `Neo4jAlertRepository.find_alert_for_customer(customer_id) -> AlertRecord | None`, querying `(a:Alert)-[:TARGETS]->(c {customer_id})`, with an offline fallback that looks up the new `ALERTS` seed list.
- [ ] 5.2 Add `Neo4jAlertRepository.create_alert(customer_id, reason, description) -> AlertRecord`, using a deterministic id (`alert-auto-{customer_id}`) and a `MERGE`-based idempotent write; offline mode tracks created alerts process-locally without persisting (and updates the alerted-customer-ids set from task 4.5).

## 6. Workflow

- [ ] 6.1 Update `initialize_state(customer_id, user_prompt)` to build `TriageState` from a customer id instead of an `AlertPayload`.
- [ ] 6.2 Update `enrich_state` to also call `find_alert_for_customer` and populate `state.existing_alert`.
- [ ] 6.3 Update `generate_insights` to build the new `InsightRequest` shape (customer_id + existing_alert, no `alert`) and to persist `recommend_alert`/`alert_reason` into `state.insights`.
- [ ] 6.4 Add `register_alert(state, repository) -> TriageState`: resolve `alert_outcome` per the existing/created/none decision table; call `repository.create_alert` only when warranted.
- [ ] 6.5 Insert `register_alert` into `run_triage` (linear) between `generate_insights` and `assess_risk`.
- [ ] 6.6 Insert a `register_alert` node into `build_langgraph` on the same edge (`insights -> register_alert -> assess_risk`); update the mermaid diagram in the README.
- [ ] 6.7 Update `build_triage_response` to include an `"alert"` section (`action`, `alert_id`, `reason`).

## 7. LLM Adapters

- [ ] 7.1 Update `INSIGHT_RESPONSE_SCHEMA`, `InsightRequest`, and `InsightResponse` in `llm.py` with `recommend_alert`/`alert_reason` (request) and matching response fields; replace `InsightRequest.alert` with `customer_id`/`existing_alert`.
- [ ] 7.2 Update `compose_insight_prompt` to describe the customer id and any existing-alert context instead of `AlertPayload` fields, including `alert-proximity` evidence text when present.
- [ ] 7.3 Update `RuleBasedLLMAdapter` to compute `recommend_alert` from `HIGH_RISK_EVIDENCE_KINDS` membership in the supplied evidence, with a templated `alert_reason`.
- [ ] 7.4 Extend `ANTHROPIC_SYSTEM_PROMPT` (shared by both real-LLM adapters) with the evidence-grounding instruction for alert recommendations.
- [ ] 7.5 Add `DEFAULT_OPENAI_MODEL = "gpt-5"` and an `OpenAILLMAdapter` dataclass (lazy `openai` client, `reasoning_effort`, Chat Completions + `response_format` json_schema), mirroring `AnthropicLLMAdapter`.
- [ ] 7.6 Update `create_llm_adapter`: `llm_enabled=False` returns `RuleBasedLLMAdapter` directly; `llm_enabled=True` branches on `llm_provider` (`openai` -> `OpenAILLMAdapter` with default model/reasoning-effort resolution, else `AnthropicLLMAdapter`).
- [ ] 7.7 Delete `DisabledLLMAdapter` and its test.

## 8. Configuration

- [ ] 8.1 Add `llm_reasoning_effort: str | None` to `AppConfig`, read from `AML_ALERT_LLM_REASONING_EFFORT`.
- [ ] 8.2 Add `openai` to the `llm` optional dependency extra in `pyproject.toml`.
- [ ] 8.3 Update `.env.example`: remove any alert-specific vars no longer used, add `OPENAI_API_KEY`, `AML_ALERT_LLM_REASONING_EFFORT`, `AML_ALERT_PROXIMITY_MAX_HOPS`, and document `AML_ALERT_LLM_PROVIDER=openai|anthropic`.

## 9. CLI

- [ ] 9.1 Remove `sample_data.py` and the `--alert-id` argument from `main.py`.
- [ ] 9.2 Add a required `--customer-id` argument (or a documented organic-customer default for a zero-config demo run).
- [ ] 9.3 Update `_run_linear`/`_run_langgraph` and `--thread-id` default to use `customer_id` instead of `alert.alert_id`.

## 10. Alert Snapshot Store (DynamoDB)

- [ ] 10.1 Add `dynamodb-local` and `dynamodb-admin` services to `docker-compose.yml` (ports 8000/8001, shared local db file, admin pointed at the local endpoint with dummy credentials).
- [ ] 10.2 Add `dynamodb_endpoint_url`, `dynamodb_table_name`, `dynamodb_region` to `AppConfig`/`.env.example`; add `boto3` to `pyproject.toml` dependencies.
- [ ] 10.3 Add `snapshot_store.py`: `AlertSnapshot` dataclass, `AlertSnapshotStore` with lazy `boto3` client, `ensure_table`, `save_snapshot`, `get_snapshot`.
- [ ] 10.4 Wire `AlertSnapshotStore` into `register_alert` (both `run_triage` and `build_langgraph`): on newly-created alerts, build an `AlertSnapshot` (including `insight_mode` = `"static"` or the active provider name) and save it; log and continue on failure without raising.
- [ ] 10.5 Extend `scripts/generate_dataset.py` to emit `data/dynamodb/seed.json` with snapshots for the 2 pre-registered alerts, derived with the same rule-based evidence logic used for the rest of the generator.
- [ ] 10.6 Add `--check-dynamodb` (verify connectivity, `ensure_table`) and `--seed-dynamodb` (load `data/dynamodb/seed.json`) flags to `main.py`, mirroring `--check-neo4j`/`--seed-neo4j`.

## 11. Report Generation

- [ ] 11.1 Add `report.py`: `render_alert_report(snapshot) -> str` (Markdown: title, alert metadata, single insight-analysis section labeled by `insight_mode`, evidence/relationship table) and `generate_alert_report(alert_id, snapshot_store, output_path=None) -> Path`.
- [ ] 11.2 Add `--report-alert-id <id>` and optional `--report-output <path>` to `main.py`; default output `reports/<alert_id>.md`, creating the directory if needed.
- [ ] 11.3 Raise a clear, specific error when no snapshot exists for the requested alert id (no live-data fallback).

## 12. Documentation

- [ ] 12.1 Rewrite the README's dataset section: 50 customers (30 organic / 20 suspicious across cycle/fan-out/fan-in), 2 pre-registered alerts, and how alert write-back works.
- [ ] 12.2 Replace the `--alert-id` scenario table with a `--customer-id` example table (at least one organic customer and one undiscovered-suspicious customer).
- [ ] 12.3 Update the mermaid workflow diagram and node table to include `register_alert`.
- [ ] 12.4 Update the LLM Insight Generation section: single `AML_ALERT_LLM_ENABLED` toggle semantics, `AML_ALERT_LLM_PROVIDER` (openai/anthropic), reasoning effort default, and a Cypher snippet to verify a created alert.
- [ ] 12.5 Document the DynamoDB services (`docker compose up -d`, `dynamodb-admin` at `http://localhost:8001`), `--check-dynamodb`/`--seed-dynamodb`, and `--report-alert-id` usage with an example.
- [ ] 12.6 Document `alert-proximity` evidence and `AML_ALERT_PROXIMITY_MAX_HOPS` alongside the other risk typologies.

## 13. Testing

- [ ] 13.1 Update `tests/test_llm.py` for the new schema fields, the `RuleBasedLLMAdapter` alert-recommendation logic, `create_llm_adapter`'s enabled/disabled routing (rule-based when disabled), and add `OpenAILLMAdapter` tests mirroring the Anthropic ones (request shape, response parsing, provider errors, malformed response).
- [ ] 13.2 Update `tests/test_workflow.py` (or equivalent) for `customer_id`-based initialization, the new `register_alert` step (existing/created/none paths), and idempotency (second investigation of the same customer does not duplicate).
- [ ] 13.3 Update `tests/test_repository.py`/offline-engine tests for `find_alert_for_customer`, `create_alert`, and the generalized N-hop evidence retrieval (hop 1, 2, and 3+ parity between offline and live-query logic where feasible).
- [ ] 13.4 Add tests for `alert-proximity` detection: a customer 2+ hops from an already-alerted customer is classified `high` risk and evidence explains the link, both offline and (where a live Neo4j instance is available) live.
- [ ] 13.5 Add `tests/test_snapshot_store.py` and `tests/test_report.py` (fake/injected DynamoDB client, snapshot round-trip, Markdown rendering, missing-snapshot error path).
- [ ] 13.6 Run the full test suite (`pytest`) and confirm all tests pass.

## 14. Manual Validation

- [ ] 14.1 Reseed Neo4j (`--seed-neo4j`) with the regenerated `seed.cypher` and confirm 50 `Customer` nodes and 2 `Alert` nodes via Neo4j Browser or `cypher-shell`.
- [ ] 14.2 Run `--seed-dynamodb` and confirm the 2 seeded snapshots are visible via `dynamodb-admin` (`http://localhost:8001`).
- [ ] 14.3 Run `--customer-id` against an organic customer and confirm no alert is created.
- [ ] 14.4 Run `--customer-id` against an undiscovered suspicious customer with `AML_ALERT_LLM_ENABLED=true` and `AML_ALERT_LLM_PROVIDER=openai` (or `anthropic`) and confirm an `Alert` node is created in Neo4j, verifiable via `MATCH (a:Alert)-[:TARGETS]->(c:Customer {customer_id: $id}) RETURN a`.
- [ ] 14.5 Re-run the same `--customer-id` and confirm the workflow reports the existing alert instead of creating a duplicate.
- [ ] 14.6 Investigate a customer known to transact (2+ hops) with an already-alerted customer and confirm `alert-proximity` evidence appears and risk is `high`.
- [ ] 14.7 Run `--report-alert-id` for a newly created alert and confirm `reports/<alert_id>.md` contains the evidence/relationships and the insight analysis that triggered it.
