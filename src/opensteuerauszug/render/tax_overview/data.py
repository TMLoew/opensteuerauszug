"""Aggregated, CHF-normalised data model consumed by the sheet writers.

Every figure in :class:`TaxOverviewData` is already in CHF (or carries the
source amount alongside) — the boundary conversions happen upstream in
phases 2–4. Sheet writers are therefore pure: they format and lay out, they
never compute. That keeps visual regressions isolated from numerical bugs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional

from .fifo import LotClose
from .orders import Order
from .waterfall import Waterfall


@dataclass(frozen=True)
class PositionSummary:
    """One row in the Wertschriften (closing holdings) sheet."""

    isin: Optional[str]
    symbol: str
    description: str
    quantity_closing: Decimal
    currency: str
    price_closing_local: Decimal
    price_closing_chf: Decimal  # ESTV Kursliste Steuerwert per share when available
    market_value_chf: Decimal


@dataclass(frozen=True)
class IncomeEvent:
    """A dividend or interest payment, already CHF-converted for display.

    Keeping dividends and interest in the same shape (with a ``category``
    discriminator) avoids a parallel type hierarchy — they differ only in
    semantic label and in which sheet they land on.
    """

    payment_date: date
    isin: Optional[str]
    symbol: str
    description: str
    category: str  # "dividend" | "interest"
    gross_local: Decimal
    currency: str
    withholding_tax_local: Decimal
    net_local: Decimal
    gross_chf: Decimal
    withholding_tax_chf: Decimal
    net_chf: Decimal


@dataclass(frozen=True)
class FeeEvent:
    """A non-commission fee (platform, data, wire, etc.). Commissions live on Order."""

    fee_date: date
    kind: str  # "platform" | "data" | "wire" | "other"
    description: str
    amount_local: Decimal
    currency: str
    amount_chf: Decimal


@dataclass(frozen=True)
class FXRateUsed:
    """One FX rate the pipeline resolved from the Kursliste (for audit)."""

    currency: str
    reference_date: date
    rate: Decimal  # CHF per 1 unit of ``currency``
    source: str = "kursliste"


@dataclass
class TaxOverviewData:
    """Everything the sheet writers need, already CHF-normalised."""

    tax_year: int
    broker: str
    preparer_mode: bool
    opening_value_chf: Decimal
    closing_value_chf: Decimal
    waterfall: Waterfall
    positions: List[PositionSummary] = field(default_factory=list)
    orders: List[Order] = field(default_factory=list)
    lot_closes: List[LotClose] = field(default_factory=list)
    dividends: List[IncomeEvent] = field(default_factory=list)
    interest: List[IncomeEvent] = field(default_factory=list)
    fees: List[FeeEvent] = field(default_factory=list)
    fx_rates: List[FXRateUsed] = field(default_factory=list)

    def realized_pnl_chf(self) -> Decimal:
        """Total realized P&L across all FIFO closes (CHF).

        Note: LotClose amounts are in the lot's source currency. Callers that
        want CHF totals should build this via converted figures before it
        lands in the data object; this helper assumes the pipeline already
        did the conversion (phase-6 wiring).
        """
        return sum((c.realized_pnl for c in self.lot_closes), Decimal(0))

    def total_dividends_chf(self) -> Decimal:
        return sum((d.gross_chf for d in self.dividends), Decimal(0))

    def total_interest_chf(self) -> Decimal:
        return sum((i.gross_chf for i in self.interest), Decimal(0))

    def total_withholding_tax_chf(self) -> Decimal:
        return sum(
            (evt.withholding_tax_chf for evt in (*self.dividends, *self.interest)),
            Decimal(0),
        )

    def total_fees_chf(self) -> Decimal:
        fee_sum = sum((f.amount_chf for f in self.fees), Decimal(0))
        commission_sum = sum(
            (abs(o.total_commission) for o in self.orders), Decimal(0)
        )
        return fee_sum + commission_sum
