"""Broker costs belong in the expenses register, and must be visible.

Fees, ADR fees and negative credit interest used to vanish with only a log
line, leaving the statement unable to reconcile against the broker's own cash
report. They are now listed as eCH-0196 expenses — without asserting that any
of them is deductible, which is the assessing authority's call.
"""

import tempfile
from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.config.models import GeneralSettings
from opensteuerauszug.importers.ibkr.ibkr_importer import IbkrImporter
from opensteuerauszug.render.translations import DEFAULT_LANGUAGE, get_text
from opensteuerauszug.model.critical_warning import CriticalWarningCategory

pytest.importorskip("ibflex")


FLEX_WITH_DROPPED_CASH = """
<FlexQueryResponse queryName="FeeQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2025-01-01" toDate="2025-12-31" period="Year" whenGenerated="2026-01-15T10:00:00">
      <CashTransactions>
        <CashTransaction accountId="U1234567" type="Other Fees" currency="USD" amount="-12.00" description="WITHDRAWAL FEE" conid="" symbol="" dateTime="2025-04-10T00:00:00" assetCategory="" />
        <CashTransaction accountId="U1234567" type="Broker Interest Paid" currency="CHF" amount="-2.92" description="CHF CREDIT INT FOR JUL-2025" conid="" symbol="" dateTime="2025-08-05T00:00:00" assetCategory="" />
        <CashTransaction accountId="U1234567" type="Broker Interest Received" currency="USD" amount="10.00" description="USD CREDIT INT FOR SEP-2025" conid="" symbol="" dateTime="2025-10-03T00:00:00" assetCategory="" />
      </CashTransactions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="USD" startingCash="0" endingCash="100.00" fromDate="2025-01-01" toDate="2025-12-31" />
        <CashReportCurrency accountId="U1234567" currency="CHF" startingCash="0" endingCash="50.00" fromDate="2025-01-01" toDate="2025-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


@pytest.fixture(scope="module")
def statement():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as handle:
        handle.write(FLEX_WITH_DROPPED_CASH)
        path = handle.name
    importer = IbkrImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )
    return importer.import_files([path])


def _rendered(message: str) -> str:
    """Recover the "12.00 USD, 2.92 CHF" part from a rendered warning."""
    tpl = get_text("warn_costs_in_expenses", DEFAULT_LANGUAGE)
    head = tpl.split("{rendered}")[0].format(count=2)
    tail = tpl.split("{rendered}")[1]
    return message[len(head) : len(message) - len(tail)]


def test_fees_and_negative_credit_interest_become_expenses(statement):
    assert statement.listOfExpenses is not None
    names = {e.name for e in statement.listOfExpenses.expense}
    assert names == {"WITHDRAWAL FEE", "CHF CREDIT INT FOR JUL-2025"}
    assert all(e.expensesDeductible is None for e in statement.listOfExpenses.expense)


def test_the_costs_are_still_called_out_for_the_reader(statement):
    warnings = [
        w for w in statement.critical_warnings if w.category == CriticalWarningCategory.OTHER
    ]
    assert len(warnings) == 1
    assert warnings[0].message == get_text("warn_costs_in_expenses", DEFAULT_LANGUAGE).format(
        count=2, rendered=_rendered(warnings[0].message)
    )
    assert warnings[0].source == "IbkrImporter"


def test_the_warning_names_the_amounts_per_currency(statement):
    message = statement.critical_warnings[0].message
    assert "12.00 USD" in message
    assert "2.92 CHF" in message


def test_interest_that_is_kept_does_not_show_up_as_omitted(statement):
    accounts = {a.bankAccountCurrency: a for a in statement.listOfBankAccounts.bankAccount}
    assert [p.amount for p in accounts["USD"].payment] == [Decimal("10.00")]
    assert accounts["CHF"].payment == []


WITHHOLDING_ON_INTEREST = """
<FlexQueryResponse queryName="WhtQuery" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="2025-01-01" toDate="2025-12-31" period="Year" whenGenerated="2026-01-15T10:00:00">
      <CashTransactions>
        <CashTransaction accountId="U1234567" type="Broker Interest Received" currency="HKD" amount="84.81" description="HKD CREDIT INT FOR DEC-2024" conid="" symbol="" dateTime="2025-01-06T00:00:00" assetCategory="" />
        <CashTransaction accountId="U1234567" type="Withholding Tax" currency="HKD" amount="-16.96" description="WITHHOLDING @ 20% ON CREDIT INT FOR DEC-2024" conid="" symbol="" dateTime="2025-01-06T00:00:00" assetCategory="" />
        <CashTransaction accountId="U1234567" type="Broker Interest Paid" currency="HKD" amount="-5.00" description="HKD DEBIT INT FOR JAN-2025" conid="" symbol="" dateTime="2025-02-05T00:00:00" assetCategory="" />
      </CashTransactions>
      <CashReport>
        <CashReportCurrency accountId="U1234567" currency="HKD" startingCash="0" endingCash="62.85" fromDate="2025-01-01" toDate="2025-12-31" />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


def _import_withholding_sample():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".xml") as handle:
        handle.write(WITHHOLDING_ON_INTEREST)
        path = handle.name
    importer = IbkrImporter(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        account_settings_list=[],
    )
    statement = importer.import_files([path])
    return CleanupCalculator(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        importer_name="ibkr",
        config_settings=GeneralSettings(canton="ZH", full_name="Test User"),
    ).calculate(statement)


def test_withholding_on_interest_is_not_deducted_as_debt_interest():
    """Tax withheld from interest is not a Schuldzins.

    Every negative bank row used to be moved into the Schuldenverzeichnis, which
    turned foreign withholding tax into a deduction the taxpayer is not entitled
    to.
    """
    statement = _import_withholding_sample()

    liability_names = [
        p.name
        for account in (
            statement.listOfLiabilities.liabilityAccount if statement.listOfLiabilities else []
        )
        for p in account.payment
    ]
    assert liability_names == ["HKD DEBIT INT FOR JAN-2025"]
    assert not any("WITHHOLDING" in n for n in liability_names)


def test_the_withholding_row_stays_on_the_bank_account_as_evidence():
    statement = _import_withholding_sample()
    account = statement.listOfBankAccounts.bankAccount[0]

    withholding = [p for p in account.payment if "WITHHOLDING" in (p.name or "")]
    assert [p.amount for p in withholding] == [Decimal("-16.96")]
    assert all(p.is_withholding_tax for p in withholding)


def test_withholding_on_interest_is_reported_as_unclaimed():
    """It is creditable but eCH-0196 cannot carry it, so it must be named."""
    statement = _import_withholding_sample()

    messages = [w.message for w in statement.critical_warnings]
    foreign = get_text("warn_interest_withholding_foreign", DEFAULT_LANGUAGE).format(
        amounts="16.96 HKD"
    )
    tail = get_text("warn_interest_withholding", DEFAULT_LANGUAGE).split("{parts}")[1]
    assert any(foreign in m for m in messages), messages
    assert any(m.endswith(tail) for m in messages), messages
