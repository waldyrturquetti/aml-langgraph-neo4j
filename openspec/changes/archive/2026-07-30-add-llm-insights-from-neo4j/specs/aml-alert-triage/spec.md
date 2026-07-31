## MODIFIED Requirements

### Requirement: AML alert triage workflow
The system MUST provide a LangGraph-based workflow that ingests a fictional AML alert, tracks triage state, generates LLM insights from Neo4j evidence, and produces a structured recommendation.

#### Scenario: Workflow starts from a user prompt and alert context
- **WHEN** the system receives a user triage prompt with a fictional alert payload
- **THEN** it SHALL initialize triage state with alert identifier, prompt context, entity context, and investigation status
- **AND THEN** it SHALL route the alert through enrichment, insight generation, and recommendation stages

#### Scenario: Workflow produces a structured result with insights
- **WHEN** the workflow completes triage
- **THEN** it SHALL return a structured result containing decision, rationale, supporting evidence summary, and LLM-generated insights

### Requirement: Analyst-ready recommendation
The system MUST generate an analyst-ready triage recommendation that references collected evidence and generated insights without claiming unsupported facts.

#### Scenario: Recommendation cites evidence and insight boundaries
- **WHEN** the workflow generates a recommendation
- **THEN** it SHALL reference the evidence used to support the conclusion
- **AND THEN** it SHALL distinguish factual evidence statements from LLM interpretive insights

#### Scenario: Recommendation remains deterministic in structure
- **WHEN** two alerts with the same input data are processed
- **THEN** the system SHALL produce recommendations with the same output fields and workflow stages even if insight wording varies

## ADDED Requirements

### Requirement: README includes strategy flow example
The system documentation MUST include a flow example that explains how the triage strategy processes user prompts with Neo4j and LLM integration.

#### Scenario: Flow example documents end-to-end path
- **WHEN** a developer reads the README
- **THEN** the documentation SHALL show the sequence user prompt -> Neo4j retrieval -> LLM insight generation -> response output
- **AND THEN** it SHALL describe each stage in plain English suitable for learning use