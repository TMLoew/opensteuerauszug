"""Country of a security drives its DA-1 grouping, so it must not be guessed.

IBKR leaves ``issuerCountryCode`` empty on a large share of Flex rows. Falling
straight back to "US" silently files e.g. an Irish-domiciled ETF under the US
section of the statement.
"""

import tempfile
from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter

pytest.importorskip("ibflex")


FLEX_WITHOUT_ISSUER_COUNTRY = """
<FlexQueryResponse queryName="CountryQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2025-01-01" toDate="2025-12-31" period="Year" whenGenerated="2026-01-15T10:00:00">
      <Trades>
        <Trade transactionID="1" accountId="U1234567" assetCategory="STK" symbol="VWRL" description="VANGUARD FTSE ALL-WORLD" conid="1001" isin="IE00B3RBWM25" issuerCountryCode="" currency="USD" quantity="10" tradeDate="2025-03-15" settleDateTarget="2025-03-17" tradePrice="100.00" tradeMoney="1000.00" buySell="BUY" ibCommission="-1.00" />
        <Trade transactionID="2" accountId="U1234567" assetCategory="STK" symbol="NESN" description="NESTLE SA" conid="1002" isin="CH0038863350" issuerCountryCode="" currency="CHF" quantity="5" tradeDate="2025-03-15" settleDateTarget="2025-03-17" tradePrice="90.00" tradeMoney="450.00" buySell="BUY" ibCommission="-1.00" />
        <Trade transactionID="3" accountId="U1234567" assetCategory="OPT" symbol="XYZ 250620C100" description="XYZ 20JUN25 100 C" conid="1003" isin="" issuerCountryCode="" currency="USD" quantity="1" tradeDate="2025-03-15" settleDateTarget="2025-03-17" tradePrice="1.00" tradeMoney="100.00" buySell="BUY" ibCommission="-1.00" multiplier="100" />
      </Trades>
      <OpenPositions>
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="VWRL" description="VANGUARD FTSE ALL-WORLD" conid="1001" isin="IE00B3RBWM25" issuerCountryCode="" currency="USD" position="10" markPrice="110.00" positionValue="1100.00" reportDate="2025-12-31" />
        <OpenPosition accountId="U1234567" assetCategory="STK" symbol="NESN" description="NESTLE SA" conid="1002" isin="CH0038863350" issuerCountryCode="" currency="CHF" position="5" markPrice="95.00" positionValue="475.00" reportDate="2025-12-31" />
        <OpenPosition accountId="U1234567" assetCategory="OPT" symbol="XYZ 250620C100" description="XYZ 20JUN25 100 C" conid="1003" isin="" issuerCountryCode="" currency="USD" position="1" markPrice="2.00" positionValue="200.00" reportDate="2025-12-31" multiplier="100" />
      </OpenPositions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="0" fromDate="2025-01-01" toDate="2025-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
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
    statement = importer.import_files([path])
    return {s.securityName: s for s in statement.listOfSecurities.depot[0].security}


def test_country_falls_back_to_the_isin_prefix_when_issuer_country_is_empty():
    securities = _import(FLEX_WITHOUT_ISSUER_COUNTRY)

    assert securities["VANGUARD FTSE ALL-WORLD (VWRL)"].country == "IE"
    assert securities["NESTLE SA (NESN)"].country == "CH"


def test_country_defaults_to_us_only_when_there_is_no_isin_either(caplog):
    with caplog.at_level("WARNING"):
        securities = _import(FLEX_WITHOUT_ISSUER_COUNTRY)

    assert securities["XYZ 20JUN25 100 C (XYZ 250620C100)"].country == "US"
    assert "defaulted to 'US'" in caplog.text


def test_explicit_issuer_country_still_wins_over_the_isin_prefix():
    xml = FLEX_WITHOUT_ISSUER_COUNTRY.replace(
        'isin="IE00B3RBWM25" issuerCountryCode=""',
        'isin="IE00B3RBWM25" issuerCountryCode="GB"',
    )
    securities = _import(xml)

    assert securities["VANGUARD FTSE ALL-WORLD (VWRL)"].country == "GB"


def test_quantities_are_unaffected_by_the_country_fallback():
    securities = _import(FLEX_WITHOUT_ISSUER_COUNTRY)

    closing = [s for s in securities["NESTLE SA (NESN)"].stock if not s.mutation]
    assert [s.quantity for s in closing] == [Decimal("5")]
