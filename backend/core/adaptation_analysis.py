"""
Ghost Protocol — Adaptation Analysis

Computes evidence that a follow-up attack wave materially changed after the
defender caught part of the previous round. This is the backend proof that the
attacker is actually adapting, not just triggering a UI banner.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend.data.models import Transaction, TransactionType


class AdaptationEvidence(BaseModel):
    verified: bool
    summary: str
    changed_signals: list[str] = Field(default_factory=list)
    previous_round_attack_count: int
    next_round_attack_count: int
    avg_amount_before: float
    avg_amount_after: float
    avg_amount_delta_pct: float
    merchant_overlap_ratio: float
    category_overlap_ratio: float
    foreign_ratio_before: float
    foreign_ratio_after: float
    transfer_ratio_before: float
    transfer_ratio_after: float
    micro_ratio_before: float
    micro_ratio_after: float


def analyze_round_adaptation(
    previous_attacks: list[Transaction],
    next_attacks: list[Transaction],
) -> AdaptationEvidence:
    if not previous_attacks or not next_attacks:
        return AdaptationEvidence(
            verified=False,
            summary="Not enough attack data to verify adaptation yet.",
            previous_round_attack_count=len(previous_attacks),
            next_round_attack_count=len(next_attacks),
            avg_amount_before=_average_amount(previous_attacks),
            avg_amount_after=_average_amount(next_attacks),
            avg_amount_delta_pct=0.0,
            merchant_overlap_ratio=0.0,
            category_overlap_ratio=0.0,
            foreign_ratio_before=_foreign_ratio(previous_attacks),
            foreign_ratio_after=_foreign_ratio(next_attacks),
            transfer_ratio_before=_transfer_ratio(previous_attacks),
            transfer_ratio_after=_transfer_ratio(next_attacks),
            micro_ratio_before=_micro_ratio(previous_attacks),
            micro_ratio_after=_micro_ratio(next_attacks),
        )

    avg_before = _average_amount(previous_attacks)
    avg_after = _average_amount(next_attacks)
    avg_delta_pct = 0.0 if avg_before <= 0 else ((avg_after - avg_before) / avg_before) * 100.0
    merchant_overlap = _jaccard_overlap(
        {transaction.merchant for transaction in previous_attacks},
        {transaction.merchant for transaction in next_attacks},
    )
    category_overlap = _jaccard_overlap(
        {transaction.category for transaction in previous_attacks},
        {transaction.category for transaction in next_attacks},
    )
    foreign_before = _foreign_ratio(previous_attacks)
    foreign_after = _foreign_ratio(next_attacks)
    transfer_before = _transfer_ratio(previous_attacks)
    transfer_after = _transfer_ratio(next_attacks)
    micro_before = _micro_ratio(previous_attacks)
    micro_after = _micro_ratio(next_attacks)

    changed_signals: list[str] = []
    if abs(avg_delta_pct) >= 20.0:
        direction = "dropped" if avg_delta_pct < 0 else "rose"
        changed_signals.append(f"average amount {direction} {abs(avg_delta_pct):.0f}%")
    if merchant_overlap <= 0.6:
        changed_signals.append(f"merchant overlap fell to {merchant_overlap:.0%}")
    if category_overlap <= 0.6:
        changed_signals.append(f"category overlap fell to {category_overlap:.0%}")
    if abs(foreign_after - foreign_before) >= 0.3:
        changed_signals.append(
            f"foreign-location share shifted from {foreign_before:.0%} to {foreign_after:.0%}"
        )
    if abs(transfer_after - transfer_before) >= 0.3:
        changed_signals.append(
            f"transfer-style activity shifted from {transfer_before:.0%} to {transfer_after:.0%}"
        )
    if abs(micro_after - micro_before) >= 0.3:
        changed_signals.append(
            f"micro-transaction share shifted from {micro_before:.0%} to {micro_after:.0%}"
        )

    verified = bool(changed_signals)
    summary = (
        "Verified adaptation: " + "; ".join(changed_signals[:4]) + "."
        if verified
        else "No material pattern shift was detected between attack rounds."
    )

    return AdaptationEvidence(
        verified=verified,
        summary=summary,
        changed_signals=changed_signals,
        previous_round_attack_count=len(previous_attacks),
        next_round_attack_count=len(next_attacks),
        avg_amount_before=round(avg_before, 2),
        avg_amount_after=round(avg_after, 2),
        avg_amount_delta_pct=round(avg_delta_pct, 2),
        merchant_overlap_ratio=round(merchant_overlap, 4),
        category_overlap_ratio=round(category_overlap, 4),
        foreign_ratio_before=round(foreign_before, 4),
        foreign_ratio_after=round(foreign_after, 4),
        transfer_ratio_before=round(transfer_before, 4),
        transfer_ratio_after=round(transfer_after, 4),
        micro_ratio_before=round(micro_before, 4),
        micro_ratio_after=round(micro_after, 4),
    )


def _average_amount(transactions: list[Transaction]) -> float:
    if not transactions:
        return 0.0
    return sum(transaction.amount for transaction in transactions) / len(transactions)


def _jaccard_overlap(before: set[str], after: set[str]) -> float:
    union = before | after
    if not union:
        return 0.0
    return len(before & after) / len(union)


def _foreign_ratio(transactions: list[Transaction]) -> float:
    if not transactions:
        return 0.0
    foreign_count = sum(1 for transaction in transactions if transaction.location_country != "Canada")
    return foreign_count / len(transactions)


def _transfer_ratio(transactions: list[Transaction]) -> float:
    if not transactions:
        return 0.0
    count = sum(
        1
        for transaction in transactions
        if transaction.transaction_type in (TransactionType.TRANSFER, TransactionType.WITHDRAWAL)
    )
    return count / len(transactions)


def _micro_ratio(transactions: list[Transaction]) -> float:
    if not transactions:
        return 0.0
    return sum(1 for transaction in transactions if transaction.amount < 50.0) / len(transactions)
