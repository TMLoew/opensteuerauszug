"""The Kursliste quotes smaller currencies per 100 units.

``denomination="100" value="10.179"`` means 100 HKD are worth 10.179 CHF.
Ignoring it overstates every balance and every payment in such a currency by a
factor of 100 — silently, and only on the XML code path, so the same statement
came out differently depending on whether the Kursliste had been converted to
SQLite first.
"""

from datetime import date
from decimal import Decimal

import pytest

from opensteuerauszug.core.kursliste_accessor import KurslisteAccessor
from opensteuerauszug.model.kursliste import (
    ExchangeRate,
    ExchangeRateMonthly,
    ExchangeRateYearEnd,
    Kursliste,
)


def _kursliste(**rates):
    return Kursliste(
        version="2.0.0.0",
        creationDate="2026-01-01T00:00:00",
        year=2025,
        **rates,
    )


@pytest.mark.parametrize(
    "denomination,expected",
    [(100, Decimal("0.10179")), (1, Decimal("10.179")), (None, Decimal("10.179"))],
)
def test_year_end_rate_is_divided_by_its_denomination(denomination, expected):
    kwargs = {"currency": "HKD", "year": 2025, "value": Decimal("10.179")}
    if denomination is not None:
        kwargs["denomination"] = denomination
    accessor = KurslisteAccessor(
        [_kursliste(exchangeRatesYearEnd=[ExchangeRateYearEnd(**kwargs)])], 2025
    )

    assert accessor.get_exchange_rate("HKD", date(2025, 12, 31)) == expected


def test_monthly_rate_is_divided_by_its_denomination():
    accessor = KurslisteAccessor(
        [
            _kursliste(
                exchangeRatesMonthly=[
                    ExchangeRateMonthly(
                        currency="HKD",
                        year=2025,
                        month="06",
                        denomination=100,
                        value=Decimal("11.37"),
                    )
                ]
            )
        ],
        2025,
    )

    assert accessor.get_exchange_rate("HKD", date(2025, 6, 15)) == Decimal("0.1137")


def test_daily_rate_is_divided_by_its_denomination():
    accessor = KurslisteAccessor(
        [
            _kursliste(
                exchangeRates=[
                    ExchangeRate(
                        currency="JPY",
                        date=date(2025, 6, 15),
                        denomination=100,
                        value=Decimal("0.5512"),
                    )
                ]
            )
        ],
        2025,
    )

    assert accessor.get_exchange_rate("JPY", date(2025, 6, 15)) == Decimal("0.005512")


def test_a_currency_quoted_per_unit_is_unaffected():
    accessor = KurslisteAccessor(
        [
            _kursliste(
                exchangeRatesYearEnd=[
                    ExchangeRateYearEnd(
                        currency="USD", year=2025, denomination=1, value=Decimal("0.79225")
                    )
                ]
            )
        ],
        2025,
    )

    assert accessor.get_exchange_rate("USD", date(2025, 12, 31)) == Decimal("0.79225")
