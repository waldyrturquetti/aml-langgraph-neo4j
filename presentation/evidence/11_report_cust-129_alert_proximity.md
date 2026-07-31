# Relatório de Investigação de Alerta: alert-auto-cust-129

- **Cliente:** cust-129
- **Motivo:** Gatilho de proximidade: a evidência afirma que o cliente está “Conectado em até 2 salto(s) ao cliente cust-200, que já possui o alerta alert-auto-cust-200.” Essa proximidade a um cliente já alertado justifica a sinalização.
- **Nível de risco:** high
- **Criado em:** 2026-07-31T04:24:18.635545+00:00

## Descrição

Fatos: As transações incluem depósitos em acct-122 e acct-124, pagamentos de boleto para acct-122 e acct-124, um TED recebido de acct-proximity-bridge e um TED enviado para acct-120; o cliente está a 2 saltos de cust-200, que já possui um alerta. Interpretação: Não há evidência clara de ciclagem ou fracionamento nas transações listadas; recomenda-se alerta com base apenas na proximidade a um cliente já alertado.

## Avaliação de Risco

Padrão(ões) estrutural(is) detectado(s): Proximidade a cliente já alertado.

**Tipologias detectadas:** Proximidade a cliente já alertado

## Análise via LLM (provedor: openai)

Fatos: As transações incluem depósitos em acct-122 e acct-124, pagamentos de boleto para acct-122 e acct-124, um TED recebido de acct-proximity-bridge e um TED enviado para acct-120; o cliente está a 2 saltos de cust-200, que já possui um alerta. Interpretação: Não há evidência clara de ciclagem ou fracionamento nas transações listadas; recomenda-se alerta com base apenas na proximidade a um cliente já alertado.

**Principais observações:**

- TED de 4200.00 BRL proveniente de acct-proximity-bridge.
- Depósito de 3352.81 BRL em acct-122.
- Pagamento de boleto de 5210.46 BRL para acct-124.
- Depósito de 5708.11 BRL em acct-122.
- Pagamento de boleto de 12044.29 BRL para acct-122.
- Depósito de 5141.97 BRL em acct-124.
- TED de 5275.83 BRL para acct-120.
- Conectado em até 2 salto(s) ao cliente cust-200, que já possui o alerta alert-auto-cust-200.
- Alerta existente: nenhum em arquivo para este cliente.

**Por que um alerta foi recomendado:** Gatilho de proximidade: a evidência afirma que o cliente está “Conectado em até 2 salto(s) ao cliente cust-200, que já possui o alerta alert-auto-cust-200.” Essa proximidade a um cliente já alertado justifica a sinalização.

## Evidências: Pessoas e Transações Relacionadas

| Tipo | Conta/Cliente Relacionado | Detalhes | Origem |
| --- | --- | --- | --- |
| TED | acct-proximity-bridge | Transferência TED de 4200.00 BRL de acct-proximity-bridge. | neo4j |
| Depósito | acct-122 | Depósito de 3352.81 BRL para acct-122. | neo4j |
| Boleto | acct-124 | Pagamento de boleto de 5210.46 BRL para acct-124. | neo4j |
| Depósito | acct-122 | Depósito de 5708.11 BRL para acct-122. | neo4j |
| Boleto | acct-122 | Pagamento de boleto de 12044.29 BRL para acct-122. | neo4j |
| Depósito | acct-124 | Depósito de 5141.97 BRL para acct-124. | neo4j |
| TED | acct-120 | Transferência TED de 5275.83 BRL para acct-120. | neo4j |
| Proximidade a cliente já alertado | cust-129 | Conectado em 2 salto(s) ao cliente cust-200, que já possui o alerta alert-auto-cust-200. | neo4j |

## Consulta Cypher para Visualizar Este Caso no Neo4j

Execute no Neo4j Browser (http://localhost:7474) para visualizar as contas e transações conectadas a este cliente (ajuste o número de saltos `*1..3` se necessário):

```cypher
MATCH (c:Customer {customer_id: 'cust-129'})-[:OWNS]->(acct)-[t:TRANSFERRED_TO*1..3]-(other)
RETURN c, acct, t, other;
```

Para ver apenas o nó do alerta e o cliente:

```cypher
MATCH (a:Alert {alert_id: 'alert-auto-cust-129'})-[:TARGETS]->(c:Customer) RETURN a, c;
```
