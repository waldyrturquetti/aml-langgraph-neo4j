## 1. LLM Configuration and Contracts

- [x] 1.1 Add configuration fields for LLM provider/model settings and safe defaults for local execution.
- [x] 1.2 Define typed state fields for insight summary, key observations, and insight status/error metadata.
- [x] 1.3 Define an LLM adapter interface and normalized response schema used by the workflow.

## 2. Insight Generation Pipeline

- [x] 2.1 Build a prompt composer that transforms alert context and Neo4j evidence into a constrained LLM input payload.
- [x] 2.2 Implement an insight generation function that calls the LLM adapter and maps response content into normalized insight fields.
- [x] 2.3 Implement fallback behavior for timeout/provider/parse errors so triage completes with safe default insights.

## 3. Workflow Integration

- [x] 3.1 Insert a dedicated insights node after Neo4j enrichment in both linear and LangGraph execution paths.
- [x] 3.2 Update final response assembly to include recommendation, evidence summary, and LLM insights in a consistent output structure.
- [x] 3.3 Ensure recommendation text distinguishes factual evidence statements from interpretive LLM insights.

## 4. Testing and Validation

- [x] 4.1 Add unit tests for prompt composition and normalized insight response mapping.
- [x] 4.2 Add workflow tests for successful LLM insight generation and final output field coverage.
- [x] 4.3 Add workflow tests for LLM failure fallback path that still returns completed triage output.
- [x] 4.4 Add deterministic-structure tests to confirm output keys/stages remain stable for identical inputs.

## 5. Documentation

- [x] 5.1 Update README with an explicit flow example: user prompt -> Neo4j retrieval -> LLM insights -> response.
- [x] 5.2 Document required environment variables and local execution examples for running triage with and without LLM availability.
- [x] 5.3 Review all new docs, logs, and prompts to ensure English language consistency and fictional-data scope statements.