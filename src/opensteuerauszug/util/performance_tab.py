"""Performance allocation tab: per-instrument gain/loss analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from opensteuerauszug.model.ech0196 import TaxStatement

_ZERO = Decimal("0")
_DASH = "–"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PerformanceRecord:
    name: str
    isin: str
    native_currency: str

    opening_value_native: Decimal = field(default=_ZERO)
    opening_value_chf: Decimal = field(default=_ZERO)
    closing_value_native: Decimal = field(default=_ZERO)
    closing_value_chf: Decimal = field(default=_ZERO)
    buys_native: Decimal = field(default=_ZERO)
    sells_native: Decimal = field(default=_ZERO)
    dividends_native: Decimal = field(default=_ZERO)
    unrealized_pl_native: Decimal = field(default=_ZERO)
    realized_pl_native: Decimal = field(default=_ZERO)
    total_pl_native: Decimal = field(default=_ZERO)
    total_pl_chf: Decimal = field(default=_ZERO)
    return_pct: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------

def _fx(stock_or_tv) -> Decimal:
    """Return exchange-rate (native → CHF) from a stock or taxValue entry, defaulting to 1."""
    rate = getattr(stock_or_tv, "exchangeRate", None)
    return Decimal(str(rate)) if rate else Decimal("1")


def compute_performance_records(statement: "TaxStatement") -> List[PerformanceRecord]:
    """Derive a PerformanceRecord for every security in the statement."""
    records: List[PerformanceRecord] = []

    list_of_securities = getattr(statement, "listOfSecurities", None)
    if list_of_securities is None:
        return records

    securities = getattr(list_of_securities, "security", None) or []

    for sec in securities:
        isin = str(getattr(sec, "isin", None) or getattr(sec, "valorNumber", None) or getattr(sec, "symbol", "") or "")
        ccy = str(getattr(sec, "currency", "?"))
        name = str(getattr(sec, "securityName", isin))

        stocks = list(getattr(sec, "stock", []) or [])
        payments = list(getattr(sec, "payment", []) or [])
        tax_value = getattr(sec, "taxValue", None)

        # --- Opening value (first balance entry: mutation=False) ---
        balance_entries = [s for s in stocks if not getattr(s, "mutation", True)]
        opening_native = _ZERO
        opening_chf = _ZERO
        opening_qty = _ZERO
        if balance_entries:
            b = balance_entries[0]
            qty = Decimal(str(getattr(b, "quantity", 0) or 0))
            price = Decimal(str(getattr(b, "unitPrice", 0) or 0))
            opening_native = qty * price
            opening_chf = opening_native / _fx(b)
            opening_qty = qty

        # --- Closing value (from SecurityTaxValue) ---
        closing_native = _ZERO
        closing_chf = _ZERO
        closing_qty = _ZERO
        if tax_value is not None:
            qty = Decimal(str(getattr(tax_value, "quantity", 0) or 0))
            price = Decimal(str(getattr(tax_value, "unitPrice", 0) or 0))
            closing_native = qty * price
            closing_chf = Decimal(str(getattr(tax_value, "value", 0) or 0))
            closing_qty = qty

        # --- Buys and sells (mutation=True transactions) ---
        buys_native = _ZERO
        sells_native = _ZERO
        for s in stocks:
            if not getattr(s, "mutation", False):
                continue
            qty = Decimal(str(getattr(s, "quantity", 0) or 0))
            price = Decimal(str(getattr(s, "unitPrice", 0) or 0))
            notional = abs(qty) * price
            if qty >= _ZERO:
                buys_native += notional
            else:
                sells_native += notional

        # --- Dividends (sum of payment amounts in native currency) ---
        dividends_native = _ZERO
        for p in payments:
            amount = getattr(p, "amount", None)
            if amount is not None:
                # payment.amount is typically in amountCurrency (native)
                dividends_native += Decimal(str(amount))
            else:
                # Fallback: amountPerUnit * quantity
                per_unit = getattr(p, "amountPerUnit", None)
                qty = getattr(p, "quantity", None)
                if per_unit is not None and qty is not None:
                    dividends_native += Decimal(str(per_unit)) * Decimal(str(qty))

        # --- Total P&L ---
        total_pl_native = closing_native + sells_native + dividends_native - opening_native - buys_native

        # Derive CHF P&L using closing exchange rate if available, else opening
        if tax_value is not None:
            fx_close = _fx(tax_value)
        elif balance_entries:
            fx_close = _fx(balance_entries[0])
        else:
            fx_close = Decimal("1")
        total_pl_chf = total_pl_native / fx_close if fx_close else _ZERO

        # --- Unrealized / Realized split (average-cost approximation) ---
        net_invested = opening_native + buys_native - sells_native
        avg_qty = (opening_qty + closing_qty) / 2
        if avg_qty > _ZERO and net_invested >= _ZERO:
            unrealized_pl_native = closing_native - (net_invested * closing_qty / avg_qty)
        elif closing_qty == _ZERO:
            # Position fully closed → all P&L is realized
            unrealized_pl_native = _ZERO
        else:
            unrealized_pl_native = closing_native - net_invested

        realized_pl_native = total_pl_native - unrealized_pl_native

        # --- Return % ---
        if opening_native > _ZERO:
            return_pct = (total_pl_native / opening_native) * 100
        else:
            return_pct = None

        records.append(PerformanceRecord(
            name=name,
            isin=isin,
            native_currency=ccy,
            opening_value_native=opening_native,
            opening_value_chf=opening_chf,
            closing_value_native=closing_native,
            closing_value_chf=closing_chf,
            buys_native=buys_native,
            sells_native=sells_native,
            dividends_native=dividends_native,
            unrealized_pl_native=unrealized_pl_native,
            realized_pl_native=realized_pl_native,
            total_pl_native=total_pl_native,
            total_pl_chf=total_pl_chf,
            return_pct=return_pct,
        ))

    records.sort(key=lambda r: abs(r.total_pl_native), reverse=True)
    return records


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class PerformanceWorker(QThread):
    """Runs the importer in a background thread and emits results."""

    finished = Signal(list)          # list[PerformanceRecord]
    error = Signal(str)

    def __init__(self, input_path: str, broker: str, tax_year: int) -> None:
        super().__init__()
        self._input_path = input_path
        self._broker = broker
        self._tax_year = tax_year

    def run(self) -> None:
        try:
            period_from = date(self._tax_year, 1, 1)
            period_to = date(self._tax_year, 12, 31)

            if self._broker == "ibkr":
                from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
                importer = IbkrImporter(period_from, period_to, [])
                statement = importer.import_files([self._input_path])
            elif self._broker == "schwab":
                from opensteuerauszug.importers.schwab.schwab_importer import SchwabImporter
                importer = SchwabImporter(period_from, period_to, [])
                statement = importer.import_files([self._input_path])
            else:
                self.error.emit("No broker selected – cannot run analysis.")
                return

            records = compute_performance_records(statement)
            self.finished.emit(records)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_COLUMNS = [
    ("Name", "name"),
    ("ISIN", "isin"),
    ("CCY", "native_currency"),
    ("Opening (CCY)", "opening_value_native"),
    ("Closing (CCY)", "closing_value_native"),
    ("Buys (CCY)", "buys_native"),
    ("Sells (CCY)", "sells_native"),
    ("Dividends (CCY)", "dividends_native"),
    ("Realized P&L", "realized_pl_native"),
    ("Unrealized P&L", "unrealized_pl_native"),
    ("Total P&L (CCY)", "total_pl_native"),
    ("Total P&L (CHF)", "total_pl_chf"),
    ("Return %", "return_pct"),
]

_GREEN = QColor("#1e8c45")
_RED = QColor("#c0392b")


def _fmt(value: object, is_pct: bool = False) -> str:
    if value is None:
        return _DASH
    try:
        d = Decimal(str(value))
    except Exception:
        return str(value)
    if is_pct:
        return f"{d:+.2f}%"
    return f"{d:,.2f}"


class _NumericItem(QTableWidgetItem):
    """Table item that sorts numerically."""

    def __init__(self, raw: object, text: str) -> None:
        super().__init__(text)
        try:
            self._sort_key = float(str(raw)) if raw is not None else 0.0
        except (TypeError, ValueError):
            self._sort_key = 0.0

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        if isinstance(other, _NumericItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)


class PerformanceTab(QWidget):
    def __init__(self, main_window: "object") -> None:
        super().__init__()
        self._main = main_window
        self._worker: Optional[PerformanceWorker] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(16)

        # ── Controls group ──────────────────────────────────────────────
        ctrl_group = QGroupBox("Performance Analysis")
        ctrl_layout = QVBoxLayout(ctrl_group)

        info = QLabel(
            "Analyzes the file and broker configured in the Generator tab.\n"
            "Prices are approximated from the raw import data – not from the official Kursliste."
        )
        info.setWordWrap(True)
        info.setObjectName("heroSubtitle")
        ctrl_layout.addWidget(info)

        btn_row = QHBoxLayout()
        self._analyze_btn = QPushButton("Analyze")
        self._analyze_btn.setDefault(True)
        self._status_label = QLabel("")
        btn_row.addWidget(self._analyze_btn)
        btn_row.addWidget(self._status_label)
        btn_row.addStretch()
        ctrl_layout.addLayout(btn_row)

        outer.addWidget(ctrl_group)

        # ── Table ────────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([c[0] for c in _COLUMNS])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(_COLUMNS)):
            self._table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        outer.addWidget(self._table)

        # ── Summary bar ─────────────────────────────────────────────────
        self._summary_label = QLabel("")
        outer.addWidget(self._summary_label)

        # ── Wire ─────────────────────────────────────────────────────────
        self._analyze_btn.clicked.connect(self._run_analysis)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _run_analysis(self) -> None:
        input_path: str = self._main.input_path_edit.text().strip()
        broker: str = self._main.importer_combo.currentData()
        tax_year: int = self._main.tax_year_spin.value()

        if not input_path:
            self._set_status("No input file selected in the Generator tab.", error=True)
            return
        if broker == "none":
            self._set_status("Select a broker in the Generator tab first.", error=True)
            return

        if self._worker and self._worker.isRunning():
            return

        self._table.setRowCount(0)
        self._summary_label.setText("")
        self._analyze_btn.setEnabled(False)
        self._set_status(f"Importing {tax_year} data…")

        self._worker = PerformanceWorker(input_path, broker, tax_year)
        self._worker.finished.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_results(self, records: List[PerformanceRecord]) -> None:
        self._analyze_btn.setEnabled(True)
        if not records:
            self._set_status("No securities found in the statement.")
            return

        self._set_status(f"Found {len(records)} instrument(s).")
        self._populate_table(records)

    def _on_error(self, message: str) -> None:
        self._analyze_btn.setEnabled(True)
        self._set_status(f"Error: {message}", error=True)

    def _set_status(self, text: str, *, error: bool = False) -> None:
        self._status_label.setText(text)
        color = "#c0392b" if error else "palette(mid)"
        self._status_label.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(self, records: List[PerformanceRecord]) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))

        total_pl_chf = _ZERO
        total_dividends_chf = _ZERO

        for row, rec in enumerate(records):
            col_values = [
                rec.name,
                rec.isin,
                rec.native_currency,
                rec.opening_value_native,
                rec.closing_value_native,
                rec.buys_native,
                rec.sells_native,
                rec.dividends_native,
                rec.realized_pl_native,
                rec.unrealized_pl_native,
                rec.total_pl_native,
                rec.total_pl_chf,
                rec.return_pct,
            ]

            for col, (header, _attr) in enumerate(_COLUMNS):
                raw = col_values[col]
                is_pct = header == "Return %"
                is_text = col < 3  # name, isin, ccy are plain strings

                if is_text:
                    item = QTableWidgetItem(str(raw) if raw is not None else _DASH)
                else:
                    item = _NumericItem(raw, _fmt(raw, is_pct=is_pct))
                    item.setTextAlignment(0x0082)  # AlignRight | AlignVCenter

                    # Color code P&L columns
                    if header in ("Realized P&L", "Unrealized P&L", "Total P&L (CCY)", "Total P&L (CHF)", "Return %"):
                        try:
                            v = float(str(raw)) if raw is not None else 0.0
                            item.setForeground(_GREEN if v >= 0 else _RED)
                        except (TypeError, ValueError):
                            pass

                self._table.setItem(row, col, item)

            total_pl_chf += rec.total_pl_chf
            total_dividends_chf += rec.dividends_native  # approximate in native; good enough for summary

        self._table.setSortingEnabled(True)

        sign = "+" if total_pl_chf >= _ZERO else ""
        self._summary_label.setText(
            f"Total P&L (CHF): {sign}{total_pl_chf:,.2f}   |   "
            f"Total Dividends (native Σ): {total_dividends_chf:,.2f}"
        )
