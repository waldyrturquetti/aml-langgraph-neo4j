## MODIFIED Requirements

### Requirement: AML alert triage workflow
The system MUST provide a LangGraph-based workflow that investigates a customer by id, tracks investigation state, generates insights from Neo4j evidence, and produces a structured recommendation.

#### Scenario: Workflow starts from a customer id
- **WHEN** the system receives a customer id and an optional free-text user prompt
- **THEN** it SHALL initialize investigation state with the customer id, prompt context, and investigation status
- **AND THEN** it SHALL route the investigation through enrichment, insight generation, alert registration, and recommendation stages

#### Scenario: Workflow produces a structured result with insights and alert outcome
- **WHEN** the workflow completes investigation
- **THEN** it SHALL return a structured result containing decision, rationale, supporting evidence summary, generated insights, and the alert outcome (whether an alert already existed, was newly created, or was not warranted)

### Requirement: Neo4j evidence enrichment
The system MUST enrich the customer investigation with connected evidence from Neo4j, including related entities, transactions, and any pre-existing alert for that customer, traversing up to a configured maximum number of hops.

#### Scenario: Fictional seed data can be inserted for local validation
- **WHEN** a developer prepares a local environment for the workflow
- **THEN** the project SHALL provide a repeatable way to load fictional AML graph data into the Neo4j container
- **AND THEN** the dataset SHALL include both connected-evidence cases and no-relationship cases

#### Scenario: Evidence is retrieved from graph relationships up to a configured hop ceiling
- **WHEN** the workflow begins evidence enrichment for a customer
- **THEN** it SHALL query Neo4j for related nodes and relationships starting from the customer's own accounts
- **AND THEN** it SHALL be able to widen the traversal hop by hop, up to a configured maximum number of hops, stopping early if the graph is exhausted before that ceiling
- **AND THEN** it SHALL include the retrieved evidence in the investigation state

#### Scenario: Missing relationships are handled safely
- **WHEN** Neo4j does not contain related evidence for a customer
- **THEN** the system SHALL continue the workflow with an empty or limited evidence set
- **AND THEN** it SHALL record that no related evidence was found

#### Scenario: Retrieved evidence matches workflow state shape
- **WHEN** graph evidence is returned from Neo4j queries
- **THEN** each evidence item SHALL include `kind`, `subject`, `details`, and `source`
- **AND THEN** the workflow SHALL accept the result without additional shape adaptation

#### Scenario: Pre-existing alert is detected during enrichment
- **WHEN** the investigated customer already has an `Alert` node connected via a `TARGETS` relationship in Neo4j
- **THEN** the workflow SHALL load that alert's identifier and reason into the investigation state
- **AND THEN** it SHALL make this existing-alert context available to the insight generation stage

#### Scenario: Connection to an already-alerted customer is detected
- **WHEN** the investigated customer is connected, directly or through intermediary accounts up to a configured maximum number of hops, to another customer who already has an `Alert`
- **THEN** the workflow SHALL include an evidence item identifying the linked customer, the existing alert, and the hop distance between them
- **AND THEN** this evidence SHALL be classified with the same severity as a detected transfer cycle or structuring pattern

### Requirement: Analyst-ready recommendation
The system MUST generate an analyst-ready investigation recommendation that references collected evidence and generated insights without claiming unsupported facts.

#### Scenario: Recommendation cites evidence and insight boundaries
- **WHEN** the workflow generates a recommendation
- **THEN** it SHALL reference the evidence used to support the conclusion
- **AND THEN** it SHALL distinguish factual evidence statements from interpretive insights

#### Scenario: Recommendation remains deterministic in structure
- **WHEN** two customers with the same graph data are investigated
- **THEN** the system SHALL produce recommendations with the same output fields and workflow stages even if insight wording varies

## ADDED Requirements

### Requirement: Idempotent alert registration
The system MUST register a new `Alert` node in Neo4j when insight generation recommends one and the customer does not already have one, and MUST NOT create a duplicate when one already exists.

#### Scenario: No existing alert and an alert is recommended
- **WHEN** the customer has no pre-existing `Alert` node and the insight generation stage recommends creating one
- **THEN** the workflow SHALL create a new `Alert` node with a `TARGETS` relationship to the customer, storing the recommended reason
- **AND THEN** the investigation result SHALL report the alert as newly created, including its identifier and reason

#### Scenario: An alert already exists for the customer
- **WHEN** the customer already has an `Alert` node connected via `TARGETS`
- **THEN** the workflow SHALL NOT create another `Alert` node for that customer
- **AND THEN** the investigation result SHALL report the existing alert's identifier and reason instead

#### Scenario: No alert is warranted
- **WHEN** the customer has no pre-existing alert and insight generation does not recommend creating one
- **THEN** the workflow SHALL complete without writing any `Alert` node
- **AND THEN** the investigation result SHALL report that no alert action was taken

### Requirement: Fictional customer/account/transaction seed dataset composition
The system MUST provide a fictional seed dataset centered on customers, accounts, and transactions, with a documented mix of ordinary and suspicious activity and a small number of pre-registered alerts.

#### Scenario: Dataset composition is documented and reproducible
- **WHEN** a developer inspects or regenerates the fictional dataset
- **THEN** the dataset SHALL contain 50 customers: 30 with ordinary organic transaction activity and 20 with an injected suspicious pattern (a directed transfer cycle, or a structuring fan-out/fan-in pattern)
- **AND THEN** exactly 2 of the 20 suspicious customers SHALL have a pre-registered `Alert` node in the seed data, while the remaining 18 SHALL have no alert until discovered through investigation
- **AND THEN** the dataset SHALL be produced by a deterministic, version-controlled generator so it can be regenerated and self-validated rather than hand-maintained
