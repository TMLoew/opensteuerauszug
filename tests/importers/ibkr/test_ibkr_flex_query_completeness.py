"""Guards against Flex Query exports that are quietly incomplete.

All three cases here come from a real IBKR export: a query that emits cash
transactions at two levels of detail without the field that tells them apart,
one that omits ``multiplier`` on option trades, and one that carries dividends
but no withholding tax. Each of them produced a wrong statement rather than an
error.
"""

import tempfile
from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.calculate.withholding_cap_calculator import WithholdingCapCalculator
from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.model.critical_warning import CriticalWarningCategory
from opensteuerauszug.model.ech0196 import (
    Depot,
    DepotNumber,
    ListOfSecurities,
    Security,
    SecurityPayment,
    TaxStatement,
)

pytest.importorskip("ibflex")

HEAD = """
<FlexQueryResponse queryName="Q" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2025-01-01" toDate="2025-12-31" period="Year" whenGenerated="2026-01-15T10:00:00">
"""
TAIL = """
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="100" fromDate="2025-01-01" toDate="2025-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""

STOCK = """
      <Trades>
        <Trade accountId="U1234567" assetCategory="STK" symbol="AAA" description="ALPHA" conid="1" isin="US0000000011" issuerCountryCode="US" currency="USD" quantity="100" tradeDate="2025-02-10" settleDateTarget="2025-02-12" tradePrice="10" tradeMoney="1000" buySell="BUY" ibCommission="-1" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="AAA" description="ALPHA" conid="1" isin="US0000000011" issuerCountryCode="US" currency="USD" position="100" markPrice="12" positionValue="1200" reportDate="2025-12-31" />
      </OpenPositions>
"""


def _import(xml_text):
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as handle:
        handle.write(xml_text)
        path = handle.name
    importer = IbkrImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )
    return importer.import_files([path])


# --- cash transactions exported at more than one level of detail -------------

MIXED_LEVELS_NO_FLAG = HEAD + STOCK + """
      <CashTransactions>
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="50.00" description="AAA CASH DIVIDEND" conid="1" symbol="AAA" dateTime="20250615" assetCategory="STK" />
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="50.00" description="AAA CASH DIVIDEND" conid="1" symbol="AAA" dateTime="20250615;202000" assetCategory="STK" />
      </CashTransactions>
""" + TAIL


def test_cash_transactions_at_two_levels_without_the_flag_are_refused():
    with pytest.raises(ValueError, match="more than one level of detail"):
        _import(MIXED_LEVELS_NO_FLAG)


def test_the_refusal_says_how_to_fix_the_flex_query():
    with pytest.raises(ValueError) as excinfo:
        _import(MIXED_LEVELS_NO_FLAG)
    assert "single level of detail" in str(excinfo.value)
    assert "Level of Detail" in str(excinfo.value)


def test_levels_that_are_labelled_are_reduced_to_the_summary_rows():
    labelled = MIXED_LEVELS_NO_FLAG.replace(
        'dateTime="20250615" assetCategory="STK" />',
        'dateTime="20250615" assetCategory="STK" levelOfDetail="SUMMARY" />',
    ).replace(
        'dateTime="20250615;202000" assetCategory="STK" />',
        'dateTime="20250615;202000" assetCategory="STK" levelOfDetail="DETAIL" />',
    )
    statement = _import(labelled)
    security = statement.listOfSecurities.depot[0].security[0]

    assert [p.amount for p in security.payment] == [Decimal("50.00")]


def test_a_single_level_export_is_left_alone():
    single = HEAD + STOCK + """
      <CashTransactions>
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="50.00" description="AAA CASH DIVIDEND" conid="1" symbol="AAA" dateTime="20250615" assetCategory="STK" />
      </CashTransactions>
""" + TAIL
    statement = _import(single)

    assert [p.amount for p in statement.listOfSecurities.depot[0].security[0].payment] == [
        Decimal("50.00")
    ]


# --- multiplier missing from the trade rows ---------------------------------

OPTION_WITHOUT_MULTIPLIER = HEAD + """
      <Trades>
        <Trade accountId="U1234567" assetCategory="OPT" subCategory="C" symbol="AAA  260220C00100000" description="AAA 20FEB26 100 C" conid="900" isin="" currency="USD" quantity="2" tradeDate="2025-06-01" settleDateTarget="2025-06-02" tradePrice="3.00" tradeMoney="600" buySell="BUY" ibCommission="-1" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="OPT" subCategory="C" symbol="AAA  260220C00100000" description="AAA 20FEB26 100 C" conid="900" isin="" currency="USD" position="2" markPrice="4.00" positionValue="800" reportDate="2025-12-31" />
      </OpenPositions>
      <SecuritiesInfo>
        <SecurityInfo assetCategory="OPT" subCategory="C" symbol="AAA  260220C00100000" description="AAA 20FEB26 100 C" conid="900" multiplier="100" strike="100" expiry="20260220" putCall="C" currency="USD" />
      </SecuritiesInfo>
""" + TAIL


def test_option_multiplier_is_taken_from_securities_info_when_the_trade_lacks_it():
    statement = _import(OPTION_WITHOUT_MULTIPLIER)
    security = statement.listOfSecurities.depot[0].security[0]
    mutation = next(s for s in security.stock if s.mutation)

    # 3.00 per share x 100 per contract.
    assert mutation.unitPrice == Decimal("300")


def test_missing_multiplier_without_securities_info_names_the_flex_fields():
    start = OPTION_WITHOUT_MULTIPLIER.index("      <SecuritiesInfo>")
    end = OPTION_WITHOUT_MULTIPLIER.index("</SecuritiesInfo>") + len("</SecuritiesInfo>\n")
    without_info = OPTION_WITHOUT_MULTIPLIER[:start] + OPTION_WITHOUT_MULTIPLIER[end:]

    with pytest.raises(ValueError) as excinfo:
        _import(without_info)
    assert "Multiplier" in str(excinfo.value)


# --- withholding tax absent from the export ---------------------------------

DIVIDEND_WITHOUT_WITHHOLDING = HEAD + STOCK + """
      <CashTransactions>
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="50.00" description="AAA CASH DIVIDEND" conid="1" symbol="AAA" dateTime="20250615" assetCategory="STK" />
      </CashTransactions>
""" + TAIL


def test_dividends_without_any_withholding_row_are_flagged_as_incomplete():
    statement = _import(DIVIDEND_WITHOUT_WITHHOLDING)

    assert statement.broker_reports_withholding_tax is False
    messages = [w.message for w in statement.critical_warnings]
    assert any("no withholding tax records" in m for m in messages)


def test_an_export_with_withholding_is_not_flagged():
    with_wht = DIVIDEND_WITHOUT_WITHHOLDING.replace(
        "</CashTransactions>",
        '<CashTransaction accountId="U1234567" type="Withholding Tax" currency="USD" '
        'amount="-7.50" description="AAA CASH DIVIDEND - US TAX" conid="1" symbol="AAA" '
        'dateTime="20250615" assetCategory="STK" />\n      </CashTransactions>',
    )
    statement = _import(with_wht)

    assert statement.broker_reports_withholding_tax is True


def _statement_with_kursliste_claim(flag):
    """A Kursliste payment carrying withholding, and a broker row without any."""
    return TaxStatement(
        minorVersion=2,
        broker_reports_withholding_tax=flag,
        listOfSecurities=ListOfSecurities(
            depot=[
                Depot(
                    depotNumber=DepotNumber("D1"),
                    security=[
                        Security(
                            positionId=1,
                            country="CH",
                            currency="CHF",
                            quotationType="PIECE",
                            securityCategory="SHARE",
                            securityName="NESTLE SA-REG",
                            payment=[
                                SecurityPayment(
                                    paymentDate=date(2025, 4, 24),
                                    quotationType="PIECE",
                                    quantity=Decimal("50"),
                                    amountCurrency="CHF",
                                    exchangeRate=Decimal("1"),
                                    grossRevenueA=Decimal("152.50"),
                                    grossRevenueB=Decimal("0"),
                                    withHoldingTaxClaim=Decimal("53.38"),
                                    kursliste=True,
                                ),
                            ],
                            broker_payments=[
                                SecurityPayment(
                                    paymentDate=date(2025, 4, 24),
                                    quotationType="PIECE",
                                    quantity=Decimal("50"),
                                    amountCurrency="CHF",
                                    amount=Decimal("152.50"),
                                ),
                            ],
                        )
                    ],
                )
            ]
        ),
    )


def test_withholding_is_not_capped_away_when_the_export_carries_no_withholding():
    statement = WithholdingCapCalculator().calculate(_statement_with_kursliste_claim(False))
    payment = statement.listOfSecurities.depot[0].security[0].payment[0]

    assert payment.withHoldingTaxClaim == Decimal("53.38")
    assert payment.grossRevenueA == Decimal("152.50")
    assert any(
        w.category == CriticalWarningCategory.OTHER and "no withholding tax entries" in w.message
        for w in statement.critical_warnings
    )


def test_withholding_is_still_capped_when_the_export_does_carry_withholding():
    statement = WithholdingCapCalculator().calculate(_statement_with_kursliste_claim(True))
    payment = statement.listOfSecurities.depot[0].security[0].payment[0]

    assert payment.withHoldingTaxClaim == Decimal("0.00")
