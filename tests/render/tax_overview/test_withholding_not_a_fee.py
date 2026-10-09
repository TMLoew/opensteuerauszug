"""Tax withheld at source is not a cost of running the account.

IBKR withholds 20% on credit interest and writes it as a negative cash row.
The overview classified any negative row as a fee, so the withheld tax was
both mislabelled and counted into the cost total the reader uses to judge
what the account costs them.
"""

from datetime import date
from decimal import Decimal

from opensteuerauszug.model.ech0196 import (
    BankAccount,
    BankAccountName,
    BankAccountNumber,
    BankAccountPayment,
    BankAccountTaxValue,
    ListOfBankAccounts,
    TaxStatement,
)
from opensteuerauszug.render.tax_overview.pipeline import _collect_bank_events


def _statement(name, amount, *, flagged):
    account = BankAccount(
        bankAccountNumber=BankAccountNumber("U1234567-USD"),
        bankAccountName=BankAccountName("U1234567 USD"),
        bankAccountCountry="IE",
        bankAccountCurrency="USD",
        taxValue=BankAccountTaxValue(
            referenceDate=date(2025, 12, 31),
            balanceCurrency="USD",
            balance=Decimal("100"),
            exchangeRate=Decimal("0.8"),
            value=Decimal("80"),
        ),
        payment=[
            BankAccountPayment(
                paymentDate=date(2025, 11, 5),
                name=name,
                amountCurrency="USD",
                amount=amount,
                exchangeRate=Decimal("0.8"),
                grossRevenueA=Decimal("0"),
                grossRevenueB=Decimal("0"),
                withHoldingTaxClaim=Decimal("0"),
                is_withholding_tax=flagged,
            )
        ],
    )
    return TaxStatement(
        minorVersion=2, listOfBankAccounts=ListOfBankAccounts(bankAccount=[account])
    )


def _kinds(name, amount, *, flagged=True):
    _, fees = _collect_bank_events(
        _statement(name, amount, flagged=flagged), period_end=date(2025, 12, 31)
    )
    return [f.kind for f in fees]


def test_withheld_tax_is_not_labelled_as_a_fee():
    assert _kinds("WITHHOLDING @ 20% ON CREDIT INT FOR OCT-2025", Decimal("-72.87")) == [
        "withholding_tax"
    ]


def test_the_name_alone_is_enough_when_the_flag_was_lost():
    """`is_withholding_tax` does not survive a round-trip through XML."""
    assert _kinds(
        "WITHHOLDING @ 20% ON CREDIT INT FOR OCT-2025", Decimal("-72.87"), flagged=False
    ) == ["withholding_tax"]


def test_a_genuine_fee_is_still_a_fee():
    assert _kinds("USD BORROW FEES FOR MAY-2025", Decimal("-505.16"), flagged=False) == ["other"]


def test_debit_interest_is_still_its_own_kind():
    assert _kinds("USD DEBIT INT FOR SEP-2025", Decimal("-179.05"), flagged=False) == [
        "interest_debit"
    ]
