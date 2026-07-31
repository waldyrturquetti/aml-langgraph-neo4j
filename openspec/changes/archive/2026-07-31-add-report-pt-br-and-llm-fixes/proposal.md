## Why

After the previous change (`rework-customer-investigation-flow`, archived) shipped, the project owner tried running it with the real OpenAI provider and hit two real bugs that made the LLM path unusable, then requested two report improvements once the LLM path worked: the alert investigation report should read in Portuguese, and should include a ready-to-run Cypher query so the underlying case can be visualized directly in Neo4j.

## What Changes

- **Fix: `.env` was never actually loaded.** No part of the codebase called `load_dotenv()`; `AppConfig.from_env()` only ever reads `os.getenv`, so a `.env` file had zero effect unless the shell happened to export those variables. Add `python-dotenv` and load it at `config.py` import time.
- **Fix: reasoning-capable OpenAI models could return an empty response.** `OpenAILLMAdapter`'s `max_tokens` (used as `max_completion_tokens`) defaulted to 1024; with `reasoning_effort` set, a model can spend the entire budget on internal reasoning tokens, leaving nothing for the visible JSON answer, which then failed as an unhelpful `TypeError` from `json.loads(None)`. Raise the default to 4096 and raise a clear, actionable `RuntimeError` when content comes back empty.
- **Add Portuguese (pt-BR) alert investigation reports.** The insight-generation contract (rule-based and both real-LLM adapters) now also returns `summary_pt`/`key_observations_pt`/`alert_reason_pt` - a faithful Portuguese translation of the same English content, produced in the *same* call (no extra LLM request, no extra cost). `register_alert` stores the Portuguese text in the DynamoDB snapshot; the CLI JSON response and Neo4j `Alert` node properties are unaffected and stay in English.
- **Translate deterministic evidence/risk text for the report.** Evidence `details` and risk `rationale` are built from fixed English templates (transaction descriptions, cycle/structuring/alert-proximity sentences) regardless of provider; a new `i18n_pt.py` module translates them by dispatching on `EvidenceItem.kind` (which template produced them) rather than free-form parsing, with a safe fallback to the original text if a pattern isn't recognized.
- **Add a Cypher visualization query to the report.** Every generated report now includes a ready-to-run Cypher snippet (parameterized with the alert's customer id and alert id) for viewing the case's accounts/transactions and the alert node directly in Neo4j Browser.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `llm-insight-generation`: insight responses (from every provider) now also carry Portuguese translations of the summary/observations/alert-reason fields, used only by the report - the underlying English contract is unchanged.
- `alert-report-generation`: reports render in Portuguese and include a Cypher query for visualizing the case in Neo4j; still makes no live Neo4j/LLM calls.

## Impact

Affected areas: `src/aml_alert_triage/config.py` (dotenv loading), `src/aml_alert_triage/llm.py` (schema/adapters/system prompt, OpenAI token budget and error handling), `src/aml_alert_triage/models.py` (`InsightResult` pt fields), `src/aml_alert_triage/workflow.py` (`generate_insights`/`register_alert` pt wiring), new `src/aml_alert_triage/i18n_pt.py`, `src/aml_alert_triage/report.py` (Portuguese rendering + Cypher section), `scripts/generate_dataset.py` (seed snapshot content), `data/dynamodb/seed.json` (regenerated), `pyproject.toml` (`python-dotenv` dependency), new `tests/test_i18n_pt.py`, updated `tests/test_llm.py`/`tests/test_report.py`.
