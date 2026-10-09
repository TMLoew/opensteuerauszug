"""The name on the statement must be the name on the tax return.

A broker spells the account holder however its own records do — IBKR issues
this account to "Hans P Mueller" — and an assessor receiving two statements
for one taxpayer under two spellings has a question to ask.  `full_name`
could not fix it: it splits on the first space, so "Hans Peter Müller"
yields the surname "Peter Müller".  Hence explicit first/last names that
override whatever the importer supplied.
"""

from datetime import date
from decimal import Decimal


from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.config.models import GeneralSettings
from opensteuerauszug.model.ech0196 import Client, ClientNumber, TaxStatement


def _statement(first=None, last=None):
    return TaxStatement(
        minorVersion=2,
        canton="SG",
        periodFrom=date(2025, 1, 1),
        periodTo=date(2025, 12, 31),
        taxPeriod=2025,
        client=[Client(clientNumber=ClientNumber("U1234567"), firstName=first, lastName=last)],
    )


def _run(statement, **settings):
    CleanupCalculator(
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        importer_name="ibkr",
        config_settings=GeneralSettings(canton="SG", **settings),
    ).calculate(statement)
    return statement.client[0]


def test_explicit_names_override_what_the_broker_supplied():
    client = _run(
        _statement("Hans", "M Mueller"),
        first_name="Hans Peter",
        last_name="Müller",
    )
    assert (client.firstName, client.lastName) == ("Hans Peter", "Müller")


def test_full_name_alone_still_only_fills_blanks():
    """Unchanged behaviour for configs written before the explicit fields."""
    client = _run(_statement("Hans", "M Mueller"), full_name="Someone Else")
    assert (client.firstName, client.lastName) == ("Hans", "M Mueller")


def test_full_name_still_fills_a_blank():
    client = _run(_statement(None, None), full_name="Hans Müller")
    assert (client.firstName, client.lastName) == ("Hans", "Müller")


def test_explicit_names_beat_full_name():
    client = _run(
        _statement(None, None),
        full_name="Hans Peter Müller",
        first_name="Hans Peter",
        last_name="Müller",
    )
    # full_name alone would have produced the surname "Peter Müller"
    assert (client.firstName, client.lastName) == ("Hans Peter", "Müller")


def test_only_a_surname_may_be_overridden():
    client = _run(_statement("Hans", "Mueller"), last_name="Müller")
    assert (client.firstName, client.lastName) == ("Hans", "Müller")


def test_no_name_configuration_leaves_the_client_untouched():
    client = _run(_statement("Hans", "M Mueller"))
    assert (client.firstName, client.lastName) == ("Hans", "M Mueller")


def test_withheld_tax_is_not_swept_into_liabilities_after_a_round_trip():
    """`is_withholding_tax` is exclude=True and dies in the XML.

    A dumped-and-reimported statement must still not deduct withheld tax as
    Schuldzins, so the description has to carry the distinction.
    """
    from opensteuerauszug.calculate.cleanup import _is_withholding_payment
    from opensteuerauszug.model.ech0196 import BankAccountPayment

    def payment(name, flagged):
        return BankAccountPayment(
            paymentDate=date(2025, 11, 5),
            name=name,
            amountCurrency="USD",
            amount=Decimal("-72.87"),
            grossRevenueA=Decimal("0"),
            grossRevenueB=Decimal("0"),
            withHoldingTaxClaim=Decimal("0"),
            is_withholding_tax=flagged,
        )

    withholding = "WITHHOLDING @ 20% ON CREDIT INT FOR OCT-2025"
    assert _is_withholding_payment(payment(withholding, True)) is True
    # the flag is gone after a round-trip; the name must still save it
    assert _is_withholding_payment(payment(withholding, False)) is True
    # a real cost is still a cost
    assert _is_withholding_payment(payment("USD DEBIT INT FOR SEP-2025", False)) is False
