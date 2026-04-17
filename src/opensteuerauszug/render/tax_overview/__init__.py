"""Tax-overview mode: tax-authority-friendly dashboard for Kanton SG filings."""

from .cli import tax_overview_command
from .conversion import CHF, CHF_QUANTUM, MoneyCHF, sum_chf, to_chf
from .fifo import FifoError, FifoResult, Lot, LotClose, apply_orders
from .orders import DEFAULT_TIME_CLUSTER_WINDOW, Fill, Order, reconstruct_orders
from .waterfall import (
    DEFAULT_RECONCILIATION_TOLERANCE_CHF,
    Waterfall,
    WaterfallLine,
    build_waterfall,
)
from .writer import (
    ALL_FORMATS,
    OutputFormat,
    TaxOverviewRequest,
    compute_report_hash,
    parse_formats,
    write_tax_overview,
)

__all__ = [
    "ALL_FORMATS",
    "CHF",
    "CHF_QUANTUM",
    "DEFAULT_RECONCILIATION_TOLERANCE_CHF",
    "DEFAULT_TIME_CLUSTER_WINDOW",
    "FifoError",
    "FifoResult",
    "Fill",
    "Lot",
    "LotClose",
    "MoneyCHF",
    "Order",
    "OutputFormat",
    "TaxOverviewRequest",
    "Waterfall",
    "WaterfallLine",
    "apply_orders",
    "build_waterfall",
    "compute_report_hash",
    "parse_formats",
    "reconstruct_orders",
    "sum_chf",
    "tax_overview_command",
    "to_chf",
    "write_tax_overview",
]
