## Context

Manually exercising the just-shipped `rework-customer-investigation-flow` change with a real `OPENAI_API_KEY` surfaced two pre-existing gaps in the LLM path (neither introduced by that change, but blocking it in practice): `.env` was never loaded into the process environment, and `OpenAILLMAdapter`'s token budget was too small for a reasoning-effort model to produce a visible answer. Once those were fixed and the LLM path worked end to end, the project owner asked for two report improvements: Portuguese output, and an embedded Cypher query for visualizing the case.

## Goals / Non-Goals

**Goals:**
- `.env` works out of the box with no manual shell exports.
- A reasoning-capable OpenAI model reliably produces a parseable answer, and a failure to do so is diagnosable from the error message alone.
- The alert investigation report (`report.py`) is entirely in Portuguese: labels, insight text, evidence details, risk rationale, and a working Cypher snippet.
- The CLI JSON response and Neo4j `Alert` node data stay in English (explicit prior decision, unchanged).

**Non-Goals:**
- No change to the CLI's language, no i18n framework/locale switching - Portuguese is hard-coded for the report only, matching the one-off ask.
- No second LLM call for translation - the real-LLM adapters produce both languages in the same structured response.

## Decisions

### 1. Dual-language insight response, one LLM call

`INSIGHT_RESPONSE_SCHEMA` gains `summary_pt`/`key_observations_pt`/`alert_reason_pt` as required fields alongside the existing English ones; the system prompt instructs the model to provide "the same facts and conclusion" in both languages. `RuleBasedLLMAdapter` (no LLM call at all) computes a parallel Portuguese template by hand for the same two summary/observations variants (evidence present / absent) plus the alert-reason sentence, using `i18n_pt.KIND_LABELS_PT` for typology names and `i18n_pt.translate_evidence_summary_pt` for the "top evidence summary" line.

**Alternative considered**: a second LLM call requesting a translation of the English response. Rejected - doubles latency/cost per investigation for no benefit, when the same call can just be asked for both languages up front.

### 2. Language boundary enforced at `register_alert`, not earlier

`InsightResult` (state) carries both language pairs unconditionally - `generate_insights` always populates `summary_pt`/`key_observations_pt`/`alert_reason_pt` (success path from the adapter, fallback path with hand-written Portuguese fallback text). Nothing downstream of that point is forced to pick a language yet. The actual English/Portuguese split happens only in `register_alert`, when building the `AlertSnapshot`: the Neo4j `Alert.reason`/`description` (via `repository.create_alert`, unchanged) and `build_triage_response`'s `"insights"` section (unchanged) stay English; the `AlertSnapshot` - the only thing `report.py` ever reads - is built from the `_pt` fields (falling back to the English ones with `or` if a provider ever left them empty).

### 3. Evidence/risk text translated by dispatching on `kind`, not free-form parsing

Evidence `details` and risk `rationale` are always built from a small, fixed set of English sentence templates elsewhere in the codebase (`format_transaction_details` in `graph_engine.py`; the cycle/structuring/alert-proximity sentences in `graph_engine.py`/`repository.py`; the `assess_risk` rationale). Since `EvidenceItem.kind` already tells us which template produced a given `details` string, `i18n_pt.translate_evidence_detail_pt` dispatches on `kind` and applies one small, purpose-built regex per known shape to extract the variable parts (amount/currency/direction for transactions; hop count for cycles; count+sample for structuring; hop count+customer+alert id for proximity), then re-renders the sentence in Portuguese. `translate_risk_rationale_pt` doesn't need regex at all - it's rebuilt directly from the structured `RiskAssessment.level`/`typologies` fields.

If a pattern doesn't match (should not happen, since we control both the encoder and decoder), the function falls back to the original English text rather than raising - a report should never fail to render over a translation mismatch.

**Alternative considered**: call an LLM to translate evidence text at report-render time. Rejected - `alert-report-generation`'s existing requirement is that report generation makes no live LLM/Neo4j calls; the evidence text is deterministic and machine-generated to begin with, so a template-aware regex translation is both cheaper and more reliable than an LLM call for this specific case.

### 4. `.env` loading and OpenAI token-budget fixes

`config.py` now calls `load_dotenv()` at import time (via the new `python-dotenv` dependency) before any `os.getenv` call - `.env` values are used as defaults, real environment variables still take precedence. `OpenAILLMAdapter.max_tokens` default raised from 1024 to 4096, and an explicit check for empty `response.choices[0].message.content` raises a `RuntimeError` naming the likely cause (`finish_reason` included) instead of letting `json.loads(None)` raise an opaque `TypeError`.

## Risks / Trade-offs

- [Regex-based evidence translation is coupled to the exact English template strings in `graph_engine.py`/`repository.py`] → If those templates change, `i18n_pt.py`'s regexes must be updated too; the safe fallback (original English text) means a mismatch degrades to a partially-English report rather than a crash.
- [4096 tokens is still a guess, not a guarantee, for every possible reasoning_effort/model combination] → The new explicit empty-response error makes a future recurrence immediately diagnosable instead of a silent fallback.

## Migration Plan

No data migration. `data/dynamodb/seed.json` was regenerated (deterministic; only the pre-registered alerts' insight/reason/description text changed to Portuguese) and reseeded via `--seed-dynamodb`; live DynamoDB items created by earlier ad-hoc testing (before this change) remain in English until re-created by a fresh investigation - acceptable for local dev data.
