# llm-insight-generation Specification

## Purpose
TBD - created by syncing change add-llm-insights-from-neo4j. Update Purpose after archive.

## Requirements
### Requirement: LLM insight generation from Neo4j evidence
The system MUST generate structured insights by sending enriched Neo4j evidence to an LLM after graph retrieval and before final response assembly.

#### Scenario: Insights are generated from retrieved evidence
- **WHEN** the workflow has collected evidence items for an alert
- **THEN** it SHALL build an LLM request using the alert context and evidence payload
- **AND THEN** it SHALL store generated insights in workflow state for downstream response composition

#### Scenario: Insight generation handles no-evidence cases
- **WHEN** the workflow has no related evidence for the alert
- **THEN** it SHALL send a constrained context indicating no related evidence
- **AND THEN** it SHALL produce a safe default insight message without failing the workflow

### Requirement: Insight output remains structured
The system MUST normalize LLM insight output into a predictable structure for consumers.

#### Scenario: Insight response is normalized
- **WHEN** the LLM returns content for an alert
- **THEN** the workflow SHALL map the result into predefined fields for summary and key observations
- **AND THEN** the final response SHALL include those fields even when some values are empty

#### Scenario: LLM failure does not break triage completion
- **WHEN** an LLM call fails due to timeout, provider error, or invalid response
- **THEN** the workflow SHALL record an insights error status
- **AND THEN** it SHALL continue to produce a completed triage result with fallback insight content
