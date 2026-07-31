"""Deterministic generator for the fictional AML transaction graph.

Regenerates:
  - src/aml_alert_triage/graph_dataset.py (offline/test fixture)
  - data/neo4j/seed.cypher (live-graph rendering of the same data)

Run with `python scripts/generate_dataset.py` from anywhere; paths are
resolved relative to this file. Fixed random seed makes output
reproducible. The generator self-validates before writing anything to
disk: the 30-customer organic pool must contain no accidental cycle or
fan-out/fan-in pattern, and each of the 20 injected suspicious cases must
trigger exactly its intended typology, both checked with the same
detection functions (graph_engine.py) the live Cypher queries mirror.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aml_alert_triage.graph_engine import (  # noqa: E402
    Account,
    AlertSeed,
    Customer,
    GraphDataset,
    Transaction,
    evidence_for_customer,
)
from aml_alert_triage.llm import InsightRequest, RuleBasedLLMAdapter  # noqa: E402
from aml_alert_triage.models import HIGH_RISK_EVIDENCE_KINDS  # noqa: E402
from aml_alert_triage.repository import summarize_evidence  # noqa: E402

SEED = 20260730
CYCLE_MAX_HOPS = 6
FANOUT_THRESHOLD = 4
FANIN_THRESHOLD = 4
CHANNELS = ["pix", "boleto", "ted", "deposit"]

FIRST_NAMES = [
    "Jordan", "Taylor", "Riley", "Morgan", "Casey", "Drew", "Jamie", "Sam",
    "Avery", "Quinn", "Reese", "Rowan", "Skyler", "Emerson", "Finley",
    "Hayden", "Kendall", "Logan", "Peyton", "Sage", "Blair", "Cameron",
    "Dakota", "Elliot",
]
LAST_NAMES = [
    "Miles", "Whitfield", "Ibarra", "Reed", "Bennett", "Jarvis", "Park",
    "Cruz", "Kessler", "Ellis", "Delgado", "Lang", "Nolan", "Fenwick",
    "Mercer", "Sawyer", "Grant", "Novak", "Okafor", "Holloway", "Vance",
    "Ortega", "Pruitt", "Castillo",
]

# 20 suspicious customers split across three typologies (approximately
# even, per the project owner's request): 7 directed transfer cycles, 7
# structuring fan-outs, 6 structuring fan-ins.
CYCLE_CASE_COUNT = 7
FANOUT_CASE_COUNT = 7
FANIN_CASE_COUNT = 6
# Hop counts for the 7 cycle cases, all within Cypher's *2..CYCLE_MAX_HOPS
# range and >= 3 for a realistic (non-degenerate) directed loop.
CYCLE_HOPS = [3, 4, 5, 6, 4, 5, 3]

# Exactly 2 of the 20 suspicious customers are pre-registered with an
# Alert in the seed data; the other 18 are undiscovered until investigated.
PRE_REGISTERED_CUSTOMER_IDS = {"cust-200", "cust-207"}


def _make_names(rng: random.Random, count: int) -> list[str]:
    seen: set[tuple[str, str]] = set()
    names: list[str] = []
    while len(names) < count:
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        if (first, last) in seen:
            continue
        seen.add((first, last))
        names.append(f"{first} {last}")
    return names


def _generate_organic(rng: random.Random, start_index: int, count: int):
    ids = [f"cust-{start_index + i}" for i in range(count)]
    names = _make_names(rng, count)
    customers = [Customer(customer_id=cid, name=name) for cid, name in zip(ids, names)]
    accounts = [Account(account_id=f"acct-{cid.split('-')[1]}", customer_id=cid) for cid in ids]
    account_ids = [a.account_id for a in accounts]

    # A random topological order makes it structurally impossible for the
    # generated transactions to contain a cycle: every edge only ever goes
    # from an earlier position to a later one.
    order = account_ids[:]
    rng.shuffle(order)
    position = {aid: i for i, aid in enumerate(order)}

    counterparties: dict[str, set[str]] = {aid: set() for aid in account_ids}
    transactions: list[Transaction] = []
    target_count = count * 2
    attempts = 0
    while len(transactions) < target_count and attempts < target_count * 30:
        attempts += 1
        a, b = rng.sample(account_ids, 2)
        source, target = (a, b) if position[a] < position[b] else (b, a)

        # Cap distinct counterparties per account at 3 (below the 4-item
        # fan-out/fan-in threshold), so the organic pool can never
        # accidentally trigger structuring detection.
        if len(counterparties[source]) >= 3 and target not in counterparties[source]:
            continue
        if len(counterparties[target]) >= 3 and source not in counterparties[target]:
            continue

        channel = rng.choice(CHANNELS)
        amount = round(rng.uniform(400.0, 13000.0), 2)
        transactions.append(Transaction(source, target, channel, amount))
        counterparties[source].add(target)
        counterparties[target].add(source)

    return customers, accounts, transactions


def _generate_cycle_case(rng: random.Random, own_account: str, hops: int, case_index: int):
    intermediates = [f"{own_account}-c{case_index}h{i}" for i in range(1, hops)]
    chain = [own_account, *intermediates, own_account]
    base_amount = round(rng.uniform(8000.0, 12000.0), 2)
    transactions = [
        Transaction(chain[i], chain[i + 1], "ted", round(base_amount - i * rng.uniform(50.0, 150.0), 2))
        for i in range(len(chain) - 1)
    ]
    accounts = [Account(account_id=aid, customer_id=None) for aid in intermediates]
    return accounts, transactions


def _generate_fanout_case(rng: random.Random, own_account: str, count: int, case_index: int):
    beneficiaries = [f"{own_account}-c{case_index}b{i}" for i in range(1, count + 1)]
    base_amount = round(rng.uniform(900.0, 980.0), 2)
    transactions = [
        Transaction(own_account, ben, "pix", round(base_amount - i * rng.uniform(2.0, 8.0), 2))
        for i, ben in enumerate(beneficiaries)
    ]
    accounts = [Account(account_id=aid, customer_id=None) for aid in beneficiaries]
    return accounts, transactions


def _generate_fanin_case(rng: random.Random, own_account: str, count: int, case_index: int):
    sources = [f"{own_account}-c{case_index}s{i}" for i in range(1, count + 1)]
    base_amount = round(rng.uniform(880.0, 960.0), 2)
    transactions = [
        Transaction(src, own_account, "pix", round(base_amount - i * rng.uniform(2.0, 8.0), 2))
        for i, src in enumerate(sources)
    ]
    accounts = [Account(account_id=aid, customer_id=None) for aid in sources]
    return accounts, transactions


def generate_dataset():
    rng = random.Random(SEED)

    organic_customers, organic_accounts, organic_txns = _generate_organic(rng, start_index=100, count=30)

    suspicious_names = iter(_make_names(rng, CYCLE_CASE_COUNT + FANOUT_CASE_COUNT + FANIN_CASE_COUNT))
    suspicious_customers: list[Customer] = []
    suspicious_accounts: list[Account] = []
    suspicious_txns: list[Transaction] = []
    groups: dict[str, list[str]] = {"cycle": [], "fanout": [], "fanin": []}

    for i in range(CYCLE_CASE_COUNT):
        idx = 200 + i
        cid, own_account = f"cust-{idx}", f"acct-{idx}"
        suspicious_customers.append(Customer(cid, next(suspicious_names)))
        suspicious_accounts.append(Account(own_account, cid))
        dummies, txns = _generate_cycle_case(rng, own_account, CYCLE_HOPS[i], idx)
        suspicious_accounts.extend(dummies)
        suspicious_txns.extend(txns)
        groups["cycle"].append(cid)

    for i in range(FANOUT_CASE_COUNT):
        idx = 207 + i
        cid, own_account = f"cust-{idx}", f"acct-{idx}"
        suspicious_customers.append(Customer(cid, next(suspicious_names)))
        suspicious_accounts.append(Account(own_account, cid))
        count = 5 + (i % 2)  # 5 or 6, safely above the fan-out threshold (4)
        dummies, txns = _generate_fanout_case(rng, own_account, count, idx)
        suspicious_accounts.extend(dummies)
        suspicious_txns.extend(txns)
        groups["fanout"].append(cid)

    for i in range(FANIN_CASE_COUNT):
        idx = 214 + i
        cid, own_account = f"cust-{idx}", f"acct-{idx}"
        suspicious_customers.append(Customer(cid, next(suspicious_names)))
        suspicious_accounts.append(Account(own_account, cid))
        count = 5 + (i % 2)  # 5 or 6, safely above the fan-in threshold (4)
        dummies, txns = _generate_fanin_case(rng, own_account, count, idx)
        suspicious_accounts.extend(dummies)
        suspicious_txns.extend(txns)
        groups["fanin"].append(cid)

    groups["organic"] = [c.customer_id for c in organic_customers]

    alerts = [
        AlertSeed(
            alert_id="alert-auto-cust-200",
            customer_id="cust-200",
            reason="cycle-detected",
            description=(
                "Directed fund-transfer cycle detected returning to the originating account "
                "after periodic monitoring flagged unusual round-trip activity."
            ),
        ),
        AlertSeed(
            alert_id="alert-auto-cust-207",
            customer_id="cust-207",
            reason="structuring-fanout-detected",
            description=(
                "Multiple distinct outgoing transfers just under a reporting threshold, "
                "consistent with structuring/pulverization."
            ),
        ),
    ]

    # A deliberate demonstration case for alert-proximity detection: cust-129
    # (an otherwise-ordinary organic customer) is connected, via one
    # intermediary hop, to cust-200 - who already has a pre-registered
    # alert. Investigating cust-129 should surface `alert-proximity`
    # evidence and classify as high risk, even though cust-129's own
    # transaction graph has no cycle or structuring pattern of its own.
    # Both new edges point out of the bridge account (not out of acct-129 or
    # acct-200) specifically to avoid nudging either account's existing
    # out-degree up to the fan-out detection threshold - this case is meant
    # to demonstrate proximity detection in isolation, not accidentally
    # trigger structuring too.
    proximity_bridge_account = "acct-proximity-bridge"
    proximity_accounts = [Account(account_id=proximity_bridge_account, customer_id=None)]
    proximity_txns = [
        Transaction(proximity_bridge_account, "acct-129", "ted", 4200.0),
        Transaction(proximity_bridge_account, "acct-200", "ted", 4150.0),
    ]
    groups["proximity_demo_customer"] = "cust-129"

    customers = organic_customers + suspicious_customers
    accounts = organic_accounts + suspicious_accounts + proximity_accounts
    transactions = organic_txns + suspicious_txns + proximity_txns
    return customers, accounts, transactions, alerts, groups


def _validate(customers, accounts, transactions, groups) -> None:
    dataset = GraphDataset(customers, accounts, transactions)

    for cid in groups["organic"]:
        account_ids = dataset.account_ids(cid)
        assert dataset.detect_cycle(account_ids, CYCLE_MAX_HOPS) is None, f"unexpected cycle for organic {cid}"
        assert dataset.detect_fan(account_ids, "out", FANOUT_THRESHOLD) is None, f"unexpected fan-out for organic {cid}"
        assert dataset.detect_fan(account_ids, "in", FANIN_THRESHOLD) is None, f"unexpected fan-in for organic {cid}"

    proximity_customer = groups["proximity_demo_customer"]
    proximity_account_ids = dataset.account_ids(proximity_customer)
    links = dataset.detect_alert_proximity(
        proximity_account_ids, max_hops=3, alerted_customer_ids={"cust-200", "cust-207"}, exclude_customer_id=proximity_customer
    )
    assert links, f"expected {proximity_customer} to be within proximity range of an alerted customer"
    assert links[0][0] == "cust-200", f"expected {proximity_customer} to link to cust-200, got {links}"
    assert dataset.detect_fan(proximity_account_ids, "out", FANOUT_THRESHOLD) is None, (
        f"proximity bridge accidentally triggered fan-out for {proximity_customer}"
    )
    assert dataset.detect_fan(proximity_account_ids, "in", FANIN_THRESHOLD) is None, (
        f"proximity bridge accidentally triggered fan-in for {proximity_customer}"
    )

    for cid in groups["cycle"]:
        account_ids = dataset.account_ids(cid)
        assert dataset.detect_cycle(account_ids, CYCLE_MAX_HOPS) is not None, f"missing cycle for {cid}"

    for cid in groups["fanout"]:
        account_ids = dataset.account_ids(cid)
        assert dataset.detect_fan(account_ids, "out", FANOUT_THRESHOLD) is not None, f"missing fan-out for {cid}"

    for cid in groups["fanin"]:
        account_ids = dataset.account_ids(cid)
        assert dataset.detect_fan(account_ids, "in", FANIN_THRESHOLD) is not None, f"missing fan-in for {cid}"

    assert len(customers) == 50, f"expected 50 customers, got {len(customers)}"
    print(f"Validated {len(customers)} customers, {len(accounts)} accounts, {len(transactions)} transactions.")


def _cypher_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _emit_graph_dataset(customers, accounts, transactions, alerts, path: Path) -> None:
    lines: list[str] = []
    lines.append('"""Canonical fictional AML transaction graph (generated, deterministic).\n\n')
    lines.append(f"Generated by scripts/generate_dataset.py with a fixed random seed ({SEED}) -\n")
    lines.append("regenerating requires rerunning that script (it self-validates the organic\n")
    lines.append("pool for accidental cycles/fan patterns and confirms each injected\n")
    lines.append('suspicious case triggers its intended typology before writing anything).\n"""\n\n')
    lines.append("from __future__ import annotations\n\n")
    lines.append("from .graph_engine import Account, AlertSeed, Customer, GraphDataset, Transaction\n\n")

    lines.append("CUSTOMERS: list[Customer] = [\n")
    for c in customers:
        lines.append(f"    Customer(customer_id={c.customer_id!r}, name={c.name!r}),\n")
    lines.append("]\n\n")

    lines.append("ACCOUNTS: list[Account] = [\n")
    for a in accounts:
        lines.append(f"    Account(account_id={a.account_id!r}, customer_id={a.customer_id!r}),\n")
    lines.append("]\n\n")

    lines.append("TRANSACTIONS: list[Transaction] = [\n")
    for t in transactions:
        lines.append(
            f"    Transaction({t.source_account_id!r}, {t.target_account_id!r}, {t.channel!r}, {t.amount!r}),\n"
        )
    lines.append("]\n\n")

    lines.append("ALERTS: list[AlertSeed] = [\n")
    for al in alerts:
        lines.append(
            f"    AlertSeed(alert_id={al.alert_id!r}, customer_id={al.customer_id!r}, "
            f"reason={al.reason!r}, description={al.description!r}),\n"
        )
    lines.append("]\n\n")

    lines.append("DATASET = GraphDataset(CUSTOMERS, ACCOUNTS, TRANSACTIONS)\n")
    path.write_text("".join(lines), encoding="utf-8")


def _emit_seed_cypher(customers, accounts, transactions, alerts, path: Path) -> None:
    lines: list[str] = []
    lines.append("// Generated by scripts/generate_dataset.py - do not edit by hand.\n\n")

    lines.append("// Customers\n")
    for c in customers:
        lines.append(f"MERGE (:Customer {{customer_id: '{c.customer_id}', name: '{_cypher_escape(c.name)}'}});\n")

    lines.append("\n// Accounts\n")
    for a in accounts:
        if a.customer_id:
            lines.append(
                f"MATCH (cust:Customer {{customer_id: '{a.customer_id}'}}) "
                f"MERGE (acct:Account {{account_id: '{a.account_id}'}}) "
                "MERGE (cust)-[:OWNS]->(acct);\n"
            )
        else:
            lines.append(f"MERGE (:Account {{account_id: '{a.account_id}'}});\n")

    lines.append("\n// Transactions\n")
    for t in transactions:
        lines.append(
            f"MATCH (src:Account {{account_id: '{t.source_account_id}'}}), "
            f"(tgt:Account {{account_id: '{t.target_account_id}'}}) "
            f"MERGE (src)-[:TRANSFERRED_TO {{channel: '{t.channel}', amount: {t.amount}, "
            f"currency: '{t.currency}'}}]->(tgt);\n"
        )

    lines.append("\n// Pre-registered alerts\n")
    for al in alerts:
        var = al.alert_id.replace("-", "_")
        lines.append(
            f"MERGE ({var}:Alert {{alert_id: '{al.alert_id}', reason: '{_cypher_escape(al.reason)}', "
            f"description: '{_cypher_escape(al.description)}'}});\n"
        )
        lines.append(
            f"MATCH ({var}:Alert {{alert_id: '{al.alert_id}'}}), (cust:Customer {{customer_id: '{al.customer_id}'}}) "
            f"MERGE ({var})-[:TARGETS]->(cust);\n"
        )

    path.write_text("".join(lines), encoding="utf-8")


def _build_dynamodb_seed(customers, accounts, transactions, alerts: list[AlertSeed]) -> list[dict]:
    """Snapshots for the pre-registered alerts, derived with the same
    rule-based (static) evidence logic register_alert would have used had
    these been created by an investigation run, so the seeded data is
    consistent with what the workflow itself produces."""
    dataset = GraphDataset(customers, accounts, transactions)
    adapter = RuleBasedLLMAdapter(provider="rule-based", model="local-insight-summarizer")

    snapshots = []
    for seed in alerts:
        evidence = evidence_for_customer(
            dataset,
            seed.customer_id,
            hop_radius=2,
            cycle_max_hops=CYCLE_MAX_HOPS,
            fanout_threshold=FANOUT_THRESHOLD,
            fanin_threshold=FANIN_THRESHOLD,
        )
        evidence_summary = summarize_evidence(evidence)
        typologies = sorted({e.kind for e in evidence if e.kind in HIGH_RISK_EVIDENCE_KINDS})
        if typologies:
            risk_level = "high"
            risk_rationale = "Structural graph pattern(s) detected: " + ", ".join(typologies) + "."
        elif evidence:
            risk_level = "elevated"
            risk_rationale = "Connected evidence was found but no high-risk structural pattern was detected."
        else:
            risk_level = "low"
            risk_rationale = "No connected evidence was found."

        request = InsightRequest(
            customer_id=seed.customer_id,
            user_prompt="",
            evidence=evidence,
            evidence_summary=evidence_summary,
            existing_alert=None,
        )
        response = adapter.generate_insights(request)

        snapshots.append(
            {
                "alert_id": seed.alert_id,
                "customer_id": seed.customer_id,
                # The snapshot's reason/description/insight_* fields feed the
                # Portuguese report (report.py); Neo4j's Alert.reason/
                # description (seed.reason/seed.description, from
                # data/neo4j/seed.cypher) stay in English, mirroring what
                # register_alert does for alerts created at runtime.
                "reason": response.alert_reason_pt or seed.reason,
                "description": response.summary_pt or seed.description,
                "evidence": [
                    {"kind": e.kind, "subject": e.subject, "details": e.details, "source": e.source}
                    for e in evidence
                ],
                "risk": {"level": risk_level, "rationale": risk_rationale, "typologies": typologies},
                "insight_mode": "static",
                "insight_summary": response.summary_pt,
                "insight_key_observations": response.key_observations_pt,
                "alert_reason": response.alert_reason_pt,
                "created_at": "2026-07-30T00:00:00+00:00",
            }
        )
    return snapshots


def _emit_dynamodb_seed(snapshots: list[dict], path: Path) -> None:
    path.write_text(json.dumps(snapshots, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    customers, accounts, transactions, alerts, groups = generate_dataset()
    _validate(customers, accounts, transactions, groups)

    graph_dataset_path = REPO_ROOT / "src" / "aml_alert_triage" / "graph_dataset.py"
    seed_cypher_path = REPO_ROOT / "data" / "neo4j" / "seed.cypher"
    dynamodb_seed_path = REPO_ROOT / "data" / "dynamodb" / "seed.json"

    _emit_graph_dataset(customers, accounts, transactions, alerts, graph_dataset_path)
    _emit_seed_cypher(customers, accounts, transactions, alerts, seed_cypher_path)

    dynamodb_seed = _build_dynamodb_seed(customers, accounts, transactions, alerts)
    _emit_dynamodb_seed(dynamodb_seed, dynamodb_seed_path)

    print(f"Wrote {graph_dataset_path}")
    print(f"Wrote {seed_cypher_path}")
    print(f"Wrote {dynamodb_seed_path}")


if __name__ == "__main__":
    main()
