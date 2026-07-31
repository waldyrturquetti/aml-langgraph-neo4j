## Why

The current workflow retrieves connected evidence from Neo4j and returns deterministic triage outputs, but it does not generate higher-level analytical insights from that evidence. Adding an LLM insights step will make the project more useful for learning by demonstrating how graph evidence can be interpreted into concise analyst guidance.

## What Changes

- Extend the triage workflow with a new post-enrichment step that sends normalized Neo4j evidence to an LLM and receives structured insights.
- Add prompt templates and response-shape handling for the LLM insights stage so output remains predictable and traceable.
- Update workflow state to store LLM-generated insights and include them in the final response to the user.
- Add fallback behavior when the LLM is unavailable, including clear status fields and safe default messaging.
- Update tests to verify prompt input composition, output structure, and non-failing behavior when the LLM call fails.
- Update the README with a concrete flow example showing: user prompt -> Neo4j data retrieval -> LLM insight generation -> response to user.

## Capabilities

### New Capabilities
- `llm-insight-generation`: Generate structured insights from Neo4j evidence and expose them in the triage output.

### Modified Capabilities
- `aml-alert-triage`: Extend workflow requirements to include LLM-based insight generation and final response composition.

## Impact

Affected areas include workflow orchestration, workflow state models, prompt and LLM integration code, error handling paths, tests, and project documentation. This change may introduce optional configuration for LLM model/provider settings while preserving fictional-only data scope for study use.