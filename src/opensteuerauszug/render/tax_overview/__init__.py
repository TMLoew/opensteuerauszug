"""Tax-overview mode: tax-authority-friendly dashboard for Kanton SG filings."""

from .cli import tax_overview_command
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
    "OutputFormat",
    "TaxOverviewRequest",
    "compute_report_hash",
    "parse_formats",
    "tax_overview_command",
    "write_tax_overview",
]
