"""Per-sheet writers for the tax-overview workbook.

Each module owns exactly one sheet; orchestration lives in :mod:`..render`.
Sheets are pure functions: they take a :class:`TaxOverviewData` and mutate a
:class:`openpyxl.Workbook`, never performing arithmetic of their own. This
separation keeps visual regressions (column widths, styling) isolated from
numerical regressions (waterfall, FIFO).
"""

from .fees import write_fees_sheet
from .fx import write_fx_rates_sheet
from .income import write_dividends_sheet, write_interest_sheet
from .orders_sheet import write_orders_sheet
from .securities import write_securities_sheet
from .uebersicht import write_uebersicht_sheet

__all__ = [
    "write_dividends_sheet",
    "write_fees_sheet",
    "write_fx_rates_sheet",
    "write_interest_sheet",
    "write_orders_sheet",
    "write_securities_sheet",
    "write_uebersicht_sheet",
]
