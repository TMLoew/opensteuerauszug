"""An expired option contract has no ISIN, so the advice cannot be followed.

The statement told the reader to add 22 option contracts to
security_identifiers.csv. None of them is a listed security with an identifier
to add, none was worth anything at year end, and none paid income — so the
advice was both impossible and pointless, while burying the warnings that
did matter.
"""

from datetime import date
from decimal import Decimal

from opensteuerauszug.calculate.cleanup import CleanupCalculator
from opensteuerauszug.model.ech0196 import (
    Security,
    SecurityPayment,
    SecurityStock,
    SecurityTaxValue,
)


def _calc():
    return CleanupCalculator(
        period_from=date(2025, 1, 1), period_to=date(2025, 12, 31), importer_name="ibkr"
    )


def _option(*, closing: Decimal, payments=None, with_tax_value=True):
    return Security(
        country="US",
        securityName="NVDA 21NOV25 197.5 C",
        symbol="NVDA  251121C00197500",
        positionId=1,
        currency="USD",
        quotationType="PIECE",
        securityCategory="OPTION",
        payment=payments or [],
        taxValue=(
            SecurityTaxValue(
                referenceDate=date(2025, 12, 31),
                quotationType="PIECE",
                quantity=closing,
                balanceCurrency="USD",
            )
            if with_tax_value
            else None
        ),
        stock=[
            SecurityStock(
                referenceDate=date(2026, 1, 1),
                mutation=False,
                quotationType="PIECE",
                quantity=closing,
                balanceCurrency="USD",
            )
        ],
    )


def test_an_expired_contract_raises_no_warning():
    assert _calc()._security_has_tax_effect(_option(closing=Decimal("0"))) is False


def test_a_position_still_held_does_warn():
    assert _calc()._security_has_tax_effect(_option(closing=Decimal("5"))) is True


def test_a_closed_position_that_paid_income_still_warns():
    paid = _option(
        closing=Decimal("0"),
        payments=[
            SecurityPayment(
                paymentDate=date(2025, 6, 1),
                quotationType="PIECE",
                quantity=Decimal("100"),
                amountCurrency="USD",
                amountPerUnit=Decimal("1"),
                grossRevenueB=Decimal("100"),
            )
        ],
    )
    assert _calc()._security_has_tax_effect(paid) is True


def test_an_undeterminable_balance_keeps_the_warning():
    """Silence has to be earned; when we cannot tell, we still speak up."""
    bare = _option(closing=Decimal("0"), with_tax_value=False)
    bare.stock = []
    assert _calc()._security_has_tax_effect(bare) is True
