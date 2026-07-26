## Context

This change adds a LangGraph-driven AML alert triage agent to a Python study project. The workflow needs to explain its reasoning, work only with fictional data, and use Neo4j as the graph-backed evidence store so the agent can traverse entities, accounts, transactions, and prior cases.

The main constraint is to keep the system understandable for learning while still reflecting a realistic triage flow. That means the design should favor explicit state, deterministic graph transitions, and transparent outputs over opaque autonomous behavior.

## Goals / Non-Goals

**Goals:**
- Provide a multi-step triage workflow that can intake an alert, enrich it from Neo4j, evaluate evidence, and produce a recommendation.
- Keep the graph state and node names explicit so the workflow is easy to inspect and test.
- Make the agent output structured, analyst-friendly summaries with traceable evidence.
- Keep all content in English, including prompts, logs, comments, and documentation.

**Non-Goals:**
- Build a production case management platform or human approval UI.
- Connect to real banking systems or use real customer data.
- Encode compliance policy as a substitute for legal or regulatory review.
- Optimize for large-scale throughput or distributed execution.

## Decisions

- Use Docker Compose to run Neo4j locally for development and learning.
  - Rationale: the project needs a repeatable, one-command way to launch the graph database without requiring a manual installation.
  - Alternatives considered: a manually installed Neo4j instance would work, but it would add setup friction and reduce reproducibility.

- Use LangGraph as the primary orchestration layer rather than a single prompt chain.
  - Rationale: alert triage is a stateful process with clear handoffs between intake, enrichment, evidence review, and recommendation.
  - Alternatives considered: a linear LLM chain would be simpler, but it would hide state transitions and make testing harder.

- Use Neo4j as the evidence and relationship store.
  - Rationale: AML investigations are graph-shaped by nature, so connected accounts, counterparties, transactions, and historical alerts are easier to traverse in a property graph.
  - Alternatives considered: a relational schema would store the same facts, but it would require more joins and would not naturally support relationship-centric reasoning.

- Seed Neo4j with a repeatable fictional dataset using versioned Cypher.
  - Rationale: query and workflow validation should run against known graph fixtures that can be loaded the same way on any machine.
  - Alternatives considered: generating fixtures only in Python memory would be faster, but it would not verify real Neo4j query behavior.

- Keep the workflow state explicit and minimal.
  - Rationale: a small, typed state object makes it easier to reason about node inputs and outputs, and it reduces accidental coupling between nodes.
  - Alternatives considered: storing large intermediate artifacts in free-form memory would make the workflow harder to validate.

- Produce a structured triage result instead of a conversational answer.
  - Rationale: the main output should be easy to inspect, test, and extend with downstream automation.
  - Alternatives considered: an open-ended narrative response would be easier to prototype, but it would be harder to assert in tests.

- Separate evidence gathering from recommendation generation.
  - Rationale: this keeps the investigation step auditable and allows each stage to be tested independently.
  - Alternatives considered: merging both steps into one model call would reduce code, but it would blur the reasoning trail.

## Risks / Trade-offs

- Over-reliance on generated reasoning may produce confident but unsupported triage notes -> Mitigation: require the final recommendation to reference concrete evidence fields from Neo4j.
- Graph traversal can become noisy if the search scope is too broad -> Mitigation: constrain hops, rank evidence, and cap the returned context.
- The study project may drift toward compliance-like language that implies real-world decisions -> Mitigation: keep all examples fictional and document the learning-only scope prominently.
- A highly modular graph can be harder for newcomers to follow -> Mitigation: keep node names and transition rules simple and document the workflow clearly.

## Migration Plan

1. Add Docker Compose and environment configuration for local Neo4j startup.
2. Add the new capability spec and implement the LangGraph workflow behind it.
3. Introduce Neo4j-backed repositories or adapters for fictional alert and relationship data.
4. Add a repeatable seed-load path for fictional graph data and verify container connectivity.
5. Add or update tests for each graph stage and the final triage output, including evidence shape checks.
6. Verify the workflow on a small fictional dataset before expanding the scenario set.

Rollback strategy:
- Remove the new change artifacts and revert the implementation changes if the workflow produces unstable or untestable results.
- Because the change is additive, rollback should not require data migration beyond deleting any generated sample data.

## Open Questions

- Should the Docker Compose setup include optional Neo4j browser access ports and persistent storage by default?
- What minimum alert schema should the fictional dataset expose for the first version?
- Should the final triage result include a simple risk label, or only evidence plus analyst guidance?
- How much graph depth should the enrichment step traverse before it stops collecting context?
- Do we want a single reusable triage graph or separate graphs for different alert types later?
