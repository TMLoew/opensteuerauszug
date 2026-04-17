"""Tax-overview mode: tax-authority-friendly dashboard for Kanton SG filings."""

from .cli import tax_overview_command
from .fifo import FifoError, FifoResult, Lot, LotClose, apply_orders
from .orders import DEFAULT_TIME_CLUSTER_WINDOW, Fill, Order, reconstruct_orders
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
    "DEFAULT_TIME_CLUSTER_WINDOW",
    "FifoError",
    "FifoResult",
    "Fill",
    "Lot",
    "LotClose",
    "Order",
    "OutputFormat",
    "TaxOverviewRequest",
    "apply_orders",
    "compute_report_hash",
    "parse_formats",
    "reconstruct_orders",
    "tax_overview_command",
    "write_tax_overview",
]
