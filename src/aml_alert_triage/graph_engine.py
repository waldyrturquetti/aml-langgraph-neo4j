"""Pure-Python graph pattern detection over the canonical fictional dataset.

This mirrors the Cypher queries in repository.py exactly (same traversal
roots, same hop semantics, same cycle/fan-out/fan-in/proximity definitions)
so the offline/test code path is a real reimplementation of the live Neo4j
query logic, not a hand-maintained set of fixtures that can silently drift
from what Neo4j actually computes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .models import EvidenceItem

_CHANNEL_VERBS = {
    "pix": "PIX transfer",
    "boleto": "Boleto payment",
    "ted": "TED transfer",
    "deposit": "Deposit",
}


@dataclass(frozen=True, slots=True)
class Customer:
    customer_id: str
    name: str


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    customer_id: str | None
    type: str = "checking"


@dataclass(frozen=True, slots=True)
class Transaction:
    source_account_id: str
    target_account_id: str
    channel: str
    amount: float
    currency: str = "BRL"


@dataclass(frozen=True, slots=True)
class AlertSeed:
    """A pre-registered `Alert` seeded into the fictional dataset, mirrored
    as both an offline fixture (here) and a live `MERGE (:Alert)-[:TARGETS]->`
    statement in data/neo4j/seed.cypher, so the two paths never drift."""

    alert_id: str
    customer_id: str
    reason: str
    description: str


class GraphDataset:
    """Indexes customers/accounts/transactions for fast pattern queries."""

    def __init__(
        self,
        customers: list[Customer],
        accounts: list[Account],
        transactions: list[Transaction],
    ) -> None:
        self.customers = customers
        self.accounts = accounts
        self.transactions = transactions
        self._accounts_by_customer: dict[str, list[str]] = {}
        for account in accounts:
            if account.customer_id is not None:
                self._accounts_by_customer.setdefault(account.customer_id, []).append(account.account_id)
        self._outgoing: dict[str, list[Transaction]] = {}
        self._incoming: dict[str, list[Transaction]] = {}
        for txn in transactions:
            self._outgoing.setdefault(txn.source_account_id, []).append(txn)
            self._incoming.setdefault(txn.target_account_id, []).append(txn)

    def account_ids(self, customer_id: str) -> set[str]:
        return set(self._accounts_by_customer.get(customer_id, []))

    def direct_transactions(self, account_ids: set[str]) -> list[Transaction]:
        seen: list[Transaction] = []
        for account_id in account_ids:
            seen.extend(self._outgoing.get(account_id, []))
            seen.extend(self._incoming.get(account_id, []))
        return seen

    def frontier_hop_transactions(
        self, frontier: set[str], visited: set[str]
    ) -> tuple[set[str], list[Transaction]]:
        """One hop of frontier-expansion BFS: transactions touching
        `frontier` whose far end has not already been visited. Returns
        (new_frontier, transactions) - the transactions are this hop's
        evidence, and `new_frontier` becomes the next hop's starting point.

        Excluding already-visited far ends (which includes the original
        `frontier` seed accounts from hop 1 onward) is what stops a later
        hop from re-reporting a transaction back to an already-seen account
        as if it were new evidence - the same exclusion the original
        hard-coded 2-hop query applied (`WHERE related <> account`),
        generalized to arbitrary hop depth.
        """
        raw = self.direct_transactions(frontier)
        seen_keys: set[tuple[str, str, str, float]] = set()
        new_frontier: set[str] = set()
        transactions: list[Transaction] = []
        for txn in raw:
            key = (txn.source_account_id, txn.target_account_id, txn.channel, txn.amount)
            if key in seen_keys:
                continue
            other = txn.target_account_id if txn.source_account_id in frontier else txn.source_account_id
            if other in visited:
                continue
            seen_keys.add(key)
            transactions.append(txn)
            new_frontier.add(other)
        return new_frontier, transactions

    def detect_cycle(self, account_ids: set[str], max_hops: int) -> int | None:
        best: int | None = None
        for start in account_ids:
            hops = self._shortest_cycle(start, max_hops)
            if hops is not None and (best is None or hops < best):
                best = hops
        return best

    def _shortest_cycle(self, start: str, max_hops: int) -> int | None:
        queue: deque[tuple[str, int]] = deque((n, 1) for n in self._targets_of(start))
        visited: set[str] = set()
        while queue:
            node, depth = queue.popleft()
            if node == start and depth >= 2:
                return depth
            if depth >= max_hops or node in visited:
                continue
            visited.add(node)
            for nxt in self._targets_of(node):
                queue.append((nxt, depth + 1))
        return None

    def _targets_of(self, account_id: str) -> list[str]:
        return [t.target_account_id for t in self._outgoing.get(account_id, [])]

    def detect_fan(
        self, account_ids: set[str], direction: str, threshold: int
    ) -> tuple[int, list[str]] | None:
        if direction == "out":
            counterparties = {
                t.target_account_id for aid in account_ids for t in self._outgoing.get(aid, [])
            }
        else:
            counterparties = {
                t.source_account_id for aid in account_ids for t in self._incoming.get(aid, [])
            }
        if len(counterparties) < threshold:
            return None
        return len(counterparties), sorted(counterparties)[:5]

    def detect_alert_proximity(
        self, account_ids: set[str], max_hops: int, alerted_customer_ids: set[str], exclude_customer_id: str
    ) -> list[tuple[str, int]]:
        """BFS outward from `account_ids` up to `max_hops`, returning
        (linked_customer_id, hop_distance) for every other customer reached
        who is a member of `alerted_customer_ids` - i.e. already has an
        alert. Mirrors repository.py's `_fetch_alert_proximity_evidence`."""
        frontier = set(account_ids)
        visited = set(account_ids)
        found: dict[str, int] = {}
        for hop in range(1, max_hops + 1):
            new_frontier, _ = self.frontier_hop_transactions(frontier, visited)
            for account_id in new_frontier:
                owner = self._customer_of(account_id)
                if owner and owner != exclude_customer_id and owner in alerted_customer_ids and owner not in found:
                    found[owner] = hop
            visited |= new_frontier
            if not new_frontier:
                break
            frontier = new_frontier
        return sorted(found.items(), key=lambda item: item[1])

    def _customer_of(self, account_id: str) -> str | None:
        for account in self.accounts:
            if account.account_id == account_id:
                return account.customer_id
        return None


def format_transaction_details(channel: str, amount: float, currency: str, direction: str, counterparty: str) -> str:
    """Single source of truth for evidence text, shared by the live Cypher-record
    mapper (repository.py) and the offline engine below, so the two paths never
    silently drift into describing the same transaction differently."""
    verb = _CHANNEL_VERBS.get(channel, "Transfer")
    preposition = "to" if direction == "to" else "from"
    return f"{verb} of {amount:.2f} {currency} {preposition} {counterparty}."


def describe_transaction(txn: Transaction, own_account_ids: set[str]) -> tuple[str, str]:
    """Returns (subject_account_id, human-readable details) for an evidence item."""
    if txn.source_account_id in own_account_ids:
        counterparty, direction = txn.target_account_id, "to"
    else:
        counterparty, direction = txn.source_account_id, "from"
    details = format_transaction_details(txn.channel, txn.amount, txn.currency, direction, counterparty)
    return counterparty, details


def evidence_from_transactions(
    transactions: list[Transaction], own_account_ids: set[str], detail_suffix: str = ""
) -> list[EvidenceItem]:
    items = []
    for txn in transactions:
        subject, details = describe_transaction(txn, own_account_ids)
        items.append(
            EvidenceItem(kind=txn.channel, subject=subject, details=details + detail_suffix, source="neo4j")
        )
    return items


def hop_evidence(dataset: GraphDataset, own_account_ids: set[str], max_hop: int) -> list[EvidenceItem]:
    """Frontier-expansion BFS outward from `own_account_ids`, up to
    `max_hop` hops, describing each hop's transactions relative to that
    hop's own frontier. A faithful reimplementation of repository.py's
    per-hop Cypher queries, generalizing what used to be two hard-coded
    hop-1/hop-2 cases to arbitrary depth."""
    frontier = set(own_account_ids)
    visited = set(own_account_ids)
    evidence: list[EvidenceItem] = []
    for _ in range(max_hop):
        new_frontier, transactions = dataset.frontier_hop_transactions(frontier, visited)
        evidence.extend(evidence_from_transactions(transactions, frontier))
        visited |= new_frontier
        if not new_frontier:
            break
        frontier = new_frontier
    return evidence


def cycle_evidence(dataset: GraphDataset, account_ids: set[str], max_hops: int) -> list[EvidenceItem]:
    hops = dataset.detect_cycle(account_ids, max_hops)
    if hops is None:
        return []
    return [
        EvidenceItem(
            kind="cycle",
            subject=next(iter(account_ids)) if account_ids else "unknown",
            details=(
                f"Detected a directed fund-transfer cycle spanning {hops} hop(s) that returns to "
                "the originating account."
            ),
            source="neo4j",
        )
    ]


def structuring_evidence(
    dataset: GraphDataset, account_ids: set[str], fanout_threshold: int, fanin_threshold: int
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []

    fanout = dataset.detect_fan(account_ids, "out", fanout_threshold)
    if fanout is not None:
        count, sample = fanout
        items.append(
            EvidenceItem(
                kind="structuring-fanout",
                subject=next(iter(account_ids)) if account_ids else "unknown",
                details=(
                    f"Detected {count} distinct outgoing transfers (possible structuring/"
                    f"pulverization); sample beneficiaries: {sample}."
                ),
                source="neo4j",
            )
        )

    fanin = dataset.detect_fan(account_ids, "in", fanin_threshold)
    if fanin is not None:
        count, sample = fanin
        items.append(
            EvidenceItem(
                kind="structuring-fanin",
                subject=next(iter(account_ids)) if account_ids else "unknown",
                details=(
                    f"Detected {count} distinct incoming transfers converging onto this account "
                    f"(possible mule/collector pattern); sample sources: {sample}."
                ),
                source="neo4j",
            )
        )

    return items


def alert_proximity_evidence(
    dataset: GraphDataset,
    account_ids: set[str],
    max_hops: int,
    alerted_customer_ids: set[str],
    exclude_customer_id: str,
    alert_ids_by_customer: dict[str, str],
) -> list[EvidenceItem]:
    links = dataset.detect_alert_proximity(account_ids, max_hops, alerted_customer_ids, exclude_customer_id)
    items: list[EvidenceItem] = []
    for linked_customer_id, hops in links:
        linked_alert_id = alert_ids_by_customer.get(linked_customer_id, "unknown")
        items.append(
            EvidenceItem(
                kind="alert-proximity",
                subject=exclude_customer_id,
                details=(
                    f"Connected within {hops} hop(s) to customer {linked_customer_id}, "
                    f"who already has alert {linked_alert_id}."
                ),
                source="neo4j",
            )
        )
    return items


def evidence_for_customer(
    dataset: GraphDataset,
    customer_id: str,
    hop_radius: int,
    cycle_max_hops: int,
    fanout_threshold: int,
    fanin_threshold: int,
    alert_proximity_max_hops: int = 0,
    alerted_customer_ids: set[str] | None = None,
    alert_ids_by_customer: dict[str, str] | None = None,
) -> list[EvidenceItem]:
    """Mirrors repository.py's `_fetch_evidence_from_neo4j` exactly, but as a
    pure-Python computation over the in-memory dataset - this is what the
    offline/test code path calls, so offline behavior is a real
    reimplementation of the live query logic rather than hand-maintained
    fixtures that can drift from what the live Cypher actually computes.
    """
    account_ids = dataset.account_ids(customer_id)

    evidence = hop_evidence(dataset, account_ids, max(hop_radius, 1))
    evidence.extend(cycle_evidence(dataset, account_ids, cycle_max_hops))
    evidence.extend(structuring_evidence(dataset, account_ids, fanout_threshold, fanin_threshold))
    if alert_proximity_max_hops > 0 and alerted_customer_ids:
        evidence.extend(
            alert_proximity_evidence(
                dataset,
                account_ids,
                alert_proximity_max_hops,
                alerted_customer_ids,
                customer_id,
                alert_ids_by_customer or {},
            )
        )
    return evidence
