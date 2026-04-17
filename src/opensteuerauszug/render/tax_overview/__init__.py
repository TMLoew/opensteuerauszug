"""Tax-overview mode: tax-authority-friendly dashboard for Kanton SG filings."""

from .cli import tax_overview_command
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
    "Fill",
    "Order",
    "OutputFormat",
    "TaxOverviewRequest",
    "compute_report_hash",
    "parse_formats",
    "reconstruct_orders",
    "tax_overview_command",
    "write_tax_overview",
]
