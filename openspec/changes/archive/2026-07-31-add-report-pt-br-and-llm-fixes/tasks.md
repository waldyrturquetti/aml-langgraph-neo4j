## 1. LLM Path Bug Fixes

- [x] 1.1 Add `python-dotenv` dependency; call `load_dotenv()` at `config.py` import time so `.env` actually takes effect.
- [x] 1.2 Raise `OpenAILLMAdapter.max_tokens` default from 1024 to 4096 to leave headroom for reasoning-effort models.
- [x] 1.3 Raise a clear `RuntimeError` (naming `finish_reason`) when the OpenAI response content is empty, instead of an opaque `json.loads(None)` failure.

## 2. Dual-Language Insight Generation

- [x] 2.1 Add `summary_pt`, `key_observations_pt`, `alert_reason_pt` to `INSIGHT_RESPONSE_SCHEMA` (required) and `InsightResponse`.
- [x] 2.2 Extend the shared system prompt to request faithful Portuguese translations alongside the English fields, in the same response.
- [x] 2.3 Update `AnthropicLLMAdapter`/`OpenAILLMAdapter` to parse the `_pt` fields from the response payload (defaulting to empty if absent).
- [x] 2.4 Add Portuguese templates to `RuleBasedLLMAdapter` (summary/observations for both evidence-present and no-evidence cases, alert-reason with translated typology labels).
- [x] 2.5 Add `_pt` fields to `InsightResult`; populate them in `workflow.generate_insights` for both the success and fallback paths (fallback path uses hand-written Portuguese fallback text).

## 3. Evidence/Risk Translation

- [x] 3.1 Add `src/aml_alert_triage/i18n_pt.py`: `translate_evidence_detail_pt` (dispatches on `EvidenceItem.kind`, regex-extracts the variable parts of each known template, falls back to original text if unrecognized), `translate_evidence_summary_pt`, `translate_risk_rationale_pt` (rebuilt from structured `RiskAssessment` fields, no regex needed), `KIND_LABELS_PT`/`CHANNEL_LABELS_PT`.
- [x] 3.2 Cover all five evidence template shapes (pix/boleto/ted/deposit transactions, cycle, structuring-fanout, structuring-fanin, alert-proximity) plus the fallback path with dedicated tests (`tests/test_i18n_pt.py`).

## 4. Report Rendering

- [x] 4.1 Update `register_alert` to build the `AlertSnapshot` from the `_pt` insight fields (reason/description/insight_summary/insight_key_observations/alert_reason), falling back to the English fields with `or`; Neo4j `Alert` properties and the CLI response stay English (unchanged).
- [x] 4.2 Rewrite `report.py`: all static labels/headers in Portuguese, insight-mode labels in Portuguese, evidence table using `translate_evidence_detail_pt`, risk section using `translate_risk_rationale_pt`.
- [x] 4.3 Add a Cypher visualization query section to the report (case accounts/transactions query, plus an alert-node lookup query), parameterized with the snapshot's `customer_id`/`alert_id`.

## 5. Dataset/Seed and Testing

- [x] 5.1 Update `scripts/generate_dataset.py`'s `_build_dynamodb_seed` to use the rule-based adapter's `_pt` fields for the seeded snapshots' `insight_summary`/`insight_key_observations`/`alert_reason`/`reason`/`description`; regenerate `data/dynamodb/seed.json`.
- [x] 5.2 Reseed the live DynamoDB table (`--seed-dynamodb`) with the regenerated Portuguese seed data.
- [x] 5.3 Update `tests/test_llm.py` (rule-based PT templates, real-adapter PT parsing, PT-fields-missing defaulting) and `tests/test_report.py` (Portuguese sections, translated evidence/risk, Cypher query section); add `tests/test_i18n_pt.py`.
- [x] 5.4 Run the full test suite (`pytest`) and confirm all tests pass. (97/97 passing)
- [x] 5.5 Manually verify: generate a report for a real alert and confirm it reads entirely in Portuguese with a working Cypher query section.

## 6. Documentation

- [x] 6.1 Rewrite the README as a full step-by-step run guide (setup, seeding, investigating, reports) reflecting the current CLI surface.
- [x] 6.2 Document the `.env` loading behavior (python-dotenv) and the OpenAI token-budget/empty-response fix.
- [x] 6.3 Document that alert investigation reports render in Portuguese and include a Cypher visualization query.
- [x] 6.4 Add concrete worked use-case examples (organic customer, undiscovered typology cases, proximity case, report generation, human-in-the-loop resume).
