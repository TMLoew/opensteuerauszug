"""Securities missing from the Kursliste must not lose their income.

``fillin`` is the mode whose job is to complete a statement from whatever data
is available. Replacing the payment list with the (empty) Kursliste-derived one
used to delete every dividend the broker had reported for a security the
Kursliste does not list, which silently under-declares taxable income.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from opensteuerauszug.calculate.base import CalculationMode
from opensteuerauszug.calculate.fill_in_tax_value_calculator import FillInTaxValueCalculator
from opensteuerauszug.calculate.kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from opensteuerauszug.core.kursliste_exchange_rate_provider import KurslisteExchangeRateProvider
from opensteuerauszug.core.kursliste_manager import KurslisteManager
from opensteuerauszug.model.ech0196 import (
    Depot,
    DepotNumber,
    ISINType,
    ListOfSecurities,
    Security,
    SecurityPayment,
    SecurityStock,
    SecurityTaxValue,
    TaxStatement,
)

KURSLISTE_DIR = Path(__file__).resolve().parents[2] / "tests" / "samples" / "kursliste"
PAY_DATE = date(2025, 6, 10)


@pytest.fixture(scope="module")
def provider():
    manager = KurslisteManager()
    manager.load_directory(KURSLISTE_DIR)
    return KurslisteExchangeRateProvider(manager)


def _statement(*, country="US", dividend=Decimal("250.00"), withholding=Decimal("37.50")):
    """A US share the mini Kursliste does not list, with a dividend + WHT."""
    payments = [
        SecurityPayment(
            paymentDate=PAY_DATE,
            quotationType="PIECE",
            quantity=Decimal("100"),
            amountCurrency="USD",
            amount=dividend,
            name="Dividend",
            broker_label_original="Dividends",
        )
    ]
    if withholding is not None:
        payments.append(
            SecurityPayment(
                paymentDate=PAY_DATE,
                quotationType="PIECE",
                quantity=Decimal("100"),
                amountCurrency="USD",
                amount=-withholding,
                name="Withholding Tax",
                broker_label_original="Withholding Tax",
                nonRecoverableTaxAmountOriginal=withholding,
            )
        )
    security = Security(
        positionId=1,
        country=country,
        currency="USD",
        quotationType="PIECE",
        securityCategory="SHARE",
        securityName="NOT IN KURSLISTE INC (XYZ)",
        isin=ISINType("US0000000001"),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("100"),
                balanceCurrency="USD",
            )
        ],
        payment=payments,
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("100"),
            balanceCurrency="USD",
            balance=Decimal("5000"),
        ),
    )
    return TaxStatement(
        minorVersion=22,
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        taxPeriod=2025,
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("U1"), security=[security])]
        ),
    )


def _run(calculator_cls, provider, statement):
    calculator = calculator_cls(mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider)
    result = calculator.calculate(statement)
    return result.listOfSecurities.depot[0].security[0]


def test_fillin_keeps_the_dividend_of_a_security_missing_from_the_kursliste(provider):
    security = _run(FillInTaxValueCalculator, provider, _statement())

    assert len(security.payment) == 1
    payment = security.payment[0]
    assert payment.paymentDate == PAY_DATE
    assert payment.amount == Decimal("250.00")
    assert payment.grossRevenueB > Decimal("0")


def test_fillin_books_broker_withholding_as_da1_not_as_negative_revenue(provider):
    security = _run(FillInTaxValueCalculator, provider, _statement())

    payment = security.payment[0]
    gross = payment.grossRevenueB
    # 15% is the non-recoverable share of the US treaty rate; the broker
    # withheld exactly that, so the whole amount is claimable.
    assert payment.nonRecoverableTaxAmount == pytest.approx(gross * Decimal("0.15"))
    assert payment.lumpSumTaxCredit is True
    assert payment.additionalWithHoldingTaxUSA == Decimal("0")
    # Nothing anywhere reduces the gross revenue.
    assert all((p.grossRevenueB or Decimal("0")) >= Decimal("0") for p in security.payment)


def test_fillin_caps_over_withheld_tax_at_the_treaty_non_recoverable_rate(provider):
    # 30% withheld (no W-8BEN on file). Only the 15% treaty residual may be
    # credited in Switzerland; the rest has to be reclaimed from the IRS.
    security = _run(FillInTaxValueCalculator, provider, _statement(withholding=Decimal("75.00")))

    payment = security.payment[0]
    assert payment.nonRecoverableTaxAmount == pytest.approx(payment.grossRevenueB * Decimal("0.15"))
    assert payment.nonRecoverableTaxPercent == Decimal("15.0000")


def test_fillin_leaves_da1_empty_when_no_treaty_rate_is_known(provider, caplog):
    with caplog.at_level("WARNING"):
        security = _run(FillInTaxValueCalculator, provider, _statement(country="ZW"))

    payment = security.payment[0]
    assert payment.grossRevenueB > Decimal("0")
    assert payment.nonRecoverableTaxAmount is None
    assert payment.lumpSumTaxCredit is None
    assert "No Kursliste DA-1 rate for country ZW" in caplog.text


def test_kursliste_mode_still_reports_what_it_dropped(provider):
    statement = _statement()
    calculator = KurslisteTaxValueCalculator(
        mode=CalculationMode.OVERWRITE, exchange_rate_provider=provider
    )
    result = calculator.calculate(statement)

    warnings = [w for w in result.critical_warnings if w.identifier == "US0000000001"]
    assert len(warnings) == 1
    assert "250.00 USD" in warnings[0].message
