"""Build TaxOverviewData from a broker statement file.

Bridges the existing import + calculate pipeline (which produces an
enriched eCH-0196 ``TaxStatement``) to the CHF-normalised
``TaxOverviewData`` that the sheet / HTML / PDF writers consume.

Scope: the translator reuses the main pipeline for broker parsing,
Kursliste enrichment, and CHF conversion. It then walks the resulting
``TaxStatement`` to populate positions, income events, orders, fees,
FX trail, waterfall, SG Verzeichnis, and DA-1 claims. Realized gains
via FIFO are intentionally left empty for now — opening-lot cost basis
is not available from a single-year flex export, and a partial FIFO
run would mislead more than it helps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ...calculate.base import CalculationMode
from ...calculate.cleanup import CleanupCalculator
from ...calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from ...calculate.total import TotalCalculator
from ...config import ConfigManager
from ...config.models import GeneralSettings, IbkrAccountSettings, SchwabAccountSettings
from ...config.paths import (
    resolve_config_file,
    resolve_kursliste_dir,
    resolve_security_identifiers_file,
)
from ...core.identifier_loader import SecurityIdentifierMapLoader
from ...core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from ...core.kursliste_manager import KurslisteManager
from ...model.ech0196 import (
    BankAccount,
    BankAccountPayment,
    Security,
    SecurityPayment,
    SecurityStock,
    TaxStatement,
)
from .data import (
    DA1Claim,
    FeeEvent,
    FXRateUsed,
    IncomeEvent,
    PositionSummary,
    TaxOverviewData,
    VerzeichnisLine,
)
from .orders import Fill, Order, reconstruct_orders
from .waterfall import Waterfall, WaterfallLine


logger = logging.getLogger(__name__)


ZERO = Decimal("0")
CHF = "CHF"

# SecurityCategory values that represent interest-bearing instruments.
_INTEREST_CATEGORIES = {"BOND", "MONEY_MARKET"}

# Commission / fee keywords that appear in SecurityPayment.name for IBKR.
_COMMISSION_KEYWORDS = ("COMMISS", "TRADING FEE", "EXCH FEE")
_FEE_KEYWORDS = ("BORROW FEE", "ACCESS FEE", "MARKET DATA", "SNAPSHOT", "EXPOSURE FEE")


@dataclass(frozen=True)
class PipelineResult:
    """The assembled overview data plus the source statement (for advanced uses)."""

    data: TaxOverviewData
    statement: TaxStatement


def build_tax_overview_data(
    input_path: Path,
    broker: str,
    tax_year: int,
    *,
    preparer_mode: bool = False,
    kursliste_dir: Optional[Path] = None,
    config_file: Optional[Path] = None,
    identifiers_csv: Optional[Path] = None,
) -> PipelineResult:
    """Run the broker pipeline and translate the result to TaxOverviewData."""
    statement = _run_pipeline(
        input_path=input_path,
        broker=broker,
        tax_year=tax_year,
        kursliste_dir=kursliste_dir,
        config_file=config_file,
        identifiers_csv=identifiers_csv,
    )
    data = _translate_statement(statement, broker=broker, tax_year=tax_year,
                                preparer_mode=preparer_mode)
    return PipelineResult(data=data, statement=statement)


# ---------------------------------------------------------------------------
# Pipeline: run the existing import + calculate steps
# ---------------------------------------------------------------------------


def _run_pipeline(
    *,
    input_path: Path,
    broker: str,
    tax_year: int,
    kursliste_dir: Optional[Path],
    config_file: Optional[Path],
    identifiers_csv: Optional[Path],
) -> TaxStatement:
    period_from = date(tax_year, 1, 1)
    period_to = date(tax_year, 12, 31)

    # Config (general settings feed the CleanupCalculator). Config is optional —
    # we only pull canton / institution for display. Missing config is fine.
    general_settings: Optional[GeneralSettings] = None
    ibkr_accounts: List[IbkrAccountSettings] = []
    schwab_accounts: List[SchwabAccountSettings] = []
    effective_config = resolve_config_file(config_file)
    if effective_config.exists():
        try:
            cm = ConfigManager(config_file_path=str(effective_config))
            if cm.general_settings:
                general_settings = GeneralSettings(**dict(cm.general_settings))
            accounts = cm.get_all_account_settings_for_broker(broker)
            for acc in accounts or []:
                if acc.kind == "ibkr":
                    ibkr_accounts.append(acc.settings)
                elif acc.kind == "schwab":
                    schwab_accounts.append(acc.settings)
        except Exception as exc:  # pragma: no cover - config errors surface to CLI
            logger.warning("tax-overview: config load failed (%s) — continuing with defaults",
                           exc)

    # The Cleanup step demands a canton. Most Lynx/IBKR exports omit
    # stateResidentialAddress, so fall back to "SG" (fork focus) when nothing
    # else is available; config and importer-supplied values still win.
    if general_settings is None:
        general_settings = GeneralSettings(canton="SG", full_name="Tax Overview")
    elif not general_settings.canton:
        general_settings = general_settings.model_copy(update={"canton": "SG"})

    # Run importer.
    if broker == "ibkr":
        # Enable tolerance for unknown XML attributes so new IBKR fields don't break parsing.
        import ibflex
        ibflex.enable_unknown_attribute_tolerance()
        from ...importers.ibkr.ibkr_importer import IbkrImporter
        importer = IbkrImporter(
            period_from=period_from,
            period_to=period_to,
            account_settings_list=ibkr_accounts,
        )
        statement = importer.import_files([str(input_path)])
    elif broker == "schwab":
        from ...importers.schwab.schwab_importer import SchwabImporter
        if not input_path.is_dir():
            raise ValueError(
                f"Schwab importer expects a directory, got file: {input_path}"
            )
        importer = SchwabImporter(
            period_from=period_from,
            period_to=period_to,
            account_settings_list=schwab_accounts,
            strict_consistency=True,
        )
        statement = importer.import_dir(str(input_path))
    else:
        raise ValueError(f"unsupported broker: {broker!r}")

    # Cleanup (identifier map, period filtering).
    identifier_map = {}
    if identifiers_csv is None:
        identifiers_csv = resolve_security_identifiers_file(None)
    if identifiers_csv and Path(identifiers_csv).exists():
        try:
            identifier_map = SecurityIdentifierMapLoader(str(identifiers_csv)).load_map()
        except Exception as exc:
            logger.warning("tax-overview: identifier map load failed (%s)", exc)

    cleanup = CleanupCalculator(
        period_from=period_from,
        period_to=period_to,
        identifier_map=identifier_map,
        enable_filtering=True,
        importer_name=broker,
        config_settings=general_settings,
    )
    statement = cleanup.calculate(statement)

    # Kursliste-driven tax value + FX. Requires Kursliste data for the year.
    effective_kursliste = resolve_kursliste_dir(kursliste_dir)
    if effective_kursliste.exists():
        try:
            km = KurslisteManager()
            km.load_directory(effective_kursliste)
            km.ensure_year_available(tax_year, effective_kursliste)
            rate_provider = KurslisteExchangeRateProvider(km)
            kursliste_calc = KurslisteTaxValueCalculator(
                mode=CalculationMode.OVERWRITE,
                exchange_rate_provider=rate_provider,
            )
            statement = kursliste_calc.calculate(statement)
        except Exception as exc:
            logger.warning(
                "tax-overview: Kursliste enrichment skipped (%s). "
                "Positions may show broker balances instead of Steuerwert.", exc
            )
    else:
        logger.warning(
            "tax-overview: Kursliste directory %s missing — positions will fall "
            "back to broker balances (no official Steuerwert applied).",
            effective_kursliste,
        )

    total = TotalCalculator(mode=CalculationMode.OVERWRITE)
    statement = total.calculate(statement)
    return statement


# ---------------------------------------------------------------------------
# Translation: TaxStatement -> TaxOverviewData
# ---------------------------------------------------------------------------


def _translate_statement(
    statement: TaxStatement,
    *,
    broker: str,
    tax_year: int,
    preparer_mode: bool,
) -> TaxOverviewData:
    period_end = date(tax_year, 12, 31)

    positions = _collect_positions(statement, period_end=period_end)
    dividends, interest, sec_fees, da1_claims = _collect_security_events(statement)
    bank_interest, bank_fees = _collect_bank_events(statement, period_end=period_end)
    fees = sec_fees + bank_fees
    interest_events = interest + bank_interest
    orders = _collect_orders(statement)
    fx_rates = _collect_fx_rates(statement)

    opening_chf = _sum_security_opening(statement, period_start=date(tax_year, 1, 1)) \
                  + _sum_bank_opening(statement, period_start=date(tax_year, 1, 1))
    closing_chf = _sum_security_closing(positions) + _sum_bank_closing(statement,
                                                                        period_end=period_end)

    verzeichnis = _build_verzeichnis(positions, dividends, interest_events, da1_claims)

    waterfall = _build_waterfall(
        opening_chf=opening_chf,
        closing_chf=closing_chf,
        dividends=dividends,
        interest=interest_events,
        fees=fees,
    )

    return TaxOverviewData(
        tax_year=tax_year,
        broker=broker,
        preparer_mode=preparer_mode,
        opening_value_chf=opening_chf,
        closing_value_chf=closing_chf,
        waterfall=waterfall,
        positions=positions,
        orders=orders,
        lot_closes=[],  # FIFO requires opening-lot basis we don't have here
        dividends=dividends,
        interest=interest_events,
        fees=fees,
        fx_rates=fx_rates,
        verzeichnis_lines=verzeichnis,
        da1_claims=da1_claims,
        ks36_criteria=[],
        ks36_evidence=[],
    )


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


def _collect_positions(statement: TaxStatement, *, period_end: date) -> List[PositionSummary]:
    positions: List[PositionSummary] = []
    los = statement.listOfSecurities
    if not los:
        return positions

    for depot in los.depot:
        for security in depot.security:
            pos = _position_for(security, period_end=period_end)
            if pos is not None:
                positions.append(pos)

    positions.sort(key=lambda p: (p.isin or "", p.symbol))
    return positions


def _position_for(security: Security, *, period_end: date) -> Optional[PositionSummary]:
    tv = security.taxValue
    closing_stock = _find_closing_stock(security.stock, period_end=period_end)

    # Prefer the security.taxValue Kursliste figures; fall back to the closing
    # stock entry when the calculator left taxValue empty (e.g. no Kursliste).
    quantity = _first_non_none(
        tv.quantity if tv else None,
        closing_stock.quantity if closing_stock else None,
    ) or ZERO
    if quantity == 0:
        return None

    price_local = _first_non_none(
        tv.unitPrice if tv else None,
        closing_stock.unitPrice if closing_stock else None,
    ) or ZERO

    market_value_chf = _first_non_none(
        tv.value if tv else None,
        closing_stock.value if closing_stock else None,
    ) or ZERO

    # Per-share CHF: balance / quantity if available, else price_local * rate.
    if market_value_chf and quantity:
        price_chf = market_value_chf / quantity
    else:
        rate = _first_non_none(
            tv.exchangeRate if tv else None,
            closing_stock.exchangeRate if closing_stock else None,
        ) or Decimal("1")
        price_chf = price_local * rate

    return PositionSummary(
        isin=security.isin,
        symbol=(security.symbol or _symbol_from_name(security.securityName)),
        description=security.securityName,
        quantity_closing=quantity,
        currency=security.currency,
        price_closing_local=price_local,
        price_closing_chf=price_chf,
        market_value_chf=market_value_chf,
    )


def _find_closing_stock(stocks: Sequence[SecurityStock], *, period_end: date) -> Optional[SecurityStock]:
    """Return the year-end closing balance stock entry, if one exists.

    The importer writes a ``mutation=False`` entry for the closing balance.
    Its referenceDate is the day AFTER the period end (start-of-next-day
    convention), so we pick the latest non-mutation entry at or just past
    period_end.
    """
    candidates = [s for s in stocks if not s.mutation]
    if not candidates:
        return None
    # Pick the one whose referenceDate is closest to (and >= period_end + 1 day).
    return max(candidates, key=lambda s: s.referenceDate)


def _find_opening_stock(stocks: Sequence[SecurityStock], *, period_start: date) -> Optional[SecurityStock]:
    """Return the opening balance stock entry (mutation=False at period start)."""
    candidates = [s for s in stocks if not s.mutation and s.referenceDate <= period_start]
    if not candidates:
        # Some importers label the opening with referenceDate = period_start exactly.
        candidates = [s for s in stocks if not s.mutation]
    if not candidates:
        return None
    return min(candidates, key=lambda s: s.referenceDate)


# ---------------------------------------------------------------------------
# Security events: dividends, interest, commissions, DA-1 claims
# ---------------------------------------------------------------------------


def _collect_security_events(
    statement: TaxStatement,
) -> Tuple[List[IncomeEvent], List[IncomeEvent], List[FeeEvent], List[DA1Claim]]:
    dividends: List[IncomeEvent] = []
    interest: List[IncomeEvent] = []
    fees: List[FeeEvent] = []
    da1: List[DA1Claim] = []

    los = statement.listOfSecurities
    if not los:
        return dividends, interest, fees, da1

    for depot in los.depot:
        for security in depot.security:
            symbol = security.symbol or _symbol_from_name(security.securityName)
            for payment in security.payment:
                kind = _classify_security_payment(payment, security)
                if kind == "fee":
                    fees.append(_fee_from_security_payment(payment, security))
                    continue
                event = _income_from_security_payment(payment, security, symbol=symbol)
                if event is None:
                    continue
                if _is_interest_security(security):
                    interest.append(event)
                else:
                    dividends.append(event)
                claim = _da1_from_security_payment(payment, security, event)
                if claim is not None:
                    da1.append(claim)

    dividends.sort(key=lambda e: (e.payment_date, e.symbol))
    interest.sort(key=lambda e: (e.payment_date, e.symbol))
    fees.sort(key=lambda f: (f.fee_date, f.kind))
    da1.sort(key=lambda c: (c.source_country, c.symbol))
    return dividends, interest, fees, da1


def _classify_security_payment(payment: SecurityPayment, security: Security) -> str:
    """Return 'fee' for commissions/fees, 'income' for dividends/interest."""
    name = (payment.name or "").upper()
    if any(kw in name for kw in _COMMISSION_KEYWORDS):
        return "fee"
    if any(kw in name for kw in _FEE_KEYWORDS):
        return "fee"
    return "income"


def _income_from_security_payment(
    payment: SecurityPayment, security: Security, *, symbol: str
) -> Optional[IncomeEvent]:
    # Gross in CHF is the sum of Kursliste-attributed gross revenue buckets.
    gross_chf = _sum_optional(
        payment.grossRevenueA,
        payment.grossRevenueACanton,
        payment.grossRevenueB,
        payment.grossRevenueBCanton,
    )
    wht_chf = _sum_optional(
        payment.withHoldingTaxClaim,
        payment.nonRecoverableTax,
        payment.additionalWithHoldingTaxUSA,
    )

    gross_local = payment.amount or ZERO
    rate = payment.exchangeRate or Decimal("1")
    # Some payments have amount in local + no CHF breakdown (e.g. when Kursliste
    # missed the ISIN). Fall back to amount * rate for a display-only figure.
    if gross_chf == 0 and gross_local != 0:
        gross_chf = (gross_local * rate).quantize(Decimal("0.01"))

    if gross_chf == 0 and gross_local == 0:
        return None

    wht_local = (wht_chf / rate) if rate and rate != 0 else ZERO
    net_local = gross_local - wht_local
    net_chf = gross_chf - wht_chf

    category = "interest" if _is_interest_security(security) else "dividend"
    return IncomeEvent(
        payment_date=payment.paymentDate,
        isin=security.isin,
        symbol=symbol,
        description=security.securityName,
        category=category,
        gross_local=gross_local,
        currency=payment.amountCurrency,
        withholding_tax_local=wht_local,
        net_local=net_local,
        gross_chf=gross_chf,
        withholding_tax_chf=wht_chf,
        net_chf=net_chf,
    )


def _fee_from_security_payment(payment: SecurityPayment, security: Security) -> FeeEvent:
    amount_local = payment.amount or ZERO
    # Brokers book commissions as negative numbers; show absolute value in the sheet.
    amount_local = abs(amount_local)
    rate = payment.exchangeRate or Decimal("1")
    amount_chf = (amount_local * rate).quantize(Decimal("0.01"))
    name_upper = (payment.name or "").upper()
    kind = "commission" if any(kw in name_upper for kw in _COMMISSION_KEYWORDS) else "other"
    return FeeEvent(
        fee_date=payment.paymentDate,
        kind=kind,
        description=payment.name or security.securityName,
        amount_local=amount_local,
        currency=payment.amountCurrency,
        amount_chf=amount_chf,
    )


def _da1_from_security_payment(
    payment: SecurityPayment, security: Security, event: IncomeEvent
) -> Optional[DA1Claim]:
    # Only foreign securities with a non-zero non-recoverable / additional US WHT
    # qualify for a DA-1 row.
    recoverable = _sum_optional(
        payment.nonRecoverableTax,
        payment.additionalWithHoldingTaxUSA,
    )
    if recoverable == 0:
        return None
    country = (security.country or "").upper() or "??"
    if country == "CH":
        return None

    gross_chf = event.gross_chf
    wht_chf = _sum_optional(
        payment.nonRecoverableTax,
        payment.additionalWithHoldingTaxUSA,
    )
    withholding_rate = wht_chf / gross_chf if gross_chf else ZERO
    return DA1Claim(
        isin=security.isin,
        symbol=event.symbol,
        description=security.securityName,
        source_country=country,
        gross_chf=gross_chf,
        withholding_tax_chf=wht_chf,
        withholding_rate=withholding_rate,
        treaty_rate_ceiling=None,  # not resolved — left blank
        recoverable_chf=wht_chf,
    )


def _is_interest_security(security: Security) -> bool:
    return security.securityCategory in _INTEREST_CATEGORIES


# ---------------------------------------------------------------------------
# Bank account events: cash interest / fees
# ---------------------------------------------------------------------------


def _collect_bank_events(
    statement: TaxStatement, *, period_end: date
) -> Tuple[List[IncomeEvent], List[FeeEvent]]:
    interest: List[IncomeEvent] = []
    fees: List[FeeEvent] = []
    loba = statement.listOfBankAccounts
    if not loba:
        return interest, fees

    for ba in loba.bankAccount:
        for payment in ba.payment:
            amount = payment.amount or ZERO
            gross_chf = _sum_optional(payment.grossRevenueA, payment.grossRevenueB)
            if gross_chf == 0 and amount:
                rate = payment.exchangeRate or Decimal("1")
                gross_chf = (amount * rate).quantize(Decimal("0.01"))

            name_upper = (payment.name or "").upper()
            is_fee = (amount < 0) or ("DEBIT INT" in name_upper) or any(
                kw in name_upper for kw in _FEE_KEYWORDS
            )
            if is_fee or payment.bankingExpenses:
                fees.append(FeeEvent(
                    fee_date=payment.paymentDate,
                    kind="interest_debit" if "DEBIT" in name_upper else "other",
                    description=payment.name or f"{ba.bankAccountName} fee",
                    amount_local=abs(amount),
                    currency=payment.amountCurrency,
                    amount_chf=abs(gross_chf),
                ))
                continue

            # Credit interest on a cash account → interest income.
            if amount > 0:
                rate = payment.exchangeRate or Decimal("1")
                wht_chf = _sum_optional(
                    payment.withHoldingTaxClaim,
                    payment.nonRecoverableTax,
                )
                wht_local = (wht_chf / rate) if rate and rate != 0 else ZERO
                interest.append(IncomeEvent(
                    payment_date=payment.paymentDate,
                    isin=None,
                    symbol=ba.bankAccountCurrency or "",
                    description=payment.name or f"{ba.bankAccountName} interest",
                    category="interest",
                    gross_local=amount,
                    currency=payment.amountCurrency,
                    withholding_tax_local=wht_local,
                    net_local=amount - wht_local,
                    gross_chf=gross_chf,
                    withholding_tax_chf=wht_chf,
                    net_chf=gross_chf - wht_chf,
                ))

    interest.sort(key=lambda e: (e.payment_date, e.symbol))
    fees.sort(key=lambda f: (f.fee_date, f.kind))
    return interest, fees


# ---------------------------------------------------------------------------
# Orders: reconstruct from SecurityStock mutation entries
# ---------------------------------------------------------------------------


def _collect_orders(statement: TaxStatement) -> List[Order]:
    fills: List[Fill] = []
    los = statement.listOfSecurities
    if not los:
        return []

    for depot in los.depot:
        for security in depot.security:
            symbol = security.symbol or _symbol_from_name(security.securityName)
            for idx, stock in enumerate(security.stock):
                if not stock.mutation:
                    continue
                qty = stock.quantity or ZERO
                if qty == 0:
                    continue
                side = "BUY" if qty > 0 else "SELL"
                price = stock.unitPrice or ZERO
                money = abs(qty) * price
                fill_id = stock.orderId or f"{security.positionId}:{idx}:{stock.referenceDate.isoformat()}"
                fills.append(Fill(
                    fill_id=fill_id,
                    symbol=symbol,
                    side=side,
                    quantity=abs(qty),
                    price=price,
                    money=money if side == "BUY" else -money,
                    commission=ZERO,  # commissions live separately in SecurityPayment
                    currency=security.currency,
                    trade_time=datetime.combine(stock.referenceDate, time.min),
                    asset_category=security.securityCategory or "",
                    isin=security.isin,
                    conid=None,
                    ib_order_id=stock.orderId,
                    order_reference=None,
                ))

    return reconstruct_orders(fills)


# ---------------------------------------------------------------------------
# FX rates: unique (currency, date, rate) tuples observed during the run
# ---------------------------------------------------------------------------


def _collect_fx_rates(statement: TaxStatement) -> List[FXRateUsed]:
    seen: Dict[Tuple[str, date], Decimal] = {}

    def _add(currency: Optional[str], ref_date: Optional[date], rate: Optional[Decimal]) -> None:
        if not currency or currency == CHF or not ref_date or not rate:
            return
        seen.setdefault((currency, ref_date), rate)

    los = statement.listOfSecurities
    if los:
        for depot in los.depot:
            for security in depot.security:
                if security.taxValue:
                    _add(security.currency, security.taxValue.referenceDate,
                         security.taxValue.exchangeRate)
                for stock in security.stock:
                    _add(security.currency, stock.referenceDate, stock.exchangeRate)
                for payment in security.payment:
                    _add(payment.amountCurrency, payment.paymentDate, payment.exchangeRate)

    loba = statement.listOfBankAccounts
    if loba:
        for ba in loba.bankAccount:
            if ba.taxValue:
                _add(ba.taxValue.balanceCurrency, ba.taxValue.referenceDate,
                     ba.taxValue.exchangeRate)
            for payment in ba.payment:
                _add(payment.amountCurrency, payment.paymentDate, payment.exchangeRate)

    return sorted(
        (FXRateUsed(currency=ccy, reference_date=d, rate=rate, source="kursliste")
         for (ccy, d), rate in seen.items()),
        key=lambda r: (r.reference_date, r.currency),
    )


# ---------------------------------------------------------------------------
# Aggregates for the waterfall
# ---------------------------------------------------------------------------


def _sum_security_opening(statement: TaxStatement, *, period_start: date) -> Decimal:
    total = ZERO
    los = statement.listOfSecurities
    if not los:
        return total
    for depot in los.depot:
        for security in depot.security:
            opening = _find_opening_stock(security.stock, period_start=period_start)
            if opening is None:
                continue
            if opening.value is not None:
                total += opening.value
            elif opening.balance is not None and opening.exchangeRate is not None:
                total += opening.balance * opening.exchangeRate
    return total


def _sum_security_closing(positions: Iterable[PositionSummary]) -> Decimal:
    return sum((p.market_value_chf for p in positions), ZERO)


def _sum_bank_opening(statement: TaxStatement, *, period_start: date) -> Decimal:
    # Bank account openings are not separately modeled in the eCH-0196 shape we
    # hold; treat opening cash as zero-delta (the residual absorbs it). This is
    # a documented limitation of the dashboard.
    return ZERO


def _sum_bank_closing(statement: TaxStatement, *, period_end: date) -> Decimal:
    total = ZERO
    loba = statement.listOfBankAccounts
    if not loba:
        return total
    for ba in loba.bankAccount:
        if ba.taxValue and ba.taxValue.value is not None:
            total += ba.taxValue.value
        elif ba.taxValue and ba.taxValue.balance is not None and ba.taxValue.exchangeRate is not None:
            total += ba.taxValue.balance * ba.taxValue.exchangeRate
    return total


# ---------------------------------------------------------------------------
# SG Verzeichnis lines (consolidate per ISIN)
# ---------------------------------------------------------------------------


def _build_verzeichnis(
    positions: Sequence[PositionSummary],
    dividends: Sequence[IncomeEvent],
    interest: Sequence[IncomeEvent],
    da1: Sequence[DA1Claim],
) -> List[VerzeichnisLine]:
    income_by_isin: Dict[str, Decimal] = {}
    vstk_by_isin: Dict[str, Decimal] = {}  # Verrechnungssteuer (CH WHT claim)
    foreign_by_isin: Dict[str, Decimal] = {}

    for event in list(dividends) + list(interest):
        key = event.isin or event.symbol
        income_by_isin[key] = income_by_isin.get(key, ZERO) + event.gross_chf

    for claim in da1:
        key = claim.isin or claim.symbol
        foreign_by_isin[key] = foreign_by_isin.get(key, ZERO) + claim.withholding_tax_chf

    # Swiss WHT only arises when no DA-1 foreign WHT was emitted for that payment;
    # approximate: sum (withholding_tax_chf - foreign_by_isin).
    # Precise bookkeeping lives upstream — this is an overview helper.
    for event in dividends:
        key = event.isin or event.symbol
        foreign = foreign_by_isin.get(key, ZERO)
        ch_portion = max(event.withholding_tax_chf - foreign, ZERO)
        if ch_portion > 0:
            vstk_by_isin[key] = vstk_by_isin.get(key, ZERO) + ch_portion

    lines: List[VerzeichnisLine] = []
    for position in positions:
        key = position.isin or position.symbol
        lines.append(VerzeichnisLine(
            form_field="A" if vstk_by_isin.get(key) else "B",
            investment_type=_verzeichnis_type(position),
            isin=position.isin,
            description=position.description,
            quantity=position.quantity_closing,
            market_value_chf=position.market_value_chf,
            income_gross_chf=income_by_isin.get(key, ZERO),
            verrechnungssteuer_chf=vstk_by_isin.get(key, ZERO),
            auslaendische_quellensteuer_chf=foreign_by_isin.get(key, ZERO),
        ))
    return lines


def _verzeichnis_type(position: PositionSummary) -> str:
    # Without the SecurityCategory on PositionSummary we use a simple heuristic
    # on description. Callers who want precise typing should populate it upstream.
    desc = (position.description or "").upper()
    if "BOND" in desc or "%" in desc:
        return "Obligation"
    if "FUND" in desc or "ETF" in desc or "UCITS" in desc:
        return "Fonds"
    return "Aktie"


# ---------------------------------------------------------------------------
# Waterfall
# ---------------------------------------------------------------------------


def _build_waterfall(
    *,
    opening_chf: Decimal,
    closing_chf: Decimal,
    dividends: Sequence[IncomeEvent],
    interest: Sequence[IncomeEvent],
    fees: Sequence[FeeEvent],
) -> Waterfall:
    total_dividends = sum((d.gross_chf for d in dividends), ZERO)
    total_interest = sum((i.gross_chf for i in interest), ZERO)
    total_wht = sum((e.withholding_tax_chf for e in (*dividends, *interest)), ZERO)
    total_fees = sum((f.amount_chf for f in fees), ZERO)

    inflows: List[WaterfallLine] = []
    if total_dividends:
        inflows.append(WaterfallLine("Dividenden brutto", total_dividends, "inflow"))
    if total_interest:
        inflows.append(WaterfallLine("Zinsen brutto", total_interest, "inflow"))

    outflows: List[WaterfallLine] = []
    if total_wht:
        outflows.append(WaterfallLine("Quellensteuer", total_wht, "outflow"))
    if total_fees:
        outflows.append(WaterfallLine("Gebühren", total_fees, "outflow"))

    return Waterfall(
        opening=opening_chf,
        inflows=inflows,
        outflows=outflows,
        closing=closing_chf,
    )


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def _first_non_none(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _sum_optional(*values: Optional[Decimal]) -> Decimal:
    total = ZERO
    for v in values:
        if v is not None:
            total += v
    return total


def _symbol_from_name(name: str) -> str:
    # IBKR security names often look like "NAME (SYM)"; pull the parenthesized tail.
    if not name:
        return ""
    if "(" in name and name.rstrip().endswith(")"):
        return name.rsplit("(", 1)[1].rstrip(")").strip()
    return name.split()[0] if name else ""
