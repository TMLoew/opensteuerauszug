"""
Security-related business logic and utilities.

This module provides functions for working with securities in tax statements,
including determining their tax classification type.

Tax classification of securities:
- Type A: Swiss securities or securities with grossRevenueA (withholding tax claim)
- Type B: Non-Swiss securities without withholding tax claims
- Type DA1: Securities with non-recoverable tax or additional withholding tax USA
"""

from decimal import Decimal
from typing import Literal, Optional, List

from opensteuerauszug.model.ech0196 import Security, SecurityPayment

SecurityType = Literal["A", "B", "DA1"]


def determine_security_type(security: Security) -> SecurityType:
    """
    Determine if a security belongs to type 'A', 'B', or 'DA1'.

    Rules:
    - DA1: If the security has payments with a non-recoverable tax or additionalWithHoldingTaxUSA
    - A: If the security has grossRevenueA in any payment, or if there's no revenue but the country is CH
    - B: All other cases

    Args:
        security: The security to evaluate

    Returns:
        One of "A", "B", or "DA1" representing the security type
    """
    # Check if it's a DA1 security (has non-recoverable tax or USA withholding tax)
    if _has_da1_payments(security.payment):
        return "DA1"

    # Check if it's type A (has grossRevenueA or is Swiss with no revenue)
    if _has_type_a_revenue(security.payment) or (
        security.country == "CH" and not _has_any_revenue(security.payment)
    ):
        return "A"

    # Default to type B
    return "B"


def _has_da1_payments(payments: Optional[List[SecurityPayment]]) -> bool:
    """Check if any payment has non-recoverable tax or USA withholding tax."""
    if not payments:
        return False

    for payment in payments:
        # Check for non-recoverable tax
        if (payment.nonRecoverableTaxAmount and payment.nonRecoverableTaxAmount > Decimal("0")) or (
            payment.nonRecoverableTaxAmountOriginal
            and payment.nonRecoverableTaxAmountOriginal > Decimal("0")
        ):
            return True

        # Check for USA withholding tax
        if payment.additionalWithHoldingTaxUSA and payment.additionalWithHoldingTaxUSA > Decimal(
            "0"
        ):
            return True

    return False


def _has_type_a_revenue(payments: Optional[List[SecurityPayment]]) -> bool:
    """Check if any payment has grossRevenueA greater than 0."""
    if not payments:
        return False

    for payment in payments:
        if payment.grossRevenueA and payment.grossRevenueA > Decimal("0"):
            return True

    return False


def _has_any_revenue(payments: Optional[List[SecurityPayment]]) -> bool:
    """Check if any payment has any type of revenue."""
    if not payments:
        return False

    for payment in payments:
        if (payment.grossRevenueA and payment.grossRevenueA > Decimal("0")) or (
            payment.grossRevenueB and payment.grossRevenueB > Decimal("0")
        ):
            return True

    return False


# ISIN prefixes that are not ISO 3166-1 alpha-2 country codes. "XS" is the
# Euroclear/Clearstream international prefix, "EU" is used for European
# institutions, and the "XA".."XF" / "QS" / "QT" ranges are CUSIP
# International / internally assigned numbers.  Everything else in the ISIN
# prefix position is a real country code by construction.
_NON_COUNTRY_ISIN_PREFIXES = ("X", "Q")


def country_from_isin(isin: Optional[str]) -> Optional[str]:
    """Return the issuer country encoded in *isin*, or ``None``.

    The first two characters of an ISIN are the ISO 3166-1 alpha-2 code of the
    numbering agency that assigned it, which is the best available proxy for
    the country of a security when the broker does not report one.  Codes from
    the reserved international ranges carry no country information and yield
    ``None`` so the caller can fall back or warn.
    """
    if not isin or len(isin) < 2:
        return None
    prefix = str(isin)[:2].upper()
    if not prefix.isalpha():
        return None
    if prefix.startswith(_NON_COUNTRY_ISIN_PREFIXES) or prefix == "EU":
        return None
    return prefix
