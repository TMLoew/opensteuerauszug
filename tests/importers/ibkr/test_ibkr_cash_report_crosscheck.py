"""The broker's own totals are the one check that does not trust our parsing.

Everything else here reads the same transaction rows we read.  IBKR's Cash
Report sums those movements independently, so comparing against it is what
catches a statement whose dividends are doubled or whose withholding never
arrived — failures that look entirely plausible in the finished PDF.
"""

import tempfile
from datetime import date

import pytest

from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.render.translations import DEFAULT_LANGUAGE, get_text
from opensteuerauszug.model.critical_warning import CriticalWarningCategory

pytest.importorskip("ibflex")


def _flex(cash_report_attributes: str, transactions: str = "") -> str:
    rows = transactions or """
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="100.00" description="ACME CASH DIVIDEND" conid="1" symbol="ACME" isin="US0000000001" dateTime="2025-04-10T00:00:00" assetCategory="STK" />
        <CashTransaction accountId="U1234567" type="Withholding Tax" currency="USD" amount="-15.00" description="ACME WITHHOLDING" conid="1" symbol="ACME" isin="US0000000001" dateTime="2025-04-10T00:00:00" assetCategory="STK" />
        """
    return f"""
<FlexQueryResponse queryName="CrossCheck" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2025-01-01" toDate="2025-12-31" period="Year" whenGenerated="2026-01-15T10:00:00">
      <CashTransactions>{rows}</CashTransactions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="85.00" fromDate="2025-01-01" toDate="2025-12-31" {cash_report_attributes} />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


def _import(xml: str):
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as handle:
        handle.write(xml)
        path = handle.name
    importer = IbkrImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )
    return importer.import_files([path])


def _mismatch_head():
    """The fixed opening of the mismatch warning, in whatever language it ships."""
    return get_text("warn_cash_report_mismatch", DEFAULT_LANGUAGE).split("{listed}")[0]


def _crosscheck_warnings(statement):
    return [
        w
        for w in statement.critical_warnings
        if w.category == CriticalWarningCategory.OTHER and w.message.startswith(_mismatch_head())
    ]


def test_matching_totals_raise_nothing():
    statement = _import(_flex('dividends="100.00" withholdingTax="-15.00"'))
    assert _crosscheck_warnings(statement) == []


def test_a_missing_dividend_is_caught():
    """The broker collected more than we booked: income would be understated."""
    statement = _import(_flex('dividends="180.00" withholdingTax="-15.00"'))

    (warning,) = _crosscheck_warnings(statement)
    assert (
        "dividends USD: broker reports 180.00, imported 100.00 (off by -80.00)" in warning.message
    )


def test_doubled_transactions_are_caught():
    """The failure mode of a Flex Query exporting both SUMMARY and DETAIL rows."""
    doubled = """
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="100.00" description="ACME CASH DIVIDEND" conid="1" symbol="ACME" isin="US0000000001" dateTime="2025-04-10T00:00:00" assetCategory="STK" />
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="100.00" description="ACME CASH DIVIDEND SECOND LOT" conid="1" symbol="ACME" isin="US0000000001" dateTime="2025-04-11T00:00:00" assetCategory="STK" />
    """
    statement = _import(_flex('dividends="100.00"', transactions=doubled))

    (warning,) = _crosscheck_warnings(statement)
    assert "imported 200.00 (off by +100.00)" in warning.message
    assert warning.message.endswith(
        get_text("warn_cash_report_mismatch", DEFAULT_LANGUAGE).split("{listed}")[1]
    )


def test_withholding_that_never_arrived_is_caught():
    """Missing withholding silently forfeits the DA-1 credit it should carry."""
    statement = _import(
        _flex(
            'dividends="100.00" withholdingTax="-15.00"',
            transactions="""
        <CashTransaction accountId="U1234567" type="Dividends" currency="USD" amount="100.00" description="ACME CASH DIVIDEND" conid="1" symbol="ACME" isin="US0000000001" dateTime="2025-04-10T00:00:00" assetCategory="STK" />
        """,
        )
    )

    (warning,) = _crosscheck_warnings(statement)
    assert (
        "withholding tax USD: broker reports -15.00, imported 0.00 (off by +15.00)"
        in warning.message
    )


def test_a_rounding_difference_is_tolerated():
    statement = _import(_flex('dividends="100.004" withholdingTax="-15.00"'))
    assert _crosscheck_warnings(statement) == []


def test_absent_totals_do_not_alarm_the_reader(caplog):
    """Most exports leave these boxes unticked; that is not a defect to report."""
    statement = _import(_flex(""))

    assert _crosscheck_warnings(statement) == []


BROKER_INTEREST_ROWS = """
        <CashTransaction accountId="U1234567" type="Broker Interest Received" currency="USD" amount="857.85" description="USD CREDIT INT" conid="" symbol="" dateTime="2025-10-03T00:00:00" assetCategory="" />
        <CashTransaction accountId="U1234567" type="Broker Interest Paid" currency="USD" amount="-837.29" description="USD DEBIT INT" conid="" symbol="" dateTime="2025-10-03T00:00:00" assetCategory="" />
"""


def test_broker_interest_is_compared_net_of_interest_paid():
    """IBKR reports brokerInterest net: 857.85 received - 837.29 paid = 20.56."""
    statement = _import(_flex('brokerInterest="20.56"', transactions=BROKER_INTEREST_ROWS))

    assert _crosscheck_warnings(statement) == []


def test_a_received_only_broker_interest_total_is_still_caught():
    """Guards the assumption: were it received-only, 857.85 would have to fail."""
    statement = _import(_flex('brokerInterest="857.85"', transactions=BROKER_INTEREST_ROWS))

    (warning,) = _crosscheck_warnings(statement)
    assert "broker interest USD" in warning.message


def test_missing_interest_paid_shows_up_as_a_divergence():
    only_received = """
        <CashTransaction accountId="U1234567" type="Broker Interest Received" currency="USD" amount="857.85" description="USD CREDIT INT" conid="" symbol="" dateTime="2025-10-03T00:00:00" assetCategory="" />
    """
    statement = _import(_flex('brokerInterest="20.56"', transactions=only_received))

    (warning,) = _crosscheck_warnings(statement)
    assert "imported 857.85" in warning.message
