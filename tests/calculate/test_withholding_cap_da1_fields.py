"""Capping withholding must also bring the DA-1 claim fields down with it.

``lumpSumTaxCredit*`` / ``nonRecoverableTax*`` are what the tax software reads
to build the DA-1 (pauschale Steueranrechnung) claim.  When the broker
reversed or under-withheld foreign tax relative to the Kursliste rate, leaving
those fields at the Kursliste level claims relief for tax that was never paid.
"""

from datetime import date
from decimal import Decimal

from opensteuerauszug.calculate.withholding_cap_calculator import WithholdingCapCalculator
from opensteuerauszug.model.ech0196 import (
    Depot,
    DepotNumber,
    ISINType,
    ListOfSecurities,
    Security,
    SecurityPayment,
    TaxStatement,
)

PAY_DATE = date(2025, 11, 5)
RATE = Decimal("0.90")


def _statement(broker_wht_usd, gross_chf, kurs_non_recoverable_chf, lump_sum_chf):
    """US ETF with a Kursliste (Q) payment carrying a full DA-1 claim."""
    broker = [
        SecurityPayment(
            paymentDate=PAY_DATE,
            quotationType="PIECE",
            quantity=Decimal("-1"),
            amountCurrency="USD",
            nonRecoverableTaxAmountOriginal=amount,
        )
        for amount in broker_wht_usd
    ]
    kursliste = SecurityPayment(
        paymentDate=PAY_DATE,
        quotationType="PIECE",
        quantity=Decimal("254"),
        amountCurrency="USD",
        exchangeRate=RATE,
        grossRevenueA=Decimal("0"),
        grossRevenueB=gross_chf,
        withHoldingTaxClaim=Decimal("0"),
        nonRecoverableTaxAmount=kurs_non_recoverable_chf,
        nonRecoverableTaxPercent=Decimal("15"),
        lumpSumTaxCredit=True,
        lumpSumTaxCreditPercent=Decimal("30"),
        lumpSumTaxCreditAmount=lump_sum_chf,
        additionalWithHoldingTaxUSA=Decimal("0"),
        kursliste=True,
        sign="(Q)",
    )
    return TaxStatement(
        minorVersion=2,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="US",
                            currency="USD",
                            quotationType="PIECE",
                            securityCategory="FUND",
                            securityName="TEST US ETF",
                            isin=ISINType("US9219378356"),
                            payment=[kursliste],
                            broker_payments=broker,
                        )
                    ],
                )
            ]
        ),
    )


def _kursliste_payment(statement):
    security = statement.listOfSecurities.depot[0].security[0]
    return next(p for p in security.payment if p.kursliste)


def test_full_reversal_drops_the_da1_claim():
    # Broker withheld 15.00 USD and reversed all of it after the 1042-S.
    statement = _statement(
        broker_wht_usd=[Decimal("15.00"), Decimal("-15.00")],
        gross_chf=Decimal("100.00"),
        kurs_non_recoverable_chf=Decimal("15.00"),
        lump_sum_chf=Decimal("30.00"),
    )

    payment = _kursliste_payment(WithholdingCapCalculator().calculate(statement))

    assert payment.nonRecoverableTaxAmount == Decimal("0.00")
    assert payment.lumpSumTaxCreditAmount == Decimal("0.00")
    assert payment.lumpSumTaxCredit is None
    assert payment.lumpSumTaxCreditPercent is None
    assert payment.nonRecoverableTaxPercent is None


def test_partial_cap_scales_the_da1_percentages_to_the_capped_amount():
    # Broker withheld 5.00 USD = 4.50 CHF instead of the Kursliste 15.00 CHF.
    statement = _statement(
        broker_wht_usd=[Decimal("5.00")],
        gross_chf=Decimal("100.00"),
        kurs_non_recoverable_chf=Decimal("15.00"),
        lump_sum_chf=Decimal("30.00"),
    )

    payment = _kursliste_payment(WithholdingCapCalculator().calculate(statement))

    assert payment.nonRecoverableTaxAmount == Decimal("4.50")
    assert payment.nonRecoverableTaxPercent == Decimal("4.5000")
    # The part recoverable abroad was not withheld either, so the combined
    # claim cannot exceed what the broker actually took.
    assert payment.lumpSumTaxCreditAmount == Decimal("4.50")
    assert payment.lumpSumTaxCreditPercent == Decimal("4.5000")


def test_matching_broker_withholding_leaves_the_da1_claim_untouched():
    statement = _statement(
        broker_wht_usd=[Decimal("16.67")],  # 16.67 * 0.90 = 15.003 CHF
        gross_chf=Decimal("100.00"),
        kurs_non_recoverable_chf=Decimal("15.00"),
        lump_sum_chf=Decimal("30.00"),
    )

    payment = _kursliste_payment(WithholdingCapCalculator().calculate(statement))

    assert payment.nonRecoverableTaxAmount == Decimal("15.00")
    assert payment.lumpSumTaxCreditAmount == Decimal("30.00")
    assert payment.lumpSumTaxCreditPercent == Decimal("30")
    assert payment.withholding_capped is False
