"""Performance sheet: per-position P&L, sector / currency splits, benchmarks.

Consumes the pre-computed :class:`PerformanceSection` on
:class:`TaxOverviewData`; all arithmetic lives in the pipeline.  When no
performance payload is attached (e.g. preparer tests that stub the
pipeline) the sheet is skipped entirely rather than emitting an empty tab,
so downstream consumers don't see a placeholder.
"""

from __future__ import annotations

from decimal import Decimal

from openpyxl.workbook import Workbook

from ..data import TaxOverviewData
from ..design import StyleName
from ._common import apply_column_widths, freeze_header, write_header_row


SHEET_NAME = "Performance"

ZERO = Decimal("0")
HUNDRED = Decimal("100")


def write_performance_sheet(workbook: Workbook, data: TaxOverviewData) -> None:
    perf = data.performance
    if perf is None:
        return

    ws = workbook.create_sheet(SHEET_NAME)
    apply_column_widths(
        ws,
        [14, 14, 40, 20, 10, 14, 14, 14, 14, 14, 14, 14, 14, 10],
    )

    row = _write_summary(ws, perf, start_row=1)
    row += 1
    row = _write_positions_table(ws, perf, start_row=row)
    row += 2
    row = _write_allocation_table(
        ws, perf.sectors, title="Sektor-Aggregation", start_row=row,
    )
    row += 2
    row = _write_allocation_table(
        ws, perf.currencies, title="Währungs-Aggregation", start_row=row,
    )
    if perf.benchmarks:
        row += 2
        _write_benchmarks_table(ws, perf, start_row=row)


def _write_summary(ws, perf, *, start_row: int) -> int:
    summary = perf.summary
    tiles = [
        ("Eröffnungswert (CHF)", summary.opening_value_chf),
        ("Schlusswert (CHF)", summary.closing_value_chf),
        ("Netto-Einzahlungen (CHF)", summary.net_deposits_chf),
        ("Gesamt-P&L (CHF)", summary.total_pnl_chf),
        ("Dividenden (CHF)", summary.dividends_chf),
        ("Zinsen (CHF)", summary.interest_chf),
        ("Gebühren (CHF)", summary.fees_chf),
        ("Rendite Modified Dietz (%)", _pct_or_none(summary.money_weighted_return_pct)),
        ("Rendite einfach (%)", _pct_or_none(summary.simple_return_pct)),
    ]
    for offset, (label, value) in enumerate(tiles):
        row = start_row + offset
        ws.cell(row=row, column=1, value=label).style = StyleName.KPI_LABEL
        value_cell = ws.cell(row=row, column=2, value=value)
        if isinstance(value, Decimal) and label.endswith("(%)"):
            value_cell.style = StyleName.BODY_PERCENT
        else:
            value_cell.style = StyleName.KPI_VALUE
    return start_row + len(tiles) - 1


def _write_positions_table(ws, perf, *, start_row: int) -> int:
    heading = ws.cell(row=start_row, column=1, value="Positionen")
    heading.style = StyleName.HEADER
    row = start_row + 1
    write_header_row(ws, row, [
        "ISIN", "Symbol", "Bezeichnung", "Sektor", "Währung",
        "Eröffnung CHF", "Schluss CHF", "Käufe CHF", "Verkäufe CHF",
        "Dividenden CHF", "Realisiert CHF", "Unrealisiert CHF",
        "Gesamt-P&L CHF", "Rendite %",
    ])
    freeze_header(ws, row)
    for offset, p in enumerate(perf.positions, start=row + 1):
        ws.cell(row=offset, column=1, value=p.isin or "").style = StyleName.BODY_TEXT
        ws.cell(row=offset, column=2, value=p.symbol).style = StyleName.BODY_TEXT
        ws.cell(row=offset, column=3, value=p.description).style = StyleName.BODY_TEXT
        ws.cell(row=offset, column=4, value=p.sector).style = StyleName.BODY_TEXT
        ws.cell(row=offset, column=5, value=p.currency).style = StyleName.BODY_TEXT
        ws.cell(row=offset, column=6, value=p.opening_value_chf).style = StyleName.BODY_CHF
        ws.cell(row=offset, column=7, value=p.closing_value_chf).style = StyleName.BODY_CHF
        ws.cell(row=offset, column=8, value=p.buys_chf).style = StyleName.BODY_CHF
        ws.cell(row=offset, column=9, value=p.sells_chf).style = StyleName.BODY_CHF
        ws.cell(row=offset, column=10, value=p.dividends_chf).style = StyleName.BODY_CHF
        ws.cell(row=offset, column=11, value=p.realized_pnl_chf).style = StyleName.BODY_CHF
        ws.cell(row=offset, column=12, value=p.unrealized_pnl_chf).style = StyleName.BODY_CHF
        ws.cell(row=offset, column=13, value=p.total_pnl_chf).style = StyleName.BODY_CHF
        ws.cell(row=offset, column=14, value=_pct_or_none(p.return_pct)).style = StyleName.BODY_PERCENT
    return row + len(perf.positions)


def _write_allocation_table(ws, allocations, *, title: str, start_row: int) -> int:
    heading = ws.cell(row=start_row, column=1, value=title)
    heading.style = StyleName.HEADER
    row = start_row + 1
    write_header_row(
        ws, row,
        ["Bezeichnung", "Marktwert CHF", "Gewicht %", "P&L CHF"],
    )
    for offset, a in enumerate(allocations, start=row + 1):
        ws.cell(row=offset, column=1, value=a.label).style = StyleName.BODY_TEXT
        ws.cell(row=offset, column=2, value=a.market_value_chf).style = StyleName.BODY_CHF
        ws.cell(row=offset, column=3, value=a.weight_pct / HUNDRED).style = StyleName.BODY_PERCENT
        ws.cell(row=offset, column=4, value=a.pnl_chf).style = StyleName.BODY_CHF
    return row + len(allocations)


def _write_benchmarks_table(ws, perf, *, start_row: int) -> None:
    heading = ws.cell(row=start_row, column=1, value="Benchmark-Referenzen")
    heading.style = StyleName.HEADER
    row = start_row + 1
    write_header_row(ws, row, ["Kürzel", "Bezeichnung", "Rendite %", "Hinweis"])
    for offset, b in enumerate(perf.benchmarks, start=row + 1):
        ws.cell(row=offset, column=1, value=b.code).style = StyleName.BODY_TEXT
        ws.cell(row=offset, column=2, value=b.label).style = StyleName.BODY_TEXT
        ws.cell(row=offset, column=3, value=b.return_pct / HUNDRED).style = StyleName.BODY_PERCENT
        ws.cell(row=offset, column=4, value=b.note or "").style = StyleName.BODY_TEXT


def _pct_or_none(value):
    """BODY_PERCENT style multiplies by 100; convert dashboard-percent to rate."""
    if value is None:
        return None
    return value / HUNDRED
