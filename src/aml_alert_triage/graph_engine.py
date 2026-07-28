"""Pure-Python graph pattern detection over the canonical fictional dataset.

This mirrors the Cypher queries in repository.py exactly (same traversal
roots, same hop semantics, same cycle/fan-out/fan-in definitions) so the
offline/test code path is a real reimplementation of the live Neo4j query
logic, not a hand-maintained set of fixtures that can silently drift from
what the live queries actually compute.
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

    def second_hop_transactions(self, account_ids: set[str]) -> tuple[set[str], list[Transaction]]:
        """Returns (pivot_account_ids, transactions) - the direct counterparties'
        *other* transactions. Callers must describe these transactions relative
        to the returned pivot set, not to `account_ids` - none of these
        transactions touch `account_ids` at all (that's the point), so framing
        them from the original account's perspective would be meaningless."""
        direct = self.direct_transactions(account_ids)
        pivots = {
            (t.target_account_id if t.source_account_id in account_ids else t.source_account_id) for t in direct
        }
        pivots -= account_ids
        transactions = [
            t
            for t in self.direct_transactions(pivots)
            if t.source_account_id not in account_ids and t.target_account_id not in account_ids
        ]
        return pivots, transactions

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


def evidence_for_customer(
    dataset: GraphDataset,
    customer_id: str,
    hop_radius: int,
    cycle_max_hops: int,
    fanout_threshold: int,
    fanin_threshold: int,
) -> list[EvidenceItem]:
    """Mirrors repository.py's `_fetch_evidence_from_neo4j` exactly, but as a
    pure-Python computation over the in-memory dataset - this is what the
    offline/test code path calls, so offline behavior is a real
    reimplementation of the live query logic rather than hand-maintained
    fixtures that can drift from what the live Cypher actually computes.
    """
    account_ids = dataset.account_ids(customer_id)

    evidence = evidence_from_transactions(dataset.direct_transactions(account_ids), account_ids)
    if hop_radius >= 2:
        pivots, second_hop_txns = dataset.second_hop_transactions(account_ids)
        evidence.extend(evidence_from_transactions(second_hop_txns, pivots))

    evidence.extend(cycle_evidence(dataset, account_ids, cycle_max_hops))
    evidence.extend(structuring_evidence(dataset, account_ids, fanout_threshold, fanin_threshold))
    return evidence
