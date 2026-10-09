from collections import defaultdict
from datetime import date
from decimal import Decimal

from typing import List, Optional
import logging

from opensteuerauszug.model.critical_warning import CriticalWarning, CriticalWarningCategory
from opensteuerauszug.model.ech0196 import Security, SecurityPayment, SecurityTaxValue
from opensteuerauszug.model.kursliste import SecurityGroupESTV
from .kursliste_tax_value_calculator import (
    KurslisteTaxValueCalculator,
    UnsupportedKurslistePayment,
)
from .base import CalculationMode
from opensteuerauszug.core.exchange_rate_provider import ExchangeRateProvider


from opensteuerauszug.core.flag_override_provider import FlagOverrideProvider
from opensteuerauszug.render.translations import Language, DEFAULT_LANGUAGE

logger = logging.getLogger(__name__)

# eCH security categories mapped onto the Kursliste security groups used to
# look up the DA-1 treaty rates for a country.
_ECH_CATEGORY_TO_ESTV_GROUP = {
    "BOND": SecurityGroupESTV.BOND,
    "FUND": SecurityGroupESTV.FUND,
    "OPTION": SecurityGroupESTV.OPTION,
    "SHARE": SecurityGroupESTV.SHARE,
}


class FillInTaxValueCalculator(KurslisteTaxValueCalculator):
    """
    Calculator that fills in missing values based on other available data,
    potentially after Kursliste and minimal calculations have been performed.
    """

    def __init__(
        self,
        mode: CalculationMode,
        exchange_rate_provider: ExchangeRateProvider,
        flag_override_provider: Optional[FlagOverrideProvider] = None,
        keep_existing_payments: bool = False,
        render_language: Language = DEFAULT_LANGUAGE,
    ):
        super().__init__(
            mode,
            exchange_rate_provider,
            flag_override_provider=flag_override_provider,
            keep_existing_payments=keep_existing_payments,
            render_language=render_language,
        )
        logger.info(
            "FillInTaxValueCalculator initialized with mode: %s and provider: %s",
            mode.value,
            type(exchange_rate_provider).__name__,
        )
        # Positions whose Steuerwert came from the broker rather than the Kursliste.
        self._broker_valued_positions: List[str] = []
        # Positions with neither a Kursliste entry nor a broker valuation.
        self._unvaluable_positions: List[str] = []
        # (identifier, date, amount, currency) for payments the taxpayer made.
        self._negative_payments: List[tuple] = []
        # (identifier, reason) for securities whose Kursliste income was unusable.
        self._kursliste_fallbacks: List[tuple] = []
        self._current_security_identifier: Optional[str] = None
        # True when the income of the security being processed comes from the
        # broker even though the security itself is in the Kursliste.
        self._current_security_uses_broker_income = False

    def calculate(self, tax_statement):
        self._broker_valued_positions = []
        self._unvaluable_positions = []
        self._negative_payments = []
        self._kursliste_fallbacks = []
        result = super().calculate(tax_statement)
        self._warn_about_broker_valuations(result)
        self._warn_about_negative_payments(result)
        self._warn_about_kursliste_fallbacks(result)
        return result

    def _warn_about_kursliste_fallbacks(self, tax_statement) -> None:
        """Report securities whose Kursliste income could not be used."""
        for identifier, reason in self._kursliste_fallbacks:
            tax_statement.critical_warnings.append(
                CriticalWarning(
                    category=CriticalWarningCategory.BROKER_VALUATION,
                    message=(
                        f"{reason} The income reported here for {identifier} is the "
                        "broker's, not the Kursliste's. Verify it by hand."
                    ),
                    source="FillInTaxValueCalculator",
                    identifier=identifier,
                )
            )

    def _warn_about_negative_payments(self, tax_statement) -> None:
        """Report payments made on a position rather than received from it.

        The manufactured dividend a short seller owes is the usual source. It is
        booked at zero income here, so the reader has to be told it exists: it
        may be deductible as a cost of the investment, but that is not a call
        this tool can make.
        """
        if not self._negative_payments:
            return
        listed = "; ".join(
            f"{identifier} {payment_date}: {amount:.2f} {currency}"
            for identifier, payment_date, amount, currency in self._negative_payments[:10]
        )
        if len(self._negative_payments) > 10:
            listed += f"; and {len(self._negative_payments) - 10} more"
        tax_statement.critical_warnings.append(
            CriticalWarning(
                category=CriticalWarningCategory.OTHER,
                message=(
                    f"{len(self._negative_payments)} payment(s) were made rather than "
                    f"received — typically the dividend owed on a short position: "
                    f"{listed}. They are reported as zero income because a private tax "
                    "return has no negative revenue, and they do not reduce the "
                    "dividends received elsewhere. Check with your tax authority "
                    "whether they are deductible as a cost."
                ),
                source="FillInTaxValueCalculator",
            )
        )

    def _warn_about_broker_valuations(self, tax_statement) -> None:
        """Say on the statement which Steuerwerte did not come from the Kursliste.

        The cover text tells the reader that every tax value is based on the
        Kursliste. In fill-in mode that is no longer true for positions the
        Kursliste does not list — typically exchange-traded options, which carry
        no ISIN — so the exception has to be visible in the document itself.
        """
        if self._broker_valued_positions:
            listed = ", ".join(self._broker_valued_positions[:10])
            if len(self._broker_valued_positions) > 10:
                listed += f", and {len(self._broker_valued_positions) - 10} more"
            tax_statement.critical_warnings.append(
                CriticalWarning(
                    category=CriticalWarningCategory.BROKER_VALUATION,
                    message=(
                        f"{len(self._broker_valued_positions)} position(s) are not in "
                        f"the Kursliste and are valued at the broker's year-end mark "
                        f"instead: {listed}. Contrary to the note on the first page, "
                        "these Steuerwerte do not come from the Kursliste. Check them "
                        "against your broker statement."
                    ),
                    source="FillInTaxValueCalculator",
                )
            )
        if self._unvaluable_positions:
            listed = ", ".join(self._unvaluable_positions[:10])
            if len(self._unvaluable_positions) > 10:
                listed += f", and {len(self._unvaluable_positions) - 10} more"
            tax_statement.critical_warnings.append(
                CriticalWarning(
                    category=CriticalWarningCategory.BROKER_VALUATION,
                    message=(
                        f"{len(self._unvaluable_positions)} position(s) have no "
                        f"Kursliste entry and no broker valuation either, so they are "
                        f"reported without a Steuerwert: {listed}. Add `positionValue` "
                        "to your broker export, or enter these positions by hand."
                    ),
                    source="FillInTaxValueCalculator",
                )
            )

    def _handle_Security(self, security: Security, path_prefix: str) -> None:
        self._current_security_identifier = self._security_identifier(security)
        self._current_security_uses_broker_income = False
        super()._handle_Security(security, path_prefix)

    def _handle_SecurityTaxValue(self, sec_tax_value: SecurityTaxValue, path_prefix: str) -> None:
        super()._handle_SecurityTaxValue(sec_tax_value, path_prefix)

        # The parent marks a Steuerwert it cannot source from the Kursliste as
        # undefined and drops the value. Filling that gap from the broker's own
        # year-end mark is the entire point of this mode; it is what makes
        # exchange-traded options (never listed in the Kursliste, and routinely
        # held short) appear with a value at all.
        if self.mode == CalculationMode.VERIFY or not sec_tax_value.undefined:
            return
        if sec_tax_value.quantity == 0:
            return

        identifier = self._current_security_identifier or path_prefix
        if sec_tax_value.balance is None or not sec_tax_value.balanceCurrency:
            self._unvaluable_positions.append(identifier)
            logger.warning(
                "No Kursliste entry and no broker balance for %s; reporting it "
                "without a Steuerwert. Include `positionValue` in the broker export "
                "to have it valued.",
                identifier,
            )
            return

        chf_value, rate = self._convert_to_chf(
            sec_tax_value.balance,
            sec_tax_value.balanceCurrency,
            f"{path_prefix}.exchangeRate",
            sec_tax_value.referenceDate,
        )
        self._set_field_value(sec_tax_value, "exchangeRate", rate, path_prefix)
        self._set_field_value(sec_tax_value, "value", chf_value, path_prefix)
        # A value and the undefined flag must never travel together.
        self._set_field_value(sec_tax_value, "undefined", None, path_prefix)
        self._broker_valued_positions.append(identifier)
        logger.info(
            "Valued %s from the broker mark: %s %s -> %s CHF",
            identifier,
            sec_tax_value.balance,
            sec_tax_value.balanceCurrency,
            chf_value,
        )

    def _handle_unsupported_kursliste_payment(
        self, security: Security, exc: UnsupportedKurslistePayment, path_prefix: str
    ) -> None:
        # The Kursliste entry exists but describes something we cannot turn into
        # a statement row (a scrip dividend, say). The broker reported what was
        # actually received, so use that rather than dropping the income.
        logger.warning("%s Falling back to the broker's own figures.", exc)
        self._kursliste_fallbacks.append((self._current_security_identifier, str(exc)))
        # The rows kept below are the broker's and still need converting.
        self._current_security_uses_broker_income = True
        self.setKurslistePayments(
            security, self._fold_broker_withholding(security.payment), path_prefix
        )

    def computePayments(self, security: Security, path_prefix: str) -> None:
        if self._current_kursliste_security is not None:
            super().computePayments(security, path_prefix)
            return

        # No Kursliste entry for this security. The parent implementations
        # replace the payment list with the (empty) Kursliste-derived one,
        # which drops the broker's dividend and interest evidence and silently
        # under-reports income. Filling in from the data we do have is exactly
        # what this calculator is for, so keep the broker rows instead.
        self.setKurslistePayments(
            security, self._fold_broker_withholding(security.payment), path_prefix
        )

    @staticmethod
    def _fold_broker_withholding(payments: List[SecurityPayment]) -> List[SecurityPayment]:
        """Attach broker withholding-tax rows to the revenue they were taken from.

        Brokers report a dividend and the tax withheld on it as two separate
        cash movements; the tax row carries a negative ``amount``. eCH-0196
        expects a single payment with the *gross* revenue plus the tax in the
        DA-1 attributes, so a stand-alone tax row would be booked as negative
        income. Rows that have no revenue to attach to (e.g. a post-year-end
        correction on its own date) keep the tax but lose their amount.
        """
        by_date: dict[date, List[SecurityPayment]] = defaultdict(list)
        for payment in payments:
            by_date[payment.paymentDate].append(payment)

        folded: List[SecurityPayment] = []
        for payment_date in sorted(by_date):
            rows = by_date[payment_date]
            tax_rows = [p for p in rows if p.nonRecoverableTaxAmountOriginal is not None]
            revenue_rows = [p for p in rows if p.nonRecoverableTaxAmountOriginal is None]
            if not tax_rows:
                folded.extend(rows)
                continue

            withheld = sum(
                (p.nonRecoverableTaxAmountOriginal or Decimal("0") for p in tax_rows),
                Decimal("0"),
            )
            if revenue_rows:
                target = revenue_rows[0]
                target.nonRecoverableTaxAmountOriginal = (
                    target.nonRecoverableTaxAmountOriginal or Decimal("0")
                ) + withheld
                folded.extend(revenue_rows)
            else:
                orphan = tax_rows[0]
                orphan.nonRecoverableTaxAmountOriginal = withheld
                # Dropping the (negative) amount keeps the tax from being
                # converted into negative gross revenue further down.
                orphan.amount = None
                folded.append(orphan)
        return folded

    def _apply_broker_withholding(
        self,
        sec_payment: SecurityPayment,
        gross_revenue_chf: Decimal,
        exchange_rate: Decimal,
        path_prefix: str,
    ) -> None:
        """Turn the broker's withholding evidence into a DA-1 claim.

        The claim is capped at the non-recoverable rate the Kursliste records
        for the security's country: tax withheld above the treaty rate has to
        be reclaimed from the source state, not credited in Switzerland. When
        no rate is on file the DA-1 attributes stay empty — under-claiming is
        recoverable by the taxpayer, over-claiming is not.
        """
        withheld_original = sec_payment.nonRecoverableTaxAmountOriginal
        if withheld_original is None or withheld_original <= Decimal("0"):
            return
        if gross_revenue_chf <= Decimal("0"):
            return

        country = self._current_security_country
        da1_rate = None
        if country and country != "CH" and self.kursliste_manager:
            accessor = self.kursliste_manager.get_kurslisten_for_year(sec_payment.paymentDate.year)
            if accessor:
                da1_rate = accessor.get_da1_rate(
                    country,
                    _ECH_CATEGORY_TO_ESTV_GROUP.get(
                        self._current_security_category or "", SecurityGroupESTV.SHARE
                    ),
                    reference_date=sec_payment.paymentDate,
                )

        if da1_rate is None or not da1_rate.nonRecoverable:
            logger.warning(
                "No Kursliste DA-1 rate for country %s; the %s withholding tax on the "
                "payment of %s is reported but not claimed. Add it to the DA-1 form manually.",
                country,
                sec_payment.amountCurrency,
                sec_payment.paymentDate,
            )
            return

        withheld_chf = withheld_original * exchange_rate
        non_recoverable_cap = gross_revenue_chf * da1_rate.nonRecoverable / Decimal(100)
        lump_sum_cap = gross_revenue_chf * da1_rate.value / Decimal(100)

        non_recoverable = min(withheld_chf, non_recoverable_cap)
        lump_sum = min(withheld_chf, lump_sum_cap)

        self._set_field_value(sec_payment, "nonRecoverableTaxAmount", non_recoverable, path_prefix)
        self._set_field_value(
            sec_payment,
            "nonRecoverableTaxPercent",
            (non_recoverable / gross_revenue_chf * Decimal(100)).quantize(Decimal("0.0001")),
            path_prefix,
        )
        self._set_field_value(sec_payment, "lumpSumTaxCreditAmount", lump_sum, path_prefix)
        self._set_field_value(
            sec_payment,
            "lumpSumTaxCreditPercent",
            (lump_sum / gross_revenue_chf * Decimal(100)).quantize(Decimal("0.0001")),
            path_prefix,
        )
        self._set_field_value(sec_payment, "lumpSumTaxCredit", True, path_prefix)
        if country == "US":
            # IBKR and other foreign brokers do not apply the additional Swiss
            # retention on US income, so there is nothing to reclaim for it.
            self._set_field_value(
                sec_payment, "additionalWithHoldingTaxUSA", Decimal("0"), path_prefix
            )

    def _handle_SecurityPayment(self, sec_payment: SecurityPayment, path_prefix: str) -> None:
        """Handles SecurityPayment objects for currency conversion and revenue categorization."""
        super()._handle_SecurityPayment(sec_payment, path_prefix)

        # Payments the Kursliste produced are already complete. Anything else
        # still needs converting — including broker rows kept for a security
        # that is in the Kursliste but whose Kursliste income was unusable.
        if sec_payment.kursliste:
            return
        if self._current_kursliste_security and not self._current_security_uses_broker_income:
            return

        if sec_payment.amountCurrency and sec_payment.paymentDate:
            payment_date = sec_payment.paymentDate
            amount = sec_payment.amount

            chf_revenue, rate = self._convert_to_chf(
                amount, sec_payment.amountCurrency, f"{path_prefix}.exchangeRate", payment_date
            )
            self._set_field_value(sec_payment, "exchangeRate", rate, path_prefix)

            if chf_revenue is not None and chf_revenue < Decimal(0):
                # A payment the taxpayer *made* — the manufactured dividend owed
                # on a short position, or a rebate clawback. There is no such
                # thing as negative income in a private tax return: it cannot
                # offset the dividends received on the long side, so it is
                # reported at zero and listed separately for the reader.
                self._negative_payments.append(
                    (
                        self._current_security_identifier or path_prefix,
                        sec_payment.paymentDate,
                        sec_payment.amount or Decimal("0"),
                        sec_payment.amountCurrency,
                    )
                )
                logger.warning(
                    "Payment of %s %s on %s for %s is negative (a payment made, not "
                    "received) and is reported as zero income.",
                    sec_payment.amount,
                    sec_payment.amountCurrency,
                    sec_payment.paymentDate,
                    self._current_security_identifier or path_prefix,
                )
                self._set_field_value(sec_payment, "grossRevenueA", Decimal(0), path_prefix)
                self._set_field_value(sec_payment, "grossRevenueB", Decimal(0), path_prefix)
            elif chf_revenue is not None and chf_revenue != Decimal(
                0
            ):  # Only process if there's actual revenue
                if self._current_security_is_type_A is True:
                    self._set_field_value(sec_payment, "grossRevenueA", chf_revenue, path_prefix)
                    self._set_field_value(sec_payment, "grossRevenueB", Decimal(0), path_prefix)
                elif self._current_security_is_type_A is False:
                    self._set_field_value(sec_payment, "grossRevenueB", chf_revenue, path_prefix)
                    self._set_field_value(sec_payment, "grossRevenueA", Decimal(0), path_prefix)
                elif self._current_security_is_type_A is None:
                    raise ValueError(
                        f"SecurityPayment at {path_prefix} has revenue, but parent Security has no country specified to determine Type A/B revenue."
                    )

            self._apply_broker_withholding(
                sec_payment, chf_revenue or Decimal("0"), rate, path_prefix
            )
        else:
            raise ValueError(
                f"SecurityPayment at {path_prefix} is missing amountCurrency or paymentDate."
            )
