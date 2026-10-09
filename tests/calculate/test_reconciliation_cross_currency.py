"""A dividend settled in another currency is still comparable.

The Kursliste records Agnico Eagle in CAD; IBKR pays it in USD.  Refusing to
compare the two turned a payment that reconciles to the centime into a
"check this by hand" line.  Enough of those and the reader stops reading the
list — which is where the genuine findings live.
"""

from datetime import date
from decimal import Decimal

from opensteuerauszug.calculate.payment_reconciliation_calculator import (
    PaymentReconciliationCalculator,
)
from opensteuerauszug.model.ech0196 import (
    Depot,
    DepotNumber,
    ListOfSecurities,
    Security,
    SecurityPayment,
    SecurityStock,
    SecurityTaxValue,
    TaxStatement,
)

PAYMENT_DATE = date(2025, 6, 16)
USD_RATE = Decimal("0.8138738095")
CAD_RATE = Decimal("0.5953665714")


class _Rates:
    def __init__(self, **rates):
        self.rates = rates

    def get_exchange_rate(self, currency, reference_date, path_prefix_for_log=None):
        if currency not in self.rates:
            raise ValueError(f"no rate for {currency}")
        return self.rates[currency]


def _statement(broker_dividend=Decimal("8.41"), broker_withholding=Decimal("1.26")):
    kursliste_payment = SecurityPayment(
        paymentDate=PAYMENT_DATE,
        quotationType="PIECE",
        quantity=Decimal("12"),
        amountCurrency="CAD",
        amountPerUnit=Decimal("0.55032"),
        exchangeRate=CAD_RATE,
        kursliste=True,
        grossRevenueB=Decimal("6.9167"),
        nonRecoverableTaxAmount=Decimal("1.0375"),
    )
    # The broker reports the dividend and its withholding as separate rows.
    broker_dividend_row = SecurityPayment(
        paymentDate=PAYMENT_DATE,
        quotationType="PIECE",
        quantity=Decimal("12"),
        amountCurrency="USD",
        amountPerUnit=broker_dividend / Decimal("12"),
        amount=broker_dividend,
        grossRevenueB=broker_dividend,
    )
    broker_withholding_row = SecurityPayment(
        paymentDate=PAYMENT_DATE,
        quotationType="PIECE",
        quantity=Decimal("12"),
        amountCurrency="USD",
        amountPerUnit=Decimal("0"),
        nonRecoverableTaxAmountOriginal=broker_withholding,
    )
    security = Security(
        country="CA",
        securityName="AGNICO EAGLE MINES LTD",
        positionId=1,
        currency="CAD",
        quotationType="PIECE",
        securityCategory="SHARE",
        payment=[kursliste_payment],
        broker_payments=[broker_dividend_row, broker_withholding_row],
        taxValue=SecurityTaxValue(
            referenceDate=date(2025, 12, 31),
            quotationType="PIECE",
            quantity=Decimal("12"),
            balanceCurrency="CAD",
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2025, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=Decimal("12"),
                balanceCurrency="CAD",
            )
        ],
    )
    return TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[Depot(depotNumber=DepotNumber("D1"), security=[security])]
        ),
    )


def _rows(statement):
    return statement.payment_reconciliation_report.rows


def test_a_usd_settled_cad_dividend_reconciles():
    statement = _statement()

    PaymentReconciliationCalculator(
        tolerance_chf=Decimal("0.10"),
        exchange_rate_provider=_Rates(USD=USD_RATE, CAD=CAD_RATE),
    ).calculate(statement)

    (row,) = _rows(statement)
    assert row.status == "match", row.note


def test_a_genuine_difference_across_currencies_is_still_reported():
    """Converting correctly must not paper over a real discrepancy."""
    statement = _statement(broker_dividend=Decimal("20.00"))

    PaymentReconciliationCalculator(
        tolerance_chf=Decimal("0.10"),
        exchange_rate_provider=_Rates(USD=USD_RATE, CAD=CAD_RATE),
    ).calculate(statement)

    (row,) = _rows(statement)
    assert row.status == "mismatch"


def test_without_a_rate_the_reader_is_told_to_check_by_hand():
    statement = _statement()

    PaymentReconciliationCalculator(
        tolerance_chf=Decimal("0.10"), exchange_rate_provider=_Rates(CAD=CAD_RATE)
    ).calculate(statement)

    (row,) = _rows(statement)
    assert row.status == "mismatch"
    assert "no exchange rate for USD" in row.note
    assert "by hand" in row.note


def test_the_cad_rate_is_never_applied_to_the_usd_amount():
    """8.41 USD at the CAD rate is 5.01 CHF — a 1.90 CHF shortfall that is not real.

    A tolerance tight enough to catch that still has to see this as a match.
    """
    statement = _statement()

    PaymentReconciliationCalculator(
        tolerance_chf=Decimal("0.20"),
        exchange_rate_provider=_Rates(USD=USD_RATE, CAD=CAD_RATE),
    ).calculate(statement)

    (row,) = _rows(statement)
    assert row.status == "match", row.note
