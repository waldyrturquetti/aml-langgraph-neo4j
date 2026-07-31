# Relatório de Investigação de Alerta: alert-auto-cust-207

- **Cliente:** cust-207
- **Motivo:** Padrão(ões) estrutural(is) detectado(s): Estruturação (fan-out).
- **Nível de risco:** high
- **Criado em:** 2026-07-30T00:00:00+00:00

## Descrição

As evidências indicam atividade conectada para o cliente cust-207; a revisão do analista deve priorizar partes relacionadas e transações repetidas.

## Avaliação de Risco

Padrão(ões) estrutural(is) detectado(s): Estruturação (fan-out).

**Tipologias detectadas:** Estruturação (fan-out)

## Análise estática (baseada em regras)

As evidências indicam atividade conectada para o cliente cust-207; a revisão do analista deve priorizar partes relacionadas e transações repetidas.

**Principais observações:**

- Analisados 6 item(ns) de evidência relacionados.
- Resumo principal da evidência: Transferência PIX de 939.42 BRL para acct-207-c207b1.; Transferência PIX de 936.90 BRL para acct-207-c207b2.; Transferência PIX de 927.88 BRL para acct-207-c207b3.; Transferência PIX de 932.29 BRL para acct-207-c207b4.; Transferência PIX de 926.98 BRL para acct-207-c207b5.; Detectadas 5 transferências distintas de saída (possível estruturação/pulverização); amostra de beneficiários: ['acct-207-c207b1', 'acct-207-c207b2', 'acct-207-c207b3', 'acct-207-c207b4', 'acct-207-c207b5'].

**Por que um alerta foi recomendado:** Padrão(ões) estrutural(is) detectado(s): Estruturação (fan-out).

## Evidências: Pessoas e Transações Relacionadas

| Tipo | Conta/Cliente Relacionado | Detalhes | Origem |
| --- | --- | --- | --- |
| PIX | acct-207-c207b1 | Transferência PIX de 939.42 BRL para acct-207-c207b1. | neo4j |
| PIX | acct-207-c207b2 | Transferência PIX de 936.90 BRL para acct-207-c207b2. | neo4j |
| PIX | acct-207-c207b3 | Transferência PIX de 927.88 BRL para acct-207-c207b3. | neo4j |
| PIX | acct-207-c207b4 | Transferência PIX de 932.29 BRL para acct-207-c207b4. | neo4j |
| PIX | acct-207-c207b5 | Transferência PIX de 926.98 BRL para acct-207-c207b5. | neo4j |
| Estruturação (fan-out) | acct-207 | Detectadas 5 transferências distintas de saída (possível estruturação/pulverização); amostra de beneficiários: ['acct-207-c207b1', 'acct-207-c207b2', 'acct-207-c207b3', 'acct-207-c207b4', 'acct-207-c207b5']. | neo4j |

## Consulta Cypher para Visualizar Este Caso no Neo4j

Execute no Neo4j Browser (http://localhost:7474) para visualizar as contas e transações conectadas a este cliente (ajuste o número de saltos `*1..3` se necessário):

```cypher
MATCH (c:Customer {customer_id: 'cust-207'})-[:OWNS]->(acct)-[t:TRANSFERRED_TO*1..3]-(other)
RETURN c, acct, t, other;
```

Para ver apenas o nó do alerta e o cliente:

```cypher
MATCH (a:Alert {alert_id: 'alert-auto-cust-207'})-[:TARGETS]->(c:Customer) RETURN a, c;
```
