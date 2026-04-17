"""Workbook-level orchestration for the tax-overview mode.

:func:`render_workbook` is the pure "data in → openpyxl.Workbook out"
function that every format writer (xlsx, html via worksheet export, PDF
cover) builds on. Order of sheet creation matches the spec's left-to-right
tab order; the KS36 hidden sheets are intentionally absent here — phase 7
adds them under the preparer-mode flag.
"""

from __future__ import annotations

from openpyxl import Workbook

from .data import TaxOverviewData
from .design import register_named_styles
from .sheets import (
    write_da1_sheet,
    write_dividends_sheet,
    write_fees_sheet,
    write_fx_rates_sheet,
    write_interest_sheet,
    write_orders_sheet,
    write_securities_sheet,
    write_uebersicht_sheet,
    write_verzeichnis_sheet,
)


def render_workbook(data: TaxOverviewData) -> Workbook:
    """Build the visible workbook from a fully-prepared :class:`TaxOverviewData`.

    Sheet order (left-to-right): Übersicht, Wertschriften, Kauf_Verkauf,
    Dividenden, Zinsen, Gebühren, FX_Kurse. Preparer-only KS36 sheets are
    appended by a separate writer in phase 7 so this orchestrator stays
    unconditional.
    """
    wb = Workbook()
    # openpyxl starts with a default "Sheet"; remove before adding ours so the
    # tab order is exactly as specified.
    default = wb.active
    wb.remove(default)

    register_named_styles(wb)

    write_uebersicht_sheet(wb, data)
    write_securities_sheet(wb, data)
    # SG-specific sheets go next — the tax clerk's reading order is
    # "what's the total?" → "which SG lines?" → "DA-1?" → transactional detail.
    write_verzeichnis_sheet(wb, data)
    write_da1_sheet(wb, data)
    write_orders_sheet(wb, data)
    write_dividends_sheet(wb, data)
    write_interest_sheet(wb, data)
    write_fees_sheet(wb, data)
    write_fx_rates_sheet(wb, data)

    return wb
