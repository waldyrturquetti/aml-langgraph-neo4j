// Fictional AML demo graph seed data.
// Safe to run multiple times because all writes use MERGE.

MERGE (c100:Customer {customer_id: 'cust-100', name: 'Jordan Miles'})
MERGE (c101:Customer {customer_id: 'cust-101', name: 'Taylor Reed'})
MERGE (c200:Customer {customer_id: 'cust-200', name: 'Riley Park'})
MERGE (a001:Account {account_id: 'acct-001', type: 'checking'})
MERGE (a777:Account {account_id: 'acct-777', type: 'savings'})
MERGE (alert1:Alert {alert_id: 'alert-001', alert_type: 'cash-structuring'})
MERGE (alert2:Alert {alert_id: 'alert-002', alert_type: 'new-beneficiary'})
MERGE (txn1:Transaction {txn_id: 'txn-1001', amount: 2500.0, currency: 'USD'})
MERGE (txn2:Transaction {txn_id: 'txn-1002', amount: 2600.0, currency: 'USD'})

MERGE (c100)-[:OWNS {note: 'Primary account holder'}]->(a001)
MERGE (c101)-[:OWNS {note: 'Secondary account holder'}]->(a001)
MERGE (c100)-[:RELATED_TO {note: 'Shared address with prior alert customer'}]-(c101)
MERGE (alert1)-[:TARGETS {note: 'Alert targets customer cust-100'}]->(c100)
MERGE (c100)-[:SENT {note: 'High velocity cash transfer'}]->(txn1)
MERGE (c100)-[:SENT {note: 'Additional structured transfer'}]->(txn2)
MERGE (txn1)-[:COUNTERPARTY {note: 'Transfer to beneficiary account'}]->(a777)

// Disconnected scenario for negative evidence path.
MERGE (alert2)-[:TARGETS {note: 'Alert targets customer cust-200'}]->(c200)
