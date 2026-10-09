"""The broker's withholding must be converted with the broker's own currency.

Agnico Eagle declares its dividend in CAD while IBKR withholds in USD.  The
cap used whichever exchange rate the Kursliste payment happened to carry, so a
USD withholding was converted at the CAD rate and the DA-1 credit came out
about a quarter too low — a quiet under-claim on a filed statement.
"""

from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.calculate.withholding_cap_calculator import WithholdingCapCalculator
from opensteuerauszug.model.ech0196 import (
    DepotNumber,
    Depot,
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
    """Only knows the rates it is given, and refuses everything else."""

    def __init__(self, **rates):
        self.rates = rates

    def get_exchange_rate(self, currency, reference_date, path_prefix_for_log=None):
        if currency not in self.rates:
            raise ValueError(f"no rate for {currency}")
        return self.rates[currency]


def _statement():
    """Kursliste says CAD 6.92 gross / 1.04 CHF withheld; broker withheld 1.26 USD."""
    kursliste_payment = SecurityPayment(
        paymentDate=PAYMENT_DATE,
        quotationType="PIECE",
        quantity=Decimal("12"),
        amountCurrency="CAD",
        amountPerUnit=Decimal("0.55032"),
        kursliste=True,
        exchangeRate=CAD_RATE,
        grossRevenueB=Decimal("6.9167"),
        nonRecoverableTaxAmount=Decimal("1.0375"),
        lumpSumTaxCredit=True,
        lumpSumTaxCreditPercent=Decimal("15"),
        lumpSumTaxCreditAmount=Decimal("1.0375"),
    )
    broker_payment = SecurityPayment(
        paymentDate=PAYMENT_DATE,
        quotationType="PIECE",
        quantity=Decimal("12"),
        amountCurrency="USD",
        amountPerUnit=Decimal("0.70083"),
        grossRevenueB=Decimal("8.41"),
        nonRecoverableTaxAmountOriginal=Decimal("1.26"),
    )
    security = Security(
        country="CA",
        securityName="AGNICO EAGLE MINES LTD",
        positionId=1,
        currency="CAD",
        quotationType="PIECE",
        securityCategory="SHARE",
        payment=[kursliste_payment],
        broker_payments=[broker_payment],
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
    return (
        TaxStatement(
            minorVersion=2,
            listOfSecurities=ListOfSecurities(
                depot=[Depot(depotNumber=DepotNumber("D1"), security=[security])]
            ),
        ),
        security,
    )


def test_broker_withholding_is_converted_at_its_own_rate():
    """1.26 USD is 1.03 CHF, which is not below the Kursliste 1.04 — no cap."""
    statement, security = _statement()

    WithholdingCapCalculator(exchange_rate_provider=_Rates(USD=USD_RATE, CAD=CAD_RATE)).calculate(
        statement
    )

    assert security.payment[0].nonRecoverableTaxAmount == Decimal("1.0375")


def test_the_cad_rate_is_never_applied_to_a_usd_amount():
    """Without the fix this capped to 1.26 * 0.5954 = 0.75 CHF."""
    statement, security = _statement()

    WithholdingCapCalculator(exchange_rate_provider=_Rates(USD=USD_RATE, CAD=CAD_RATE)).calculate(
        statement
    )

    assert security.payment[0].nonRecoverableTaxAmount != pytest.approx(Decimal("0.75"), abs=0.01)


def test_a_genuinely_lower_broker_withholding_still_caps():
    statement, security = _statement()
    security.broker_payments[0].nonRecoverableTaxAmountOriginal = Decimal("0.63")

    calculator = WithholdingCapCalculator(exchange_rate_provider=_Rates(USD=USD_RATE))
    calculator.calculate(statement)

    # 0.63 USD * 0.81387 = 0.5127 CHF
    assert security.payment[0].nonRecoverableTaxAmount == pytest.approx(
        Decimal("0.5127"), abs=Decimal("0.001")
    )
    assert calculator.capped_securities


def test_an_unconvertible_currency_leaves_the_claim_alone_and_says_so():
    """Better an unverified Kursliste figure than one scaled by a wrong rate."""
    statement, security = _statement()

    calculator = WithholdingCapCalculator(exchange_rate_provider=_Rates(CAD=CAD_RATE))
    calculator.calculate(statement)

    assert security.payment[0].nonRecoverableTaxAmount == Decimal("1.0375")
    assert calculator.unconvertible_withholding == {"AGNICO EAGLE MINES LTD": [PAYMENT_DATE]}


def test_without_a_provider_a_matching_currency_still_works():
    """The Kursliste's own rate is reusable when it converts the same currency."""
    statement, security = _statement()
    security.broker_payments[0].amountCurrency = "CAD"
    security.broker_payments[0].nonRecoverableTaxAmountOriginal = Decimal("0.63")

    calculator = WithholdingCapCalculator()
    calculator.calculate(statement)

    # 0.63 CAD * 0.59537 = 0.3751 CHF
    assert security.payment[0].nonRecoverableTaxAmount == pytest.approx(
        Decimal("0.3751"), abs=Decimal("0.001")
    )
