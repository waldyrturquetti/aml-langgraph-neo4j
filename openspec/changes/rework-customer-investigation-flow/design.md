## Context

Today's flow: `main.py` picks an `AlertPayload` out of the hardcoded `SAMPLE_ALERTS` dict by `--alert-id`, and `workflow.py`'s `TriageState.alert` carries it through `initialize -> enrich -> insights -> assess_risk -> [human_review] -> review`. `enrich_state` queries Neo4j (or the offline `graph_engine.py` mirror) for evidence rooted at `alert.customer_id`; nothing ever reads the `Alert` nodes seeded into Neo4j. `assess_risk` classifies risk from evidence *kind* alone (`cycle`/`structuring-fanout`/`structuring-fanin` -> `high`). `generate_insights` calls whichever `LLMAdapter` `create_llm_adapter` picked (`DisabledLLMAdapter`, `RuleBasedLLMAdapter`, or `AnthropicLLMAdapter`) and never touches Neo4j.

This change moves the entry point to `customer_id`, adds a Neo4j write-back step, and expands the dataset. It also folds in the already-designed `OpenAILLMAdapter` (previously its own change) since it lands in the same `llm.py` file and the same `create_llm_adapter` branch logic.

## Goals / Non-Goals

**Goals:**
- Investigation starts from a customer, not a pre-labeled alert; the system decides whether to flag one, mirroring a real AML analyst workflow.
- The dataset is graph-native: people, accounts, transactions are the source of truth; `Alert` nodes are an output of investigation, with a small number pre-seeded to represent "already known" cases.
- Alert creation is idempotent per customer (one alert per customer, no duplicates across repeated investigations).
- `AML_ALERT_LLM_ENABLED=false` still produces a real, evidence-grounded (if templated) verdict — not a "sorry, unavailable" placeholder.
- `openai` becomes a first-class provider alongside `anthropic`, with optional reasoning effort.

**Non-Goals:**
- No alert *lifecycle* (open/closed/resolved status, multiple alerts per customer over time) — this change adds creation only, matching the "idempotent, one alert per customer" decision.
- No UI/API layer — CLI-only, as today.
- No change to `assess_risk`'s structural risk classification or the human-review interrupt mechanics; `register_alert` is an independent, additive step driven by the insight response, not by `risk.level`.
- No guardrail beyond prompt instructions to stop a real LLM from recommending an alert ungrounded in evidence — acceptable for a study project; documented as a risk below.

## Decisions

### 1. `TriageState` moves from `alert: AlertPayload` to `customer_id: str`

`AlertPayload` (`alert_id`, `customer_id`, `alert_type`, `amount`, `currency`, `description`) represented an *input* alert. That concept is gone as an input; `AlertPayload` is removed from `models.py`. `TriageState.customer_id: str` becomes the primary key for investigation. `sample_data.py` / `SAMPLE_ALERTS` are removed.

A new `AlertRecord` dataclass in `models.py` represents alert *data*, whether read from Neo4j or newly created:
```python
@dataclass(slots=True)
class AlertRecord:
    alert_id: str
    reason: str
    description: str
```
`TriageState` gains `existing_alert: AlertRecord | None = None` (populated during enrichment) and `alert_outcome: AlertOutcome = field(default_factory=AlertOutcome)`:
```python
@dataclass(slots=True)
class AlertOutcome:
    action: str = "none"  # "none" | "existing" | "created"
    alert_id: str | None = None
    reason: str | None = None
```

`HIGH_RISK_EVIDENCE_KINDS` moves from `workflow.py` to `models.py` (both `workflow.assess_risk` and `llm.RuleBasedLLMAdapter` need it; `llm.py` cannot import `workflow.py` without a cycle since `workflow.py` already imports `llm.py`).

### 2. New workflow step: `register_alert`, positioned right after `insights`

Sequence becomes: `initialize -> enrich -> insights -> register_alert -> assess_risk -> [human_review] -> review`. `register_alert` is independent of `assess_risk`'s structural risk level by design (Non-Goal above) — it only consumes `state.existing_alert` and `state.insights.recommend_alert`/`alert_reason`:
- If `state.existing_alert` is set (found during `enrich_state`): `alert_outcome = AlertOutcome("existing", existing_alert.alert_id, existing_alert.reason)`. No write.
- Else if `state.insights.recommend_alert`: call `repository.create_alert(customer_id, reason=state.insights.alert_reason, description=...)`, set `alert_outcome = AlertOutcome("created", new_alert.alert_id, new_alert.reason)`.
- Else: `alert_outcome = AlertOutcome("none")`.

This node is added to both `build_langgraph` (new `register_alert` node, linear edge `insights -> register_alert -> assess_risk`) and `run_triage` (plain function call in sequence) — same dual-path pattern the codebase already uses everywhere else. `build_triage_response` gains an `"alert"` section reporting `action`/`alert_id`/`reason`.

**Alternative considered**: run `register_alert` after `review`/`finalize` instead, to have the full disposition available for the alert's stored reason text. Rejected — it would make the decision *look* like it depends on `risk.level`/disposition, which contradicts the "LLM decides explicitly" choice; keeping it immediately after `insights` keeps the causal chain (evidence -> insight judgment -> alert) explicit and testable in isolation from risk classification.

### 3. Idempotency: check-then-create, not a database constraint

`Neo4jAlertRepository.find_alert_for_customer(customer_id) -> AlertRecord | None` runs during `enrich_state` (one extra read alongside the existing evidence queries):
```cypher
MATCH (a:Alert)-[:TARGETS]->(c {customer_id: $customer_id})
RETURN a.alert_id AS alert_id, a.reason AS reason, a.description AS description
LIMIT 1
```
`Neo4jAlertRepository.create_alert(customer_id, reason, description) -> AlertRecord` generates a deterministic id (`f"alert-auto-{customer_id}"`) and writes:
```cypher
MATCH (c {customer_id: $customer_id})
MERGE (a:Alert {alert_id: $alert_id})
SET a.reason = $reason, a.description = $description
MERGE (a)-[:TARGETS]->(c)
```
Using `MERGE` on the deterministic id makes a second accidental call idempotent at the database level too (belt-and-suspenders on top of the application-level existence check). The offline (`graph_engine`) path mirrors this over the in-memory dataset for tests, tracking created alerts in a dict on the offline repository instance — writes there are process-local and not persisted, consistent with the rest of the offline path (evidence, etc. is also recomputed each call, not persisted).

**Alternative considered**: random/UUID alert ids. Rejected — deterministic ids make the idempotency check trivially testable and keep `MERGE` meaningful; nothing requires unpredictability here.

### 4. Insight response schema gains `recommend_alert: bool` and `alert_reason: str`

`INSIGHT_RESPONSE_SCHEMA`, `InsightRequest`, and `InsightResponse` in `llm.py` all gain the two fields. `InsightRequest` drops `alert: AlertPayload` in favor of `customer_id: str` and `existing_alert: AlertRecord | None` (so the prompt can say "this customer already has an open alert for X" when relevant, and the model isn't asked to redundantly recommend one).

- **`RuleBasedLLMAdapter`** (static mode): `recommend_alert = any(item.kind in HIGH_RISK_EVIDENCE_KINDS for item in request.evidence)`, with a templated `alert_reason` when true. This is a deliberate design choice: static mode has no reasoning, so its "recommendation" is a direct mirror of the same structural detection `assess_risk` uses — deterministic and testable, not a second, independently-tunable heuristic.
- **`AnthropicLLMAdapter` / `OpenAILLMAdapter`** (real LLM mode): the system prompt is extended with an explicit grounding instruction: *"Only recommend an alert when the supplied evidence shows a concrete suspicious pattern; never recommend one from absence of evidence or speculation."* The model returns `recommend_alert`/`alert_reason` as part of the same structured JSON-schema response already used for `summary`/`key_observations` — no extra round-trip.

### 5. `AML_ALERT_LLM_ENABLED` becomes the sole static/real-LLM switch

`create_llm_adapter`:
```python
if not config.llm_enabled:
    return RuleBasedLLMAdapter(provider="rule-based", model=config.llm_model)
if config.llm_provider == "openai":
    ...
return AnthropicLLMAdapter(...)  # default real-LLM provider when enabled=true
```
`DisabledLLMAdapter` is deleted (dead code once `llm_enabled=False` routes to `RuleBasedLLMAdapter` directly) along with its test. `AML_ALERT_LLM_PROVIDER` now only matters when `llm_enabled=true` (chooses `anthropic` vs `openai`); `rule-based` is no longer a provider value to select explicitly — it's simply what `llm_enabled=false` means. This is a small simplification over today's three-provider-string design, matching the mental model the project owner described: *false = static, true = real LLM (pick which one)*.

### 6. `OpenAILLMAdapter` (folded in from the prior standalone proposal)

Mirrors `AnthropicLLMAdapter`: lazy `openai.OpenAI(timeout=...)` client, `compose_insight_prompt` reuse, Chat Completions with `response_format={"type": "json_schema", ...}` built from the (now alert-aware) `INSIGHT_RESPONSE_SCHEMA`. `reasoning_effort: str | None`, resolved in `create_llm_adapter` to `"medium"` when the provider is `openai` and `AML_ALERT_LLM_REASONING_EFFORT` is unset (new `AppConfig.llm_reasoning_effort` field). Default model `gpt-5`. `openai` is added to the existing `llm` extra in `pyproject.toml`. Credential resolution via the SDK's standard `OPENAI_API_KEY`.

**Provider selection is entirely `.env`-driven**, with two independent switches (per the project owner's mental model): `AML_ALERT_LLM_ENABLED` (`false`/`true`) picks static vs. real LLM, and — only when `true` — `AML_ALERT_LLM_PROVIDER` (`openai`/`anthropic`) picks which real LLM. No code change or CLI flag is needed to switch between Claude and OpenAI; both credentials (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) can be present in `.env` simultaneously and only the selected provider's key is read.

**Model selection is also purely `.env`-driven, for either provider**, via the existing `AML_ALERT_LLM_MODEL` variable (already present in `config.py` before this change, previously only exercised by the `anthropic` branch). `create_llm_adapter` keeps the same override rule for both providers: if `config.llm_model` still equals `AppConfig()`'s default (`"local-insight-summarizer"`, meaning the operator never set `AML_ALERT_LLM_MODEL`), substitute the provider's own default (`DEFAULT_ANTHROPIC_MODEL` / `DEFAULT_OPENAI_MODEL`); otherwise pass the operator's exact string straight through to the API call. Picking e.g. `claude-opus-5` or `gpt-5-mini` is a one-line `.env` edit — never a code change.

### 9. Generalized N-hop evidence retrieval (`NEO4J_MAX_HOPS` becomes a real ceiling)

Today, `_fetch_direct_evidence` (1 hop) and `_fetch_second_hop_evidence` (a hardcoded 2-hop pivot join) are the only two evidence queries; `hop_radius` past 2 has no further effect. This change replaces both with a single iterative frontier-expansion helper, so `NEO4J_MAX_HOPS` genuinely bounds how many hops the widen-search retry loop (`should_widen_search`/`widen_search` in `workflow.py`, unchanged) can reach:

```python
def _fetch_hop_evidence(self, customer_id: str, hop_radius: int, limit: int) -> list[EvidenceItem]:
    frontier = self._account_ids_for_customer(customer_id)   # hop 0: the customer's own accounts
    visited = set(frontier)
    evidence: list[EvidenceItem] = []
    for hop in range(1, hop_radius + 1):
        transactions = self._fetch_transactions_touching(frontier, limit)
        next_frontier = {counterparty(t) for t in transactions} - visited
        evidence.extend(self._transactions_to_evidence(transactions, frontier, hop))
        visited |= next_frontier
        frontier = next_frontier
        if not frontier:
            break  # graph exhausted before reaching hop_radius; stop early
    return evidence
```
Each hop is one simple, non-variable-length Cypher query (`MATCH (a)-[r:TRANSFERRED_TO]-(b) WHERE a.account_id IN $frontier ...`), avoiding the "variable-length bound can't be parameterized" constraint the codebase already documents for `cycle_max_hops` (`_CYCLE_HOPS_RANGE` clamp-and-interpolate). `visited` prevents revisiting accounts already seen at an earlier hop, so this describes *breadth* outward from the customer — it deliberately does not surface cycles back to a visited account (that remains `_fetch_cycle_evidence`'s job, unaffected, still governed by `AML_ALERT_CYCLE_MAX_HOPS`/`cycle_max_hops` as its own separate ceiling).

`graph_engine.py`'s offline mirror gets the equivalent generalization: `direct_transactions`/`second_hop_transactions` are replaced by a single `hop_transactions(dataset, own_account_ids, max_hop) -> list[EvidenceItem]` that performs the same frontier-expansion loop over the in-memory dataset, so `evidence_for_customer` (used by both the offline repository path and tests) stays a faithful reimplementation of the live query — the existing "two paths never silently drift" invariant is preserved, now for arbitrary hop depth instead of just 1-2.

Behavior at `hop_radius=1` and `hop_radius=2` is unchanged (same accounts visited, same evidence produced) — this is a pure generalization, not a behavior change at the depths already in use today. `AppConfig.neo4j_max_hops` default stays `2`; operators can now raise it (e.g., to 3 or 4) and it will genuinely traverse further, whereas today it silently has no effect past 2.

**Alternative considered**: a single Cypher variable-length pattern (`TRANSFERRED_TO*1..N`) evaluated in one query. Rejected — the upper bound would need the same literal-interpolation workaround already used for `cycle_max_hops`, and a single multi-hop query can't easily distinguish "hop 1 evidence" from "hop 3 evidence" for the evidence item's `kind`/`subject` framing the way the current per-hop item shape requires; the iterative approach keeps each hop's Cypher trivial and keeps evidence framing (subject = the frontier account each transaction was found from) exactly as it is today.

### 9a. Alert-proximity evidence: connection to an already-alerted customer

A customer who transacts — directly or through intermediaries — with someone who already has an `Alert` is itself a red flag (association/network screening, a real AML technique), independent of whether the customer's *own* transaction graph shows a cycle or structuring pattern. This is added as a fourth targeted, hop-radius-independent query, alongside `_fetch_cycle_evidence`/`_fetch_structuring_evidence`:

```cypher
MATCH (customer {customer_id: $customer_id})-[:OWNS]->(account)
MATCH path = (account)-[:TRANSFERRED_TO*1..N]-(other_account)
MATCH (other_customer)-[:OWNS]->(other_account)
MATCH (a:Alert)-[:TARGETS]->(other_customer)
WHERE other_customer.customer_id <> $customer_id
WITH other_customer, a, min(length(path)) AS hops
RETURN other_customer.customer_id AS linked_customer_id, a.alert_id AS linked_alert_id, hops
ORDER BY hops ASC
LIMIT $limit
```
`N` is a new, independent config ceiling, `AppConfig.alert_proximity_max_hops` (`AML_ALERT_PROXIMITY_MAX_HOPS`, default `3`) — deliberately separate from `cycle_max_hops`, since "how far a laundering cycle can loop back" and "how far association-with-a-flagged-customer should reach" are different tuning knobs with different real-world justifications, per the project owner's explicit choice. It is clamped and literal-interpolated the same way `cycle_max_hops` already is (Cypher variable-length bounds cannot be bind parameters).

Each match becomes `EvidenceItem(kind="alert-proximity", subject=customer_id, details="Connected within {hops} hop(s) to customer {linked_customer_id}, who already has alert {linked_alert_id}.", source="neo4j")`. **`"alert-proximity"` joins `HIGH_RISK_EVIDENCE_KINDS`** (now `{"cycle", "structuring-fanout", "structuring-fanin", "alert-proximity"}`) — per the project owner's explicit choice, proximity to a known flagged customer is treated with the same severity as a structural typology match: it alone drives `assess_risk` to `high` and triggers the `human_review` interrupt, with no other code change needed since `assess_risk` already just checks kind membership in the set.

**Offline parity requires new state.** Unlike cycle/structuring (self-contained within one customer's transaction graph), proximity detection depends on *which customers currently have an alert* — live Neo4j sees this for free (every `Alert` node ever written, including ones created earlier in the same run, is already in the database). The offline path has no persistent database, so `Neo4jAlertRepository`'s offline mode gains a process-local `set[str]` of alerted customer ids, seeded from `ALERTS` (Decision 7) and appended to whenever the offline `create_alert` runs — so investigating customer B after customer A was flagged in the same offline/test run correctly surfaces the new proximity link, mirroring live behavior instead of only ever seeing the 2 seed alerts.

**Alternative considered**: reuse `cycle_max_hops` for this query too, avoiding a new config variable. Rejected per explicit project owner direction (a dedicated, independently-tunable ceiling was requested).

### 10. Alert snapshot persisted to DynamoDB, not Neo4j

A generated Markdown report needs to show "why this alert was raised" as it looked *at creation time* — evidence, risk classification, and the insight (static or LLM) that triggered it — independent of whatever the live graph looks like later. Rather than growing the `Alert` node's properties in Neo4j (mixing an audit snapshot into the graph's live query surface) or writing to a local file, this is persisted to a **separate auxiliary store: DynamoDB Local**, added to `docker-compose.yml` alongside a **`dynamodb-admin`** UI for browsing it (both requested explicitly by the project owner).

`docker-compose.yml` gains two services:
```yaml
dynamodb-local:
  image: amazon/dynamodb-local:latest
  ports: ["8000:8000"]
  command: ["-jar", "DynamoDBLocal.jar", "-sharedDb", "-dbPath", "./data"]
  volumes: ["dynamodb_data:/home/dynamodblocal/data"]

dynamodb-admin:
  image: aaronshaf/dynamodb-admin:latest
  ports: ["8001:8001"]
  environment:
    DYNAMO_ENDPOINT: http://dynamodb-local:8000
    AWS_REGION: ${DYNAMODB_REGION:-us-east-1}
    AWS_ACCESS_KEY_ID: local
    AWS_SECRET_ACCESS_KEY: local
  depends_on: [dynamodb-local]
```
`AppConfig` gains `dynamodb_endpoint_url` (default `http://localhost:8000`), `dynamodb_table_name` (default `aml-alert-snapshots`), `dynamodb_region` (default `us-east-1`). A new `snapshot_store.py` module defines:
```python
@dataclass(slots=True)
class AlertSnapshot:
    alert_id: str
    customer_id: str
    reason: str
    description: str
    evidence: list[EvidenceItem]
    risk: RiskAssessment
    insight_mode: str            # "static" | "anthropic" | "openai"
    insight_summary: str
    insight_key_observations: list[str]
    alert_reason: str
    created_at: str              # ISO-8601 UTC

class AlertSnapshotStore:
    def ensure_table(self) -> None: ...      # create-if-not-exists, alert_id as partition key
    def save_snapshot(self, snapshot: AlertSnapshot) -> None: ...
    def get_snapshot(self, alert_id: str) -> AlertSnapshot | None: ...
```
`insight_mode` records which adapter actually produced the insight that led to the alert (`"static"` when `AML_ALERT_LLM_ENABLED=false`, or the provider name when `true`) — this is how the report ends up showing "whichever analysis was active," directly resolving the "respects the current toggle" decision without the report step making any new LLM call itself.

Lazy `boto3` client construction (dummy `local`/`local` credentials, matching DynamoDB Local's no-auth expectation) mirrors the lazy-driver pattern already used for `Neo4jAlertRepository` and the LLM adapters. `boto3` becomes a core dependency (not an optional extra) in `pyproject.toml`, since snapshot persistence is part of the default `register_alert` path, not an opt-in feature.

**Snapshot writes are best-effort, matching the rest of the codebase's degrade-gracefully posture.** If DynamoDB Local is unreachable, `register_alert` logs a warning and still completes the alert creation in Neo4j — a missing snapshot means that alert's report cannot later be generated (surfaced as a clear error from `--report-alert-id`), but it never fails the investigation itself, consistent with how a Neo4j-unreachable or LLM-failure condition is handled elsewhere in this workflow.

### 11. Pre-registered alerts get seeded snapshots too

The 2 pre-registered alerts (Decision 7) are not created via `register_alert`, so they would otherwise have no snapshot and `--report-alert-id` would fail for them. `scripts/generate_dataset.py` also emits `data/dynamodb/seed.json` — a JSON array of `AlertSnapshot` records for those 2 cases, built with the same rule-based (static) evidence-derivation logic used elsewhere in the generator, so the seeded snapshots are consistent with what `register_alert` would have produced. A new `--seed-dynamodb` CLI flag (mirroring `--seed-neo4j`) loads this file via `AlertSnapshotStore.save_snapshot`, after first calling `ensure_table()`.

### 12. `--report-alert-id`: a pure read-and-render step

`report.py` adds `render_alert_report(snapshot: AlertSnapshot) -> str` (Markdown string: title, alert metadata, the single insight analysis section labeled by `insight_mode`, and an evidence table rendering each `EvidenceItem` as a relationship/transaction row) and `generate_alert_report(alert_id, snapshot_store, output_path=None) -> Path` (fetches the snapshot, raises a clear error if none exists, writes to `reports/<alert_id>.md` by default, creating the `reports/` directory if needed). `main.py` gains `--report-alert-id <id>` and an optional `--report-output <path>`. This step makes **no** Neo4j or LLM calls — everything it needs is already in the snapshot, keeping report generation fast, deterministic, and independent of whether Neo4j/an LLM provider is reachable at report time.

**Alternative considered**: re-querying Neo4j live for the evidence shown in the report (simpler, no new store). Rejected per explicit project owner direction — an audit-style report should reflect the state at flagging time, and using a separate auxiliary store (DynamoDB, with an admin UI) was a deliberate ask, not just an implementation convenience.

### 7. Dataset: 50 customers via a versioned generator script

`scripts/generate_dataset.py` (fixed random seed, self-validating like the original scratchpad script) generates:
- **30 organic customers**: everyday PIX/boleto/TED/deposit activity, structurally guaranteed acyclic and capped fan-out/fan-in per account (same self-validated property the current 25-customer organic pool already has).
- **20 suspicious customers**, each independently injected with one typology: a directed transfer cycle, or a structuring fan-out/fan-in pattern — an approximately even split across the three typologies (mirroring today's `cycle` / `structuring-fanout` / `structuring-fanin` evidence kinds; exact counts pinned in `tasks.md`).
- **2 pre-registered alerts**: exactly two of the 20 suspicious customers get an `Alert` node + `TARGETS` relationship written into both `graph_dataset.py`'s offline fixtures (a new `ALERTS: list[AlertSeed]`) and `data/neo4j/seed.cypher`. The other 18 suspicious customers (and all 30 organic ones) have no alert until an investigation run creates one.

The script writes both `src/aml_alert_triage/graph_dataset.py` (the offline/test source of truth) and `data/neo4j/seed.cypher` (the live-graph rendering), matching the existing "one generator, two outputs, self-validated" pattern documented in the current README.

### 8. CLI: `--customer-id` replaces `--alert-id`

`main.py` drops `SAMPLE_ALERTS`/`--alert-id`/`--seed-file` default coupling to alert scenarios. New `--customer-id` (required, or defaulted to one known organic customer for a zero-config demo run) feeds `initialize_state(customer_id, user_prompt)` directly. `--thread-id` defaults to `customer_id` instead of `alert.alert_id`. Help text and README examples are updated to show investigating both an organic customer (no alert expected) and a suspicious-but-undiscovered customer (alert created by the run).

## Risks / Trade-offs

- [A real LLM (anthropic/openai) could recommend an alert ungrounded in evidence, writing a spurious `Alert` node] → Mitigated by an explicit grounding instruction in the system prompt and by evidence always being included in the request; not mitigated by any server-side validation — acceptable for a study/demo project, called out in README as a known limitation of LLM-driven writes.
- [Two sources of truth for "is this customer suspicious": `assess_risk`'s structural classification and `insights.recommend_alert`] → They can disagree (e.g., real LLM recommends an alert on `elevated`-but-not-`high` evidence). This is intentional (Non-Goal: `register_alert` is independent of `risk.level`) but should be clearly surfaced in the response (`alert` section is separate from `risk`/`disposition` in `build_triage_response`) so it never looks like silent inconsistency.
- [Regenerating the dataset invalidates the existing `--alert-id` scenario table and any external notes referencing `alert-001`..`alert-006`] → Expected and accepted (**BREAKING**, already called out in the proposal); README is updated with a new customer-based scenario table.
- [Offline `create_alert` writes are process-local (not persisted) while live Neo4j writes are real] → Matches the existing offline/live asymmetry already accepted throughout the codebase (evidence is also recomputed, not persisted, offline); tests exercise the offline path's in-memory idempotency directly.
- [Generalized N-hop traversal issues one Cypher query per hop, so a high `NEO4J_MAX_HOPS` on a dense graph means more round-trips and a larger evidence set fed to the LLM] → Acceptable at the dataset's scale (50 customers); `evidence_limit` (`AML_ALERT_EVIDENCE_LIMIT`) still caps items per hop, and `min_evidence_for_conclusion` still stops the widen-search retry loop as soon as enough evidence is found, so deep hops are only reached when genuinely needed.
- [A third infrastructure dependency (DynamoDB Local) adds setup surface to a study project] → Scoped tightly: one table, two new `docker-compose.yml` services, best-effort writes that never fail the main workflow. Accepted as an explicit, deliberate requirement from the project owner rather than an incidental addition.
- [An alert created before this feature existed, or created while DynamoDB was down, has no snapshot] → `--report-alert-id` fails with a clear, specific error (no snapshot found) rather than silently falling back to a live re-query, so a report never misleadingly presents "current graph state" as if it were "state at flagging time."

## Migration Plan

This is a from-scratch reseed, not a live migration: existing local Neo4j data from the previous 30-customer/6-alert dataset should be dropped and reloaded via `--seed-neo4j` against the new `data/neo4j/seed.cypher`. No production data exists (fictional/local-only project). Rollback is reverting the change and reseeding from the prior `seed.cypher` (retained in git history).

## Open Questions

None — all four open design questions (alert decision-maker, CLI parameter, dataset generator persistence, duplicate-alert handling) were confirmed with the project owner before writing this document.
