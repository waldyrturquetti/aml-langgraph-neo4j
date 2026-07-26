## 1. Project Setup

- [x] 1.1 Add or confirm the Python package layout for the AML triage workflow, Neo4j access layer, and shared domain models.
- [x] 1.2 Define the triage state schema, including alert metadata, evidence collection, decision output, and workflow status fields.
- [x] 1.3 Add configuration for Neo4j connection settings and any workflow limits required by the design.
- [x] 1.4 Add Docker Compose configuration for Neo4j with persistent storage, exposed ports, and local development defaults.
- [x] 1.5 Add environment sample files and documentation for starting the containerized Neo4j service.

## 2. Graph Workflow

- [x] 2.1 Implement the LangGraph entry node that accepts a fictional alert payload and initializes triage state.
- [x] 2.2 Implement the Neo4j enrichment step that loads related entities, transactions, and historical alert context.
- [x] 2.3 Implement the evidence review and recommendation nodes that produce a structured analyst-facing result.
- [x] 2.4 Wire the graph transitions so the workflow handles missing evidence safely and always reaches a terminal result.

## 3. Neo4j Integration

- [x] 3.1 Implement repository or adapter methods for reading alert-linked entities and relationships from Neo4j.
- [x] 3.2 Add a small fictional dataset or fixture set that exercises connected and disconnected alert scenarios.
- [ ] 3.3 Verify the graph queries return the evidence shape expected by the workflow state.
- [ ] 3.4 Verify the application can connect to the Neo4j container using the documented local configuration.

## 4. Validation and Documentation

- [x] 4.1 Add tests for workflow initialization, evidence enrichment, missing-evidence handling, and final recommendation structure.
- [x] 4.2 Add tests that confirm the output remains deterministic in structure for identical inputs.
- [x] 4.3 Document the fictional-only scope, workflow stages, and how to run the triage agent locally.
- [x] 4.4 Review logs, prompts, comments, and docstrings to ensure they are written in English and match the project conventions.
- [x] 4.5 Validate the Docker Compose startup path and Neo4j connectivity notes in the setup documentation.
