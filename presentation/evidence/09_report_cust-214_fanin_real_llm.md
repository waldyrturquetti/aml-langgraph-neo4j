# Relatório de Investigação de Alerta: alert-auto-cust-214

- **Cliente:** cust-214
- **Motivo:** Padrão concreto de fan-in: 5 transferências PIX distintas de acct-214-c214s5/c214s4/c214s3/c214s2/c214s1, com valores semelhantes (BRL 936,16–958,15), convergindo em cust-214, conforme 'structuring-fanin'—condizente com atividade de coleta/mula.
- **Nível de risco:** high
- **Criado em:** 2026-07-31T03:50:48.018196+00:00

## Descrição

Cinco transferências PIX distintas (BRL 936,16–958,15) de cinco contas diferentes convergiram para cust-214; um item “structuring-fanin” sinaliza esse possível padrão de mula/coletor.

## Avaliação de Risco

Padrão(ões) estrutural(is) detectado(s): Estruturação (fan-in).

**Tipologias detectadas:** Estruturação (fan-in)

## Análise via LLM (provedor: openai)

Cinco transferências PIX distintas (BRL 936,16–958,15) de cinco contas diferentes convergiram para cust-214; um item “structuring-fanin” sinaliza esse possível padrão de mula/coletor.

**Principais observações:**

- Fato: Recebeu 5 transferências PIX para cust-214 de fontes únicas: acct-214-c214s5, acct-214-c214s4, acct-214-c214s3, acct-214-c214s2, acct-214-c214s1.
- Fato: Os valores são semelhantes e próximos: BRL 936,16, 947,91, 950,84, 954,71, 958,15.
- Fato: O item de detecção 'structuring-fanin' aponta 5 entradas distintas convergindo para esta conta (possível padrão de mula/coletor).
- Interpretação: Vários valores semelhantes de remetentes diferentes convergindo para uma conta é consistente com um possível padrão de coleta/mula (fan-in).

**Por que um alerta foi recomendado:** Padrão concreto de fan-in: 5 transferências PIX distintas de acct-214-c214s5/c214s4/c214s3/c214s2/c214s1, com valores semelhantes (BRL 936,16–958,15), convergindo em cust-214, conforme 'structuring-fanin'—condizente com atividade de coleta/mula.

## Evidências: Pessoas e Transações Relacionadas

| Tipo | Conta/Cliente Relacionado | Detalhes | Origem |
| --- | --- | --- | --- |
| PIX | acct-214-c214s5 | Transferência PIX de 936.16 BRL de acct-214-c214s5. | neo4j |
| PIX | acct-214-c214s4 | Transferência PIX de 947.91 BRL de acct-214-c214s4. | neo4j |
| PIX | acct-214-c214s3 | Transferência PIX de 950.84 BRL de acct-214-c214s3. | neo4j |
| PIX | acct-214-c214s2 | Transferência PIX de 954.71 BRL de acct-214-c214s2. | neo4j |
| PIX | acct-214-c214s1 | Transferência PIX de 958.15 BRL de acct-214-c214s1. | neo4j |
| Estruturação (fan-in) | cust-214 | Detectadas 5 transferências distintas de entrada convergindo para esta conta (possível conta-laranja/coletora); amostra de origens: ['acct-214-c214s5', 'acct-214-c214s4', 'acct-214-c214s3', 'acct-214-c214s2', 'acct-214-c214s1']. | neo4j |

## Consulta Cypher para Visualizar Este Caso no Neo4j

Execute no Neo4j Browser (http://localhost:7474) para visualizar as contas e transações conectadas a este cliente (ajuste o número de saltos `*1..3` se necessário):

```cypher
MATCH (c:Customer {customer_id: 'cust-214'})-[:OWNS]->(acct)-[t:TRANSFERRED_TO*1..3]-(other)
RETURN c, acct, t, other;
```

Para ver apenas o nó do alerta e o cliente:

```cypher
MATCH (a:Alert {alert_id: 'alert-auto-cust-214'})-[:TARGETS]->(c:Customer) RETURN a, c;
```
