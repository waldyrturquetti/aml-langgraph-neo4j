## Context

The current AML study workflow retrieves fictional graph evidence from Neo4j and returns a structured recommendation. The workflow does not include an explicit reasoning stage that converts raw evidence into concise analyst insights using an LLM, and the README does not yet describe the end-to-end processing strategy in a single flow.

The design must keep the project deterministic in structure, transparent for learning, and resilient when an LLM provider is unavailable.

## Goals / Non-Goals

**Goals:**
- Add a dedicated workflow step that transforms Neo4j evidence into structured LLM insights.
- Preserve deterministic response shape while allowing variable insight text content.
- Ensure the final user response includes both evidence-backed recommendation and LLM-generated insights.
- Add README documentation that illustrates the runtime flow from user prompt to final response.
- Keep all behavior scoped to fictional datasets and learning use.

**Non-Goals:**
- Building provider-specific production-grade prompt management.
- Supporting multi-model routing, streaming, or complex tool-calling orchestration.
- Replacing deterministic recommendation logic with purely generative reasoning.

## Decisions

- Introduce a new workflow node after Neo4j enrichment and before final recommendation serialization.
  - Rationale: this cleanly separates evidence retrieval from interpretation.
  - Alternatives considered: embedding LLM calls inside enrichment was rejected because it mixes data access and reasoning concerns.

- Define an explicit insights payload in workflow state.
  - Rationale: downstream nodes and tests need a stable field contract.
  - Alternatives considered: embedding insights in free-form recommendation text was rejected because it weakens traceability.

- Add a lightweight LLM adapter interface with a safe fallback path.
  - Rationale: deterministic operation is required even if the model call fails or is disabled.
  - Alternatives considered: hard-failing the workflow on model errors was rejected because it harms local learning flows.

- Keep recommendation generation evidence-grounded and append LLM insights as a separate section.
  - Rationale: this preserves factual constraints while still adding interpretive value.
  - Alternatives considered: having LLM produce the final disposition was rejected to avoid unsupported conclusions.

- Document the runtime strategy in README with a simple, explicit flow example.
  - Rationale: the project is educational and should show how prompt, graph data, and model output connect.
  - Alternatives considered: keeping only textual setup instructions was rejected because it does not visualize execution behavior.

## Risks / Trade-offs

- LLM outputs may include speculative statements -> Mitigation: require prompts to constrain outputs to supplied evidence and include fallback messaging.
- Additional external dependency can reduce local reliability -> Mitigation: keep adapter optional with deterministic offline behavior.
- Prompt quality can drift over time -> Mitigation: centralize prompt template and add tests over request payload structure.
- Added workflow stage increases complexity -> Mitigation: keep node boundaries explicit and state schema minimal.

## Migration Plan

1. Extend state models with an insights section and status metadata.
2. Add an LLM adapter and prompt builder that consumes Neo4j evidence.
3. Insert the insights node into the existing workflow graph.
4. Update final response formatting to include insights and fallback status.
5. Add tests for success and failure paths of the insights stage.
6. Update README with end-to-end flow example and execution notes.

Rollback strategy:
- Remove the insights node and adapter wiring while preserving Neo4j-only triage behavior.
- Retain existing recommendation path as the baseline fallback.

## Open Questions

- Should insights be limited to a fixed number of bullet points for deterministic readability?
- Should model settings be environment-driven now or deferred to a follow-up change?
- Should the workflow expose both raw evidence and summarized evidence in final output?