from decimal import Decimal

from typing import Optional
import logging

from opensteuerauszug.model.ech0196 import SecurityPayment, Security, SecurityTaxValue
from .kursliste_tax_value_calculator import KurslisteTaxValueCalculator
from .base import CalculationMode
from ..core.exchange_rate_provider import ExchangeRateProvider
from ..core.flag_override_provider import FlagOverrideProvider
from ..core.manual_price_provider import ManualPriceProvider

logger = logging.getLogger(__name__)

class FillInTaxValueCalculator(KurslisteTaxValueCalculator):
    """
    Calculator that fills in missing values based on other available data,
    potentially after Kursliste and minimal calculations have been performed.
    """
    def __init__(self, mode: CalculationMode, exchange_rate_provider: ExchangeRateProvider, flag_override_provider: Optional[FlagOverrideProvider] = None, manual_price_provider: Optional[ManualPriceProvider] = None, keep_existing_payments: bool = False):
        super().__init__(mode, exchange_rate_provider, flag_override_provider=flag_override_provider, keep_existing_payments=keep_existing_payments)
        self.manual_price_provider = manual_price_provider
        logger.info(
            "FillInTaxValueCalculator initialized with mode: %s and provider: %s",
            mode.value,
            type(exchange_rate_provider).__name__,
        )

    def _handle_Security(self, security: Security, path_prefix: str) -> None:
        """Override to store current security context for manual price lookup and suppress warnings for manual prices."""
        self._current_security = security

        # Check if we have a manual price AND non-zero quantity before calling parent (which may add warning)
        # Only suppress warnings for securities we'll actually apply manual prices to
        has_applicable_manual_price = False
        if self.manual_price_provider and security.isin and security.taxValue and security.taxValue.referenceDate:
            # Only suppress warning if quantity is non-zero (we'll actually use the manual price)
            if security.taxValue.quantity != 0:
                date_str = security.taxValue.referenceDate.strftime('%Y-%m-%d')
                manual_price_info = self.manual_price_provider.get_price(security.isin, date_str)
                has_applicable_manual_price = manual_price_info is not None

        # Store the count of missing entries before calling parent
        missing_count_before = len(self._missing_kursliste_entries) if hasattr(self, '_missing_kursliste_entries') else 0

        # Call parent to handle Kursliste lookup
        super()._handle_Security(security, path_prefix)

        # If a new missing entry was added but we have an applicable manual price, remove it
        if has_applicable_manual_price and hasattr(self, '_missing_kursliste_entries'):
            missing_count_after = len(self._missing_kursliste_entries)
            if missing_count_after > missing_count_before:
                # Remove the last added entry (which is for this security)
                removed_entry = self._missing_kursliste_entries.pop()
                logger.debug(
                    "Suppressing missing Kursliste warning for %s (manual price available)",
                    removed_entry
                )

        # Don't reset _current_security here - it will be used by child elements like SecurityTaxValue

    def _handle_SecurityTaxValue(self, sec_tax_value: SecurityTaxValue, path_prefix: str) -> None:
        """Override to apply manual prices when Kursliste prices aren't available."""
        # First, let the parent (KurslisteTaxValueCalculator) handle it
        super()._handle_SecurityTaxValue(sec_tax_value, path_prefix)

        # If Kursliste already set the price (kursliste=True), we're done
        if sec_tax_value.kursliste is True:
            return

        # If no manual price provider, we're done
        if not self.manual_price_provider:
            return

        #  Check if we have a manual price for this security
        if not hasattr(self, '_current_security') or not self._current_security or not self._current_security.isin:
            return

        if not sec_tax_value.referenceDate:
            return

        # Skip applying manual prices if the end-of-year quantity is zero
        # (security was sold before year-end, so price is irrelevant)
        if sec_tax_value.quantity == 0:
            return

        # Try to get manual price
        date_str = sec_tax_value.referenceDate.strftime('%Y-%m-%d')
        manual_price_info = self.manual_price_provider.get_price(
            self._current_security.isin,
            date_str
        )

        if manual_price_info:
            price, currency = manual_price_info
            logger.info(
                "Applying manual price for %s on %s: %s %s",
                self._current_security.isin,
                date_str,
                price,
                currency
            )

            # Convert price to CHF if needed
            if currency == "CHF":
                chf_price = price
                rate = Decimal("1")
            else:
                chf_price, rate = self._convert_to_chf(
                    price,
                    currency,
                    f"{path_prefix}.exchangeRate",
                    sec_tax_value.referenceDate
                )

            if chf_price is not None:
                self._set_field_value(sec_tax_value, "unitPrice", chf_price, path_prefix)
                value = chf_price * sec_tax_value.quantity
                self._set_field_value(sec_tax_value, "value", value, path_prefix)
                self._set_field_value(sec_tax_value, "exchangeRate", rate, path_prefix)
                self._set_field_value(sec_tax_value, "balanceCurrency", "CHF", path_prefix)
                # Mark as manual price (not from Kursliste)
                self._set_field_value(sec_tax_value, "kursliste", False, path_prefix)
                # Add note indicating this is a manual price
                self._set_field_value(sec_tax_value, "name", "Manual price (not from official Kursliste)", path_prefix)

    def computePayments(self, security: Security, path_prefix: str) -> None:
        if self.kursliste_manager:
            super().computePayments(security, path_prefix)
        else:
            # Fallback to Minimal behavior (no op)
            # Use the grandparent implementation directly or a similar logic
            self.setKurslistePayments(security, [], path_prefix)

    def _handle_SecurityPayment(self, sec_payment: SecurityPayment, path_prefix: str) -> None:
        """Handles SecurityPayment objects for currency conversion and revenue categorization."""
        super()._handle_SecurityPayment(sec_payment, path_prefix)

        # if we have a security assume the kurstliste computation has been done
        if self._current_kursliste_security or sec_payment.kursliste:
            return

        if sec_payment.amountCurrency and sec_payment.paymentDate:
            payment_date = sec_payment.paymentDate
            amount = sec_payment.amount
            
            chf_revenue, rate = self._convert_to_chf(
                amount,
                sec_payment.amountCurrency,
                f"{path_prefix}.exchangeRate",
                payment_date
            )
            self._set_field_value(sec_payment, "exchangeRate", rate, path_prefix)

            if chf_revenue is not None and chf_revenue != Decimal(0): # Only process if there's actual revenue
                if self._current_security_is_type_A is True:
                    self._set_field_value(sec_payment, "grossRevenueA", chf_revenue, path_prefix)
                    self._set_field_value(sec_payment, "grossRevenueB", Decimal(0), path_prefix)
                elif self._current_security_is_type_A is False:
                    self._set_field_value(sec_payment, "grossRevenueB", chf_revenue, path_prefix)
                    self._set_field_value(sec_payment, "grossRevenueA", Decimal(0), path_prefix)
                elif self._current_security_is_type_A is None:
                    raise ValueError(f"SecurityPayment at {path_prefix} has revenue, but parent Security has no country specified to determine Type A/B revenue.")
        else:
            raise ValueError(f"SecurityPayment at {path_prefix} is missing amountCurrency or paymentDate.")
