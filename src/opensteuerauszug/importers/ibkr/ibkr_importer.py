import os
import logging
from typing import Final, List, Any, Dict, Optional, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict

logger = logging.getLogger(__name__)

from opensteuerauszug.model.position import SecurityPosition
from opensteuerauszug.model.ech0196 import (
    BankAccountNumber,
    BankAccountPayment,
    Expense,
    ListOfExpenses,
    Institution,
    ISINType,
    SecurityCategory,
    SecurityPayment,
    SecurityStock,
    TaxStatement,
    Client,
)
from opensteuerauszug.config.models import IbkrAccountSettings
from opensteuerauszug.core.security import country_from_isin
from opensteuerauszug.model.critical_warning import CriticalWarning, CriticalWarningCategory
from opensteuerauszug.importers.common import (
    CashAccountEntry,
    CashPositionData,
    PositionHints,
    SecurityNameRegistry,
    SecurityPositionData,
    aggregate_mutations,
    apply_withholding_tax_fields,
    augment_list_of_bank_accounts,
    augment_list_of_securities,
    build_client,
    build_security_payment,
    fold_cash_payments,
    parse_swiss_canton,
    resolve_first_last_name,
    to_decimal,
)
from opensteuerauszug.render.translations import get_text, Language, DEFAULT_LANGUAGE

# Country of the IBKR legal entity that actually holds the account, keyed by
# the `ibEntity` attribute of AccountInformation. Swiss clients are booked to
# a handful of these; the cash accounts belong to that entity, not to the US.
IBKR_ENTITY_TO_COUNTRY: Final[Dict[str, str]] = {
    "IBLLC": "US",
    "IBLLC-US": "US",
    "IB-US": "US",
    "IB-UK": "GB",
    "IBUK": "GB",
    "IBIE": "IE",
    "IB-IE": "IE",
    "IBCE": "HU",
    "IB-CE": "HU",
    "IB-LUX": "LU",
    "IB-CAN": "CA",
    "IBCAN": "CA",
    "IB-AU": "AU",
    "IB-HK": "HK",
    "IB-IN": "IN",
    "IB-JP": "JP",
    "IB-SG": "SG",
}

# eCH-0196 expense types for the cash movements IBKR reports as costs. The
# type is descriptive only — whether an expense is deductible is decided by the
# assessing authority, so `expensesDeductible` is deliberately left unset.
EXPENSE_TYPE_NEGATIVE_INTEREST: Final[str] = "29"  # Negativzinsen (Privatvermögen)
EXPENSE_TYPE_MANAGEMENT: Final[str] = "15"  # Vermögensverwaltungskosten
EXPENSE_TYPE_OTHER: Final[str] = "37"  # Diverse Gebühren

# Used when the Flex data does not name the IBKR entity holding the account.
DEFAULT_BANK_ACCOUNT_COUNTRY: Final[str] = "US"

# Used when neither the Flex data nor the ISIN reveals an issuer country.
# Most IBKR holdings of Swiss retail clients are US-listed, so this keeps the
# historic behaviour, but every fallback is reported so the user can check.
DEFAULT_SECURITY_COUNTRY: Final[str] = "US"

IBKR_ASSET_CATEGORY_TO_ECH_SECURITY_CATEGORY: Final[Dict[str, SecurityCategory]] = {
    "STK": "SHARE",
    "BOND": "BOND",
    "OPT": "OPTION",
    "FOP": "OPTION",
    "FUT": "OTHER",
    "ETF": "FUND",
    "FUND": "FUND",
}
# Import ibflex components to avoid RuntimeWarning about module loading order
import ibflex
from ibflex.parser import FlexParserError
from ibflex.enums import TradeType


def is_summary_level(entry: object) -> bool:
    """Return True when an entry is marked with levelOfDetail SUMMARY."""
    level_of_detail = getattr(entry, "levelOfDetail", None)
    if level_of_detail is None:
        return False
    level_value = (
        level_of_detail.value if hasattr(level_of_detail, "value") else str(level_of_detail)
    )
    return str(level_value).upper() == "SUMMARY"


def should_skip_pseudo_account_entry(entry: object) -> bool:
    """Skip pseudo rows where accountId='-' or mapped-to-None SUMMARY rows."""
    # ibflex maps accountId="-" to None on some entry types, so
    # we only treat missing accountId rows as pseudo entries when they
    # are marked as SUMMARY.
    entry_account_id = getattr(entry, "accountId", None)
    return entry_account_id == "-" or (entry_account_id is None and is_summary_level(entry))


class IbkrImporter:
    """
    Imports Interactive Brokers account data for a given tax period
    from Flex Query XML files.
    """

    def _get_required_field(
        self, data_object: object, field_name: str, object_description: str
    ) -> Any:
        """Helper to get a required field or raise ValueError if missing."""
        value = getattr(data_object, field_name, None)
        if value is None:
            error_desc = object_description  # Use the passed in description
            if hasattr(data_object, 'symbol'):
                error_desc = (
                    f"{object_description} (Symbol: " f"{getattr(data_object, 'symbol', 'N/A')})"
                )
            elif (
                hasattr(data_object, 'accountId') and 'Account:' not in object_description
            ):  # Avoid double "Account:"
                error_desc = (
                    f"{object_description} (Account: "
                    f"{getattr(data_object, 'accountId', 'N/A')})"
                )
            raise ValueError(f"Missing required field '{field_name}' in {error_desc}.")
        if isinstance(value, str) and not value.strip():
            error_desc = object_description  # Use the passed in description
            if hasattr(data_object, 'symbol'):
                error_desc = (
                    f"{object_description} (Symbol: " f"{getattr(data_object, 'symbol', 'N/A')})"
                )
            elif hasattr(data_object, 'accountId') and 'Account:' not in object_description:
                error_desc = (
                    f"{object_description} (Account: "
                    f"{getattr(data_object, 'accountId', 'N/A')})"
                )
            raise ValueError(f"Empty required field '{field_name}' in {error_desc}.")
        return value

    @staticmethod
    def _build_multiplier_map(statement: Any) -> Dict[str, Decimal]:
        """Map conid -> contract multiplier from the SecuritiesInfo section.

        Flex queries routinely omit ``multiplier`` on the Trade and OpenPosition
        rows while still carrying it in SecuritiesInfo for every instrument.
        Without it an option price is out by the contract size — a factor of 100
        for US equity options — so fall back to this map rather than refusing
        the export.
        """
        multipliers: Dict[str, Decimal] = {}
        for info in getattr(statement, "SecuritiesInfo", None) or ():
            conid = getattr(info, "conid", None)
            multiplier = getattr(info, "multiplier", None)
            if conid is None or multiplier is None:
                continue
            try:
                multipliers[str(conid)] = Decimal(str(multiplier))
            except Exception:
                continue
        return multipliers

    @staticmethod
    def _build_option_event_map(statement: Any) -> Dict[tuple, Any]:
        """Map (conid, date) -> OptionAction from the OptionEAE section.

        Expiry, assignment and exercise all reach the Trades section as a
        zero-price book trade; only OptionEAE says which one it was. Keyed on
        the option leg, so the stock leg of an assignment does not shadow it.
        """
        events: Dict[tuple, Any] = {}
        for entry in getattr(statement, "OptionEAE", None) or ():
            if getattr(entry, "assetCategory", None) not in ["OPT", "FOP"]:
                continue
            conid = getattr(entry, "conid", None)
            event_date = getattr(entry, "date", None)
            action = getattr(entry, "transactionType", None)
            if conid is None or event_date is None or action is None:
                continue
            events[(str(conid), event_date)] = action
        return events

    @staticmethod
    def _cash_transaction_identity(cash_tx: Any) -> tuple:
        """Everything that identifies a cash movement except its time of day.

        A Flex query that emits both the summary and the detail row for the
        same movement produces two rows that agree on all of this; only the
        detail row carries a time in ``dateTime``.
        """
        moment = getattr(cash_tx, "dateTime", None)
        day = moment.date() if hasattr(moment, "date") else moment
        return (
            str(getattr(cash_tx, "type", None)),
            getattr(cash_tx, "currency", None),
            str(getattr(cash_tx, "conid", None)),
            getattr(cash_tx, "description", None),
            getattr(cash_tx, "amount", None),
            day,
        )

    def _select_cash_transaction_level(
        self, cash_transactions: Sequence[Any], account_id: str
    ) -> List[Any]:
        """Return one row per cash movement, or refuse if that cannot be decided.

        A Flex query can emit cash transactions at more than one level of
        detail. Every level repeats the same amounts, so importing all of them
        doubles dividends, interest and fees — silently, and in the direction
        that over-declares income and over-claims withholding tax.

        When ``levelOfDetail`` is exported the levels can be told apart and the
        summary rows are the ones to keep. When it is not, they cannot, so this
        refuses rather than guessing which copy is real.
        """
        # IBKR marks the aggregate rows of a multi-level export with
        # accountId="-". Those are dropped further down anyway, and counting
        # them here would make a perfectly good export look duplicated.
        candidates = [tx for tx in cash_transactions if not should_skip_pseudo_account_entry(tx)]
        if len(candidates) < len(cash_transactions):
            logger.info(
                "Account %s: ignoring %d aggregate cash row(s) marked with a pseudo " "account id.",
                account_id,
                len(cash_transactions) - len(candidates),
            )

        levels = {
            str(getattr(tx, "levelOfDetail", None)).upper()
            for tx in candidates
            if getattr(tx, "levelOfDetail", None) is not None
        }
        if levels and len(levels) > 1:
            kept = [tx for tx in candidates if is_summary_level(tx)]
            logger.warning(
                "Account %s: cash transactions came at %d levels of detail (%s); "
                "keeping the %d summary row(s) of %d and dropping the rest to avoid "
                "counting every amount more than once.",
                account_id,
                len(levels),
                ", ".join(sorted(levels)),
                len(kept),
                len(candidates),
            )
            return kept

        seen: Dict[tuple, Any] = {}
        repeated = 0
        signature = False
        for tx in candidates:
            identity = self._cash_transaction_identity(tx)
            previous = seen.get(identity)
            if previous is None:
                seen[identity] = tx
                continue
            repeated += 1
            # The summary row has no time of day, the detail row does.
            times = {
                getattr(getattr(t, "dateTime", None), "time", lambda: None)()
                for t in (previous, tx)
            }
            if len(times) > 1:
                signature = True

        if signature:
            raise ValueError(
                f"Account {account_id}: the Flex query exports cash transactions at "
                f"more than one level of detail — {repeated} of "
                f"{len(candidates)} rows repeat a movement that is already "
                "present — and does not include the 'levelOfDetail' field, so the "
                "copies cannot be told apart. Importing them would double every "
                "dividend, interest payment and fee. Re-run the Flex Query with a "
                "single level of detail selected for Cash Transactions (or add the "
                "'Level of Detail' field) and export again."
            )
        return candidates

    def _price_apply_multiplier(
        self,
        data_object: Any,
        price: Decimal,
        object_description: str,
        multipliers: Optional[Dict[str, Decimal]] = None,
    ) -> Decimal:
        """Scale a per-share option price up to the price of one contract."""
        if not price:
            return price
        if getattr(data_object, "assetCategory", None) not in ["OPT", "FOP"]:
            return price

        raw_multiplier = getattr(data_object, "multiplier", None)
        if raw_multiplier is not None:
            return price * self._to_decimal(raw_multiplier, "multiplier", object_description)

        conid = getattr(data_object, "conid", None)
        from_info = (multipliers or {}).get(str(conid)) if conid is not None else None
        if from_info is not None:
            return price * from_info

        raise ValueError(
            f"Missing required field 'multiplier' in {object_description} and the "
            "SecuritiesInfo section does not provide one for this contract either. "
            "Re-run the Flex Query with the 'Multiplier' field, or include the "
            "'Securities Info' section."
        )

    def _to_decimal(
        self, value: object | None, field_name: str, object_description: str
    ) -> Decimal:
        """Converts a value to Decimal, raising ValueError on failure."""
        return to_decimal(value, field_name, object_description)

    def _normalize_country_code(self, value: object | None) -> str | None:
        if value is None:
            return None
        country = str(value).strip().upper()
        if not country:
            return None
        return country[:2]

    def _maybe_update_security_country(
        self,
        security_country_map: Dict[SecurityPosition, str],
        sec_pos: SecurityPosition,
        country_code: str | None,
        source_label: str,
    ) -> None:
        if not country_code:
            return
        existing = security_country_map.get(sec_pos)
        if existing and existing != country_code:
            logger.warning(
                "Conflicting issuer country code for %s from %s: %s (existing: %s)",
                sec_pos.get_processing_identifier(),
                source_label,
                country_code,
                existing,
            )
            return
        if not existing:
            security_country_map[sec_pos] = country_code

    def __init__(
        self,
        period_from: date,
        period_to: date,
        account_settings_list: List[IbkrAccountSettings],
        render_language: Language = DEFAULT_LANGUAGE,
    ):
        """
        Initialize the importer with a tax period.

        Args:
            period_from (date): The start date of the tax period.
            period_to (date): The end date of the tax period.
            account_settings_list: List of IBKR account settings.
            render_language (Language): Language for translations.
        """
        self.period_from = period_from
        self.period_to = period_to
        self.account_settings_list = account_settings_list
        self.render_language = render_language

        if not self.account_settings_list:
            # Currently no account info is used so we keep stumm.
            logger.debug("IbkrImporter initialized with an empty list of " "account settings.")
        # else:
        # print(
        #     f"IbkrImporter initialized. Primary account (if used): "
        #     f"{self.account_settings_list[0].account_id}"
        # )

    def _aggregate_stocks(self, stocks: List[SecurityStock]) -> List[SecurityStock]:
        """Aggregate buy and sell entries on the same date with equal order id if present without reordering."""
        return aggregate_mutations(stocks)

    def _parse_flex_statements(
        self,
        filenames: Sequence[str],
        *,
        file_label: str,
        log_label: str,
        error_label: str,
    ) -> list[ibflex.FlexStatement]:
        statements: list[ibflex.FlexStatement] = []

        for filename in filenames:
            if not os.path.exists(filename):
                raise FileNotFoundError(f"{file_label} not found: {filename}")
            if not filename.lower().endswith(".xml"):
                logger.warning("Skipping non-XML %s: %s", log_label, filename)
                continue

            try:
                logger.info("Parsing %s: %s", log_label, filename)
                response = ibflex.parser.parse(filename)
                if response and response.FlexStatements:
                    for stmt in response.FlexStatements:
                        if should_skip_pseudo_account_entry(stmt):
                            logger.info(
                                "Skipping FlexStatement with pseudo accountId in %s",
                                filename,
                            )
                            continue
                        logger.info(
                            "Successfully parsed statement for account: %s, Period: %s to %s",
                            stmt.accountId,
                            stmt.fromDate,
                            stmt.toDate,
                        )
                        statements.append(stmt)
                else:
                    logger.warning(
                        "No FlexStatements found in %s or response was empty.",
                        filename,
                    )
            except FlexParserError as e:
                raise ValueError(
                    f"Failed to parse {error_label} {filename} with ibflex: {e}"
                    + self._flex_parse_hint(e)
                )
            except Exception as e:
                raise RuntimeError(f"An unexpected error occurred while parsing {filename}: {e}")

        return statements

    @staticmethod
    def _flex_parse_hint(error: Exception) -> str:
        """Turn a parser complaint into something the reader can act on.

        The Flex Query offers cash transaction types that the parser has no
        mapping for. Selecting one makes the *whole* export unreadable, and the
        bare message does not say which box to untick.
        """
        message = str(error)
        if "is not a valid CashAction" not in message:
            return ""
        supported = ", ".join(sorted(action.value for action in ibflex.CashAction))
        return (
            " — this cash transaction type cannot be imported and makes the whole "
            "export unreadable. Untick it in the Cash Transactions section of the "
            f"Flex Query. The types that can be imported are: {supported}."
        )

    def _find_processed_security_position(
        self,
        processed_security_positions: Dict[SecurityPosition, SecurityPositionData],
        account_id: str,
        security_id: object,
    ) -> SecurityPosition | None:
        for position in processed_security_positions:
            if position.depot == account_id and position.symbol == str(security_id):
                return position
        return None

    def _build_cash_transaction_security_position(
        self,
        account_id: str,
        cash_tx: ibflex.CashTransaction,
        description: str,
    ) -> SecurityPosition:
        security_id = self._get_required_field(cash_tx, 'conid', 'CashTransaction')
        isin_attr = cash_tx.isin
        symbol_attr = cash_tx.symbol
        return SecurityPosition(
            depot=account_id,
            valor=None,
            isin=ISINType(isin_attr) if isin_attr else None,
            symbol=str(security_id),
            description=(f"{description} ({symbol_attr})" if symbol_attr else description),
        )

    def _apply_withholding_tax_fields(
        self,
        payment: SecurityPayment,
        amount: Decimal,
        currency: str,
        tx_type: ibflex.CashAction,
    ) -> None:
        if tx_type != ibflex.CashAction.WHTAX:
            return
        apply_withholding_tax_fields(payment, amount, currency)

    def _build_security_payment(
        self,
        *,
        payment_date: date,
        description: str,
        currency: str,
        amount: Decimal,
        tx_type: ibflex.CashAction,
    ) -> SecurityPayment:
        return build_security_payment(
            payment_date=payment_date,
            description=description,
            currency=currency,
            amount=amount,
            broker_label=tx_type.value,
            is_withholding=tx_type == ibflex.CashAction.WHTAX,
            is_securities_lending=tx_type == ibflex.CashAction.PAYMENTINLIEU,
        )

    def _import_corrections_flex_files(
        self,
        corrections_filenames: Sequence[str],
        processed_security_positions: Dict[SecurityPosition, SecurityPositionData],
    ) -> None:
        corrections_flex_statements = self._parse_flex_statements(
            corrections_filenames,
            file_label="Corrections Flex file",
            log_label="corrections Flex statement",
            error_label="corrections Flex file",
        )

        corrections_count = 0
        for stmt in corrections_flex_statements:
            account_id = self._get_required_field(
                stmt,
                'accountId',
                'FlexStatement (corrections)',
            )
            if not stmt.CashTransactions:
                continue

            for cash_tx in stmt.CashTransactions:
                if should_skip_pseudo_account_entry(cash_tx):
                    continue

                settle_date = getattr(cash_tx, 'settleDate', None)
                if settle_date is None:
                    continue
                if isinstance(settle_date, str):
                    settle_date = datetime.strptime(settle_date, "%Y%m%d").date()
                if settle_date < self.period_from or settle_date > self.period_to:
                    continue

                security_id = cash_tx.conid
                if not security_id:
                    continue

                tx_type = cash_tx.type
                if tx_type is None:
                    continue

                if tx_type != ibflex.CashAction.WHTAX:
                    continue

                description = self._get_required_field(
                    cash_tx,
                    'description',
                    'CashTransaction (corrections)',
                )
                amount = self._to_decimal(
                    self._get_required_field(
                        cash_tx,
                        'amount',
                        'CashTransaction (corrections)',
                    ),
                    'amount',
                    f"CashTransaction (corrections) {description[:30]}",
                )
                currency = self._get_required_field(
                    cash_tx,
                    'currency',
                    'CashTransaction (corrections)',
                )

                sec_pos_key = self._find_processed_security_position(
                    processed_security_positions,
                    account_id,
                    security_id,
                )
                if sec_pos_key is None:
                    logger.warning(
                        "Corrections flex: skipping withholding correction for unknown security conid=%s (%s)",
                        security_id,
                        description,
                    )
                    continue

                processed_security_positions[sec_pos_key]['payments'].append(
                    self._build_security_payment(
                        payment_date=settle_date,
                        description=description,
                        currency=currency,
                        amount=amount,
                        tx_type=tx_type,
                    )
                )
                corrections_count += 1

        if corrections_count:
            logger.info(
                "Imported %d withholding-tax correction(s) from corrections flex file(s).",
                corrections_count,
            )

    # IBKR's own per-currency totals, and the cash transaction types that have to
    # add up to each of them. Only categories whose mapping is unambiguous are
    # listed, because a check that cries wolf on a tax document is worse than no
    # check at all.
    #
    # `brokerInterest` was held back until its meaning was settled, since
    # received-only and net-of-paid would each need a different sum. It is net:
    # in a 2025 export it reports USD 20.56, which is exactly 857.85 received
    # minus 837.29 paid, and HKD 260.79 for an account with no HKD debit
    # interest. Hence both the received and the paid action below.
    CASH_REPORT_CHECKS: Final[tuple] = (
        ("dividends", "dividends", (ibflex.CashAction.DIVIDEND,)),
        ("payments in lieu of dividends", "paymentInLieu", (ibflex.CashAction.PAYMENTINLIEU,)),
        ("withholding tax", "withholdingTax", (ibflex.CashAction.WHTAX,)),
        ("other fees", "otherFees", (ibflex.CashAction.FEES,)),
        (
            "broker interest",
            "brokerInterest",
            (ibflex.CashAction.BROKERINTRCVD, ibflex.CashAction.BROKERINTPAID),
        ),
    )

    def _verify_against_cash_report(
        self,
        tax_statement: TaxStatement,
        all_flex_statements: Sequence[Any],
        booked_cash: Dict[tuple, Decimal],
        tolerance: Decimal = Decimal("0.01"),
    ) -> None:
        """Check what was taken in against the broker's own category totals.

        The Cash Report is IBKR summing the same movements independently, so it
        is the one check here that does not rely on our own reading of the
        transaction rows. A statement whose dividends are doubled or whose
        withholding is missing looks entirely plausible otherwise.

        Reported rather than raised: the divergence may equally mean the export
        is incomplete, and refusing would leave the reader with nothing.
        """
        totals: Dict[tuple, Decimal] = defaultdict(Decimal)
        available: set = set()
        for stmt in all_flex_statements:
            for row in getattr(stmt, "CashReport", None) or ():
                if should_skip_pseudo_account_entry(row):
                    continue
                currency = getattr(row, "currency", None)
                if currency is None or str(currency) == "BASE_SUMMARY":
                    continue
                for _label, attribute, _types in self.CASH_REPORT_CHECKS:
                    value = getattr(row, attribute, None)
                    if value is None:
                        continue
                    available.add(attribute)
                    totals[(str(currency), attribute)] += Decimal(str(value))

        if not available:
            # Only a log line: the check being unavailable is not itself a defect in
            # the statement, and a critical warning on every export that did not tick
            # these optional boxes would train the reader to ignore the ones that matter.
            logger.warning(
                "The Flex export's Cash Report carries no category totals, so the imported "
                "amounts could not be cross-checked against the broker's own figures. "
                "Select Dividends, Withholding Tax, Payment In Lieu and Other Fees in the "
                "Flex Query's Cash Report section to enable that check."
            )
            return

        discrepancies: List[str] = []
        for label, attribute, types in self.CASH_REPORT_CHECKS:
            if attribute not in available:
                continue
            currencies = {c for (c, a) in totals if a == attribute}
            currencies |= {c for (c, t) in booked_cash if t in types}
            for currency in sorted(currencies):
                reported = totals.get((currency, attribute), Decimal("0"))
                imported = sum(
                    (booked_cash.get((currency, t), Decimal("0")) for t in types), Decimal("0")
                )
                delta = imported - reported
                if abs(delta) > tolerance:
                    discrepancies.append(
                        f"{label} {currency}: broker reports {reported:.2f}, "
                        f"imported {imported:.2f} (off by {delta:+.2f})"
                    )

        if not discrepancies:
            logger.info(
                "Imported cash matches the broker's own Cash Report totals for %s.",
                ", ".join(sorted(available)),
            )
            return

        listed = "; ".join(discrepancies)
        logger.error("Imported cash disagrees with the broker's Cash Report: %s", listed)
        tax_statement.critical_warnings.append(
            CriticalWarning(
                category=CriticalWarningCategory.OTHER,
                message=(
                    "THE AMOUNTS IN THIS STATEMENT DO NOT MATCH THE BROKER'S OWN TOTALS: "
                    f"{listed}. Do not file this statement until the difference is "
                    "explained. It usually means the export lists transactions at more "
                    "than one level of detail, or that a transaction type is missing "
                    "from it."
                ),
                source="IbkrImporter",
            )
        )

    @staticmethod
    def _build_list_of_expenses(
        tax_statement: TaxStatement,
        expense_items: Sequence[tuple[str, Decimal, str, str]],
        account_id: str,
    ) -> None:
        """Put broker costs into the Spesenverzeichnis.

        The CHF figure and exchange rate are filled in later, once a rate
        provider is available. ``expensesDeductible`` is left unset on purpose:
        whether a cost is deductible is the assessing authority's call, not
        this tool's.
        """
        if not expense_items:
            return
        expenses = [
            Expense(
                referenceDate=payment_date,
                name=description[:200],
                amountCurrency=currency,
                amount=abs(amount),
                expenseType=expense_type,
                bankAccountNumber=BankAccountNumber(f"{account_id}-{currency}"),
            )
            for description, amount, currency, expense_type, payment_date in expense_items
        ]
        tax_statement.listOfExpenses = ListOfExpenses(expense=expenses)

    @staticmethod
    def _warn_about_omitted_cash(
        tax_statement: TaxStatement,
        omitted_cash_items: Sequence[tuple[str, Decimal, str, str]],
    ) -> None:
        """Put the cash movements we left out on the statement itself.

        Fees and negative credit interest belong in an expenses section
        (eCH-0196 ``listOfExpenses``) that we do not produce yet. Reporting the
        totals as a critical warning means they show up on the instructions
        page of the PDF, so the reader can decide whether to claim them,
        instead of the money vanishing with only a log line.
        """
        if not omitted_cash_items:
            return
        totals: Dict[str, Decimal] = {}
        for _description, amount, currency, _expense_type, _payment_date in omitted_cash_items:
            totals[currency] = totals.get(currency, Decimal("0")) + abs(amount)
        rendered = ", ".join(f"{amount:.2f} {currency}" for currency, amount in totals.items())
        tax_statement.critical_warnings.append(
            CriticalWarning(
                category=CriticalWarningCategory.OTHER,
                message=(
                    f"{len(omitted_cash_items)} cost(s) totalling {rendered} (broker fees, "
                    "ADR fees, advisor fees, negative credit interest) are listed in the "
                    "expenses register. Whether they are deductible is for the assessing "
                    "authority to decide, so no deductible amount is claimed here."
                ),
                source="IbkrImporter",
            )
        )

    @staticmethod
    def _warn_about_interest_withholding(
        tax_statement: TaxStatement,
        interest_withholding: Sequence[tuple[str, Decimal, str]],
    ) -> None:
        """Report foreign tax withheld from interest, which the format cannot carry.

        eCH-0196 gives a bank account payment no DA-1 attributes, so tax deducted
        from interest can only travel as evidence. It may still be creditable, so
        the reader has to be told it exists rather than finding a payment row that
        quietly contributes nothing.
        """
        if not interest_withholding:
            return
        totals: Dict[str, Decimal] = {}
        for _description, amount, currency in interest_withholding:
            totals[currency] = totals.get(currency, Decimal("0")) + abs(amount)
        swiss = {c: a for c, a in totals.items() if c == "CHF"}
        foreign = {c: a for c, a in totals.items() if c != "CHF"}
        parts = []
        if swiss:
            # Swiss withholding on interest is expressible (bankAccountPaymentType
            # has withHoldingTaxClaim) — this tool just does not derive it from a
            # separate tax row yet.
            parts.append(
                ", ".join(f"{a:.2f} {c}" for c, a in swiss.items())
                + " of Swiss withholding tax (Verrechnungssteuer)"
            )
        if foreign:
            parts.append(
                ", ".join(f"{a:.2f} {c}" for c, a in foreign.items())
                + " of foreign withholding tax, which eCH-0196 cannot express on a bank "
                "account payment at all"
            )
        tax_statement.critical_warnings.append(
            CriticalWarning(
                category=CriticalWarningCategory.OTHER,
                message=(
                    "Tax was withheld from interest that is not linked to a security: "
                    + "; and ".join(parts)
                    + ". It is carried as evidence only and is NOT claimed anywhere in this "
                    "statement. Claim it on the Wertschriftenverzeichnis (Verrechnungssteuer) "
                    "or the DA-1 form (foreign) yourself."
                ),
                source="IbkrImporter",
            )
        )

    def import_files(
        self, filenames: List[str], corrections_filenames: Optional[List[str]] = None
    ) -> TaxStatement:
        """
        Import data from IBKR Flex Query XMLs and return a TaxStatement.

        Args:
            filenames: List of file paths to import (XML).
            corrections_filenames: Optional list of "corrections" flex query XML
                files covering the period after the tax year (e.g. Jan–Mar of
                the following year).  Only CashTransactions whose settleDate
                falls within [period_from, period_to] are imported from these
                files, allowing withholding-tax reversals to be netted against
                original deductions.

        Returns:
            The imported tax statement.
        """
        all_flex_statements = self._parse_flex_statements(
            filenames,
            file_label="IBKR Flex statement file",
            log_label="IBKR Flex statement",
            error_label="IBKR Flex XML file",
        )

        if not all_flex_statements:
            # This might be an error or just a case of no relevant data.
            # "If data is missing do a hard error" - might need adjustment
            logger.warning(
                "No Flex statements were successfully parsed. " "Returning empty TaxStatement."
            )
            return TaxStatement(
                minorVersion=1,
                periodFrom=self.period_from,
                periodTo=self.period_to,
                taxPeriod=self.period_from.year,
                listOfSecurities=None,
                listOfBankAccounts=None,
            )

        # Key: SecurityPosition or tuple for cash. Value: dict with 'stocks', 'payments'
        processed_security_positions: defaultdict[SecurityPosition, SecurityPositionData] = (
            defaultdict(lambda: {'stocks': [], 'payments': []})
        )

        # Best-name-wins registry for security display names.
        security_name_registry = SecurityNameRegistry()

        processed_cash_positions: defaultdict[tuple, CashPositionData] = defaultdict(
            lambda: {'stocks': [], 'payments': []}
        )
        security_country_map: Dict[SecurityPosition, str] = {}
        # Cash movements we deliberately leave out of the statement, recorded so
        # the user is told what is missing instead of only seeing a log line.
        omitted_cash_items: List[tuple[str, Decimal, str, str, date]] = []
        saw_withholding_rows = False
        saw_income_rows = False
        booked_cash: defaultdict[tuple, Decimal] = defaultdict(Decimal)
        # Withholding tax on interest, which eCH-0196 cannot express on a bank
        # account payment: (description, amount, currency).
        interest_withholding: List[tuple[str, Decimal, str]] = []

        # Map to store assetCategory and subCategory for each security
        security_asset_category_map: Dict[SecurityPosition, tuple[str, Optional[str]]] = {}
        rights_issue_positions: set[SecurityPosition] = set()

        for stmt in all_flex_statements:
            account_id = self._get_required_field(stmt, 'accountId', 'FlexStatement')
            # account_id_processed = account_id # Keep track for summary
            logger.info(f"Processing statement for account: {account_id}")
            multipliers = self._build_multiplier_map(stmt)
            option_events = self._build_option_event_map(stmt)

            def should_skip_entry(entry: Any, entry_label: str) -> bool:
                if should_skip_pseudo_account_entry(entry):
                    logger.info(
                        "Skipping %s entry with pseudo accountId in account %s",
                        entry_label,
                        account_id,
                    )
                    return True
                return False

            # --- Process Trades ---
            if stmt.Trades:
                for trade in stmt.Trades:
                    if not isinstance(trade, ibflex.Trade):
                        # Skipping summary objects.
                        # It seems tempting to use SymbolSummary but for FX these
                        # are actually for the full report period, so have no fixed date.
                        continue
                    if should_skip_entry(trade, "Trade"):
                        continue
                    trade_date = self._get_required_field(trade, 'tradeDate', 'Trade')
                    settle_date = self._get_required_field(trade, 'settleDateTarget', 'Trade')
                    symbol = self._get_required_field(trade, 'symbol', 'Trade')
                    description = self._get_required_field(trade, 'description', 'Trade')
                    asset_category = self._get_required_field(trade, 'assetCategory', 'Trade')

                    conid = str(self._get_required_field(trade, 'conid', 'Trade'))
                    isin = trade.isin  # Optional field always present on dataclass
                    valor = None  # Flex does not typically provide Valor

                    quantity = self._to_decimal(
                        self._get_required_field(trade, 'quantity', 'Trade'),
                        'quantity',
                        f"Trade {symbol}",
                    )
                    trade_price = self._to_decimal(
                        self._get_required_field(trade, 'tradePrice', 'Trade'),
                        'tradePrice',
                        f"Trade {symbol}",
                    )
                    trade_price = self._price_apply_multiplier(
                        trade, trade_price, f"Trade {symbol}", multipliers
                    )

                    trade_money = self._to_decimal(
                        self._get_required_field(trade, 'tradeMoney', 'Trade'),
                        'tradeMoney',
                        f"Trade {symbol}",
                    )
                    currency = self._get_required_field(trade, 'currency', 'Trade')
                    # 'BUY' or 'SELL'
                    buy_sell = self._get_required_field(trade, 'buySell', 'Trade')

                    transaction_type: Optional[TradeType] = getattr(trade, 'transactionType', None)
                    expiry_date = getattr(trade, 'expiry', None)
                    close_price = getattr(trade, 'closePrice', None)

                    ib_commission = self._to_decimal(
                        trade.ibCommission if trade.ibCommission is not None else '0',
                        'ibCommission',
                        f"Trade {symbol}",
                    )

                    if asset_category == "CASH":
                        # FX trades are neutral to the portfolio, so we skip them.
                        logger.debug("Skipped CASH trade {symbol}")
                        continue

                    if asset_category not in ["STK", "OPT", "FUT", "BOND", "ETF", "FUND", "FOP"]:
                        logger.warning(
                            f"Skipping trade for unhandled asset "
                            f"category: {asset_category} (Symbol: {symbol})"
                        )
                        continue

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=valor,
                        isin=ISINType(isin) if isin else None,
                        symbol=conid,
                        description=f"{description} ({symbol})",
                    )

                    # Update name metadata (Priority: 8 for Trades)
                    security_name_registry.update(sec_pos, f"{description} ({symbol})", 8)

                    # Store assetCategory and subCategory
                    sub_category = getattr(trade, 'subCategory', None)
                    if sec_pos not in security_asset_category_map:
                        security_asset_category_map[sec_pos] = (asset_category, sub_category)

                    trade_country = self._normalize_country_code(
                        getattr(trade, 'issuerCountryCode', None)
                    )
                    self._maybe_update_security_country(
                        security_country_map,
                        sec_pos,
                        trade_country,
                        "Trade",
                    )

                    unit_price = trade_price if trade_price != Decimal(0) else None
                    name = get_text(buy_sell.value.lower(), self.render_language)
                    # Trade price is 0 for expired, assigned or exercised options.
                    if trade_price == Decimal(0) and asset_category in ["OPT", "FOP"]:
                        # The OptionEAE section says exactly which of the three
                        # happened, so prefer it over guessing from closePrice.
                        eae_action = option_events.get((conid, trade_date))
                        if eae_action is not None:
                            name = get_text(
                                (
                                    'option_expiration'
                                    if eae_action == ibflex.enums.OptionAction.EXPIRE
                                    else 'option_assignment'
                                ),
                                self.render_language,
                            )
                        elif transaction_type == TradeType.BOOKTRADE and close_price is not None:
                            if close_price == Decimal(0) and (
                                expiry_date is None
                                or expiry_date is not None
                                and expiry_date == trade_date
                            ):
                                # Expired worthless. Without an OptionEAE entry this is
                                # inferred, but it makes no difference for tax purposes.
                                name = get_text('option_expiration', self.render_language)
                            elif close_price != Decimal(0):
                                name = get_text('option_assignment', self.render_language)
                        else:
                            # Neither source is in the export. The quantity, date and
                            # zero price — everything that is tax relevant — are known,
                            # so only the label is affected; carry on.
                            logger.warning(
                                "Zero-price %s trade for %s on %s cannot be classified as "
                                "expiry, assignment or exercise: the export has neither an "
                                "OptionEAE section nor a closePrice. The position change is "
                                "imported, only its label is generic.",
                                asset_category,
                                symbol,
                                trade_date,
                            )
                        unit_price = Decimal(0)

                    stock_mutation = SecurityStock(
                        referenceDate=trade_date,
                        mutation=True,
                        quantity=quantity,
                        unitPrice=unit_price,
                        name=name,
                        orderId=trade.ibOrderID,
                        balanceCurrency=currency,
                        quotationType="PIECE",
                    )
                    processed_security_positions[sec_pos]['stocks'].append(stock_mutation)

                    # Cash movements resulting from trades are tracked via the cash transaction section. Only the stock mutation is stored here.

            # --- Process Open Positions (End of Period Snapshot) ---
            if stmt.OpenPositions:
                end_plus_one = self.period_to + timedelta(days=1)
                for open_pos in stmt.OpenPositions:
                    if should_skip_entry(open_pos, "OpenPosition"):
                        continue
                    # Ignore the reportDate from the Flex statement and
                    # use period end + 1 as reference date for the balance
                    # entry. This avoids creating a separate stock entry on
                    # the period end itself which would later result in a
                    # duplicate closing balance.
                    _ = self._get_required_field(
                        open_pos, 'reportDate', 'OpenPosition'
                    )  # validation only
                    symbol = self._get_required_field(open_pos, 'symbol', 'OpenPosition')
                    description = self._get_required_field(open_pos, 'description', 'OpenPosition')
                    asset_category = self._get_required_field(
                        open_pos, 'assetCategory', 'OpenPosition'
                    )

                    conid = str(self._get_required_field(open_pos, 'conid', 'OpenPosition'))
                    isin = open_pos.isin
                    valor = None

                    quantity = self._to_decimal(
                        self._get_required_field(open_pos, 'position', 'OpenPosition'),
                        'position',
                        f"OpenPosition {symbol}",
                    )
                    currency = self._get_required_field(open_pos, 'currency', 'OpenPosition')

                    if asset_category not in ["STK", "OPT", "FUT", "BOND", "ETF", "FUND", "FOP"]:
                        logger.warning(
                            f"Skipping open position for unhandled "
                            f"asset category: {asset_category} "
                            f"(Symbol: {symbol})"
                        )
                        continue

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=valor,
                        isin=ISINType(isin) if isin else None,
                        symbol=conid,
                        description=f"{description} ({symbol})",
                    )

                    # Update name metadata (Priority: 10 for OpenPositions)
                    security_name_registry.update(sec_pos, f"{description} ({symbol})", 10)

                    # Store assetCategory and subCategory
                    sub_category = getattr(open_pos, 'subCategory', None)
                    if sec_pos not in security_asset_category_map:
                        security_asset_category_map[sec_pos] = (asset_category, sub_category)

                    position_country = self._normalize_country_code(
                        getattr(open_pos, 'issuerCountryCode', None)
                    )
                    self._maybe_update_security_country(
                        security_country_map,
                        sec_pos,
                        position_country,
                        "OpenPosition",
                    )

                    mark_price = None
                    if getattr(open_pos, 'markPrice', None) is not None:
                        mark_price = self._to_decimal(
                            open_pos.markPrice, 'markPrice', f"OpenPosition {symbol}"
                        )
                        mark_price = self._price_apply_multiplier(
                            open_pos, mark_price, f"OpenPosition {symbol}", multipliers
                        )

                    pos_value = None
                    if getattr(open_pos, 'positionValue', None) is not None:
                        pos_value = self._to_decimal(
                            open_pos.positionValue, 'positionValue', f"OpenPosition {symbol}"
                        )

                    balance_stock = SecurityStock(
                        # Balance as of the period end + 1
                        referenceDate=end_plus_one,
                        mutation=False,
                        quantity=quantity,
                        balanceCurrency=currency,
                        quotationType="PIECE",
                        unitPrice=mark_price,
                        balance=pos_value,
                    )
                    processed_security_positions[sec_pos]['stocks'].append(balance_stock)

            # --- Process Transfers ---
            if stmt.Transfers:
                for transfer in stmt.Transfers:
                    if should_skip_entry(transfer, "Transfer"):
                        continue
                    asset_category = self._get_required_field(transfer, 'assetCategory', 'Transfer')
                    asset_cat_val = (
                        asset_category.value
                        if hasattr(asset_category, 'value')
                        else str(asset_category)
                    )
                    if str(asset_cat_val).upper() == 'CASH':
                        continue

                    tx_date = transfer.date
                    if tx_date is None:
                        tx_dt = transfer.dateTime
                        if tx_dt is not None:
                            tx_date = tx_dt.date() if hasattr(tx_dt, 'date') else tx_dt
                    if tx_date is None:
                        raise ValueError('Transfer missing date/dateTime')

                    symbol = self._get_required_field(transfer, 'symbol', 'Transfer')
                    description = self._get_required_field(transfer, 'description', 'Transfer')
                    conid = str(self._get_required_field(transfer, 'conid', 'Transfer'))
                    isin = transfer.isin

                    quantity = self._to_decimal(
                        self._get_required_field(transfer, 'quantity', 'Transfer'),
                        'quantity',
                        f"Transfer {symbol}",
                    )

                    direction = transfer.direction
                    direction_val = direction.value.upper() if direction else None
                    is_cancel = ibflex.Code.CANCEL in (transfer.code or ())
                    # IBKR encodes a transfer that opens a short position as
                    # direction IN with a negative quantity (and the mirror case
                    # on the way out). The quantity is what moves the position,
                    # so it is authoritative; the mismatch is worth noting but
                    # not worth refusing the whole export over. Whether the
                    # resulting negative balance is acceptable is decided once,
                    # in CleanupCalculator.
                    if (
                        direction_val == 'OUT'
                        and quantity > 0
                        or direction_val == 'IN'
                        and quantity < 0
                    ) and not is_cancel:
                        logger.warning(
                            "Transfer direction %s but quantity %s for %s; following the "
                            "quantity. This is how IBKR reports transfers that open or "
                            "close a short position.",
                            direction_val,
                            quantity,
                            symbol,
                        )

                    currency = self._get_required_field(transfer, 'currency', 'Transfer')

                    transfer_type = self._get_required_field(transfer, 'type', 'Transfer')
                    transfer_type_val = transfer_type.value
                    account = self._get_required_field(transfer, 'account', 'Transfer')

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=None,
                        isin=ISINType(isin) if isin else None,
                        symbol=conid,
                        description=f"{description} ({symbol})",
                    )

                    # Update name metadata (Priority: 5 for Transfers)
                    security_name_registry.update(sec_pos, f"{description} ({symbol})", 5)

                    stock_mutation = SecurityStock(
                        referenceDate=tx_date,
                        mutation=True,
                        quantity=quantity,
                        name=f"{transfer_type_val} {account}"
                        + (" (Cancelled)" if is_cancel else ""),
                        balanceCurrency=currency,
                        quotationType="PIECE",
                    )

                    processed_security_positions[sec_pos]['stocks'].append(stock_mutation)

            # --- Process Corporate Actions ---
            if stmt.CorporateActions:
                for action in stmt.CorporateActions:
                    if should_skip_entry(action, "CorporateAction"):
                        continue
                    # CorporateActions have dates with time stamps, which can be at end of business etc
                    # to avoid this we assume that the reportDate is always the effective date when we see
                    # a difference in the amount of securities.
                    action_date = self._get_required_field(action, "reportDate", "CorporateAction")

                    if hasattr(action_date, "date"):
                        action_date = action_date.date()
                    elif isinstance(action_date, str):
                        date_part = action_date.split(";")[0].split("T")[0]
                        action_date = date.fromisoformat(date_part)

                    symbol = self._get_required_field(action, "symbol", "CorporateAction")
                    description = self._get_required_field(action, "description", "CorporateAction")
                    conid = str(self._get_required_field(action, "conid", "CorporateAction"))
                    isin = action.isin

                    quantity = self._to_decimal(
                        self._get_required_field(action, "quantity", "CorporateAction"),
                        "quantity",
                        f"CorporateAction {symbol}",
                    )
                    currency = self._get_required_field(action, "currency", "CorporateAction")

                    action_description = getattr(action, "actionDescription", None) or description

                    sec_pos = SecurityPosition(
                        depot=account_id,
                        valor=None,
                        isin=ISINType(isin) if isin else None,
                        symbol=conid,
                        description=f"{description} ({symbol})",
                    )

                    # Update name metadata for CorporateActions
                    # Priority logic:
                    # - Issuer available: 4
                    # - Description only (short): 1
                    # - Description only (long): 0 (use symbol fallback via helper logic if priority 0 beats existing)
                    # Actually, if description is long, we prefer symbol.
                    # Let's say:
                    # - Issuer: 4
                    # - Description <= 50 chars: 1
                    # - Description > 50 chars: -1 (Don't use if possible, prefer symbol if nothing else)

                    issuer = getattr(action, "issuer", None)
                    ca_name = f"{description} ({symbol})"
                    ca_priority = 1

                    if issuer:
                        ca_name = f"{issuer} ({symbol})"
                        ca_priority = 4
                    elif len(description) > 50:
                        # Long description and no issuer. Prefer symbol (short name).
                        ca_name = f"{symbol} ({symbol})"
                        ca_priority = 2
                    else:
                        ca_name = f"{description} ({symbol})"
                        ca_priority = 3

                    security_name_registry.update(sec_pos, ca_name, ca_priority)

                    sub_category = getattr(action, "subCategory", None)
                    if sub_category == "RIGHT":
                        rights_issue_positions.add(sec_pos)

                    stock_mutation = SecurityStock(
                        referenceDate=action_date,
                        mutation=True,
                        quantity=quantity,
                        name=action_description,
                        balanceCurrency=currency,
                        quotationType="PIECE",
                    )

                    processed_security_positions[sec_pos]["stocks"].append(stock_mutation)

            # --- Process Cash Transactions ---
            if stmt.CashTransactions:
                cash_transactions = self._select_cash_transaction_level(
                    stmt.CashTransactions, account_id
                )
                for cash_tx in cash_transactions:
                    if should_skip_entry(cash_tx, "CashTransaction"):
                        continue
                    tx_date_time = self._get_required_field(cash_tx, 'dateTime', 'CashTransaction')
                    # Ensure tx_date is a date object
                    tx_date = (
                        tx_date_time.date()
                        if hasattr(tx_date_time, 'date')
                        else self._get_required_field(cash_tx, 'tradeDate', 'CashTransaction')
                    )

                    description = self._get_required_field(
                        cash_tx, 'description', 'CashTransaction'
                    )
                    amount = self._to_decimal(
                        self._get_required_field(cash_tx, 'amount', 'CashTransaction'),
                        'amount',
                        f"CashTransaction {description[:30]}",
                    )
                    currency = self._get_required_field(cash_tx, 'currency', 'CashTransaction')

                    # Everything we take in, tallied per category, so it can be
                    # checked against IBKR's own totals once the loop is done.
                    if cash_tx.type is not None:
                        booked_cash[(str(currency), cash_tx.type)] += amount

                    security_id = cash_tx.conid
                    tx_type = cash_tx.type
                    if tx_type is None:
                        raise ValueError(f"CashTransaction type is missing for {description}")

                    if tx_type == ibflex.CashAction.WHTAX:
                        saw_withholding_rows = True
                    elif tx_type in (
                        ibflex.CashAction.DIVIDEND,
                        ibflex.CashAction.PAYMENTINLIEU,
                        ibflex.CashAction.BONDINTRCVD,
                    ):
                        saw_income_rows = True

                    # Skip fees even if they are associated with a security (e.g., ADR fees)
                    if tx_type in [ibflex.CashAction.FEES, ibflex.CashAction.ADVISORFEES]:
                        logger.info("Fee on %s recorded as an expense.", description)
                        omitted_cash_items.append(
                            (description, amount, currency, EXPENSE_TYPE_OTHER, tx_date)
                        )
                        continue

                    if security_id:
                        tx_type_str = tx_type.value
                        tx_type_str_lower = str(tx_type_str).lower()
                        asset_category = getattr(cash_tx, 'assetCategory', None)
                        # Guard against booking general broker/cash interest under a
                        # security, which would misreport it as securities income.
                        # Bond interest is fine at import time (assetCategory == "BOND").
                        # This used to be a bare `assert`, which disappears under
                        # `python -O` and would let the bad booking through silently.
                        if 'interest' in tx_type_str_lower and asset_category != 'BOND':
                            raise ValueError(
                                f"CashTransaction of type {tx_type_str} is linked to security "
                                f"conid={security_id} but has assetCategory "
                                f"{asset_category!r} rather than BOND: "
                                f"{description}. Booking it under the security would "
                                "report broker interest as securities income."
                            )

                        sec_pos_key = self._find_processed_security_position(
                            processed_security_positions,
                            account_id,
                            security_id,
                        )

                        sym_attr = cash_tx.symbol

                        if sec_pos_key is None:
                            sec_pos_key = self._build_cash_transaction_security_position(
                                account_id,
                                cash_tx,
                                description,
                            )

                        if asset_category:
                            sub_category = getattr(cash_tx, 'subCategory', None)
                            if sec_pos_key not in security_asset_category_map:
                                security_asset_category_map[sec_pos_key] = (
                                    asset_category,
                                    sub_category,
                                )

                        # Update name metadata (Priority: 0 for CashTransactions - lowest)
                        # Use description or symbol if description is generic?
                        # Usually description in CashTx is like "Dividend ...". Not great for security name.
                        # But if it's the only source, it's better than nothing.
                        security_name_registry.update(
                            sec_pos_key,
                            f"{description} ({sym_attr})" if sym_attr else description,
                            0,
                        )

                        sec_payment = self._build_security_payment(
                            payment_date=tx_date,
                            description=description,
                            currency=currency,
                            amount=amount,
                            tx_type=tx_type,
                        )
                        processed_security_positions[sec_pos_key]['payments'].append(sec_payment)
                    else:
                        if tx_type in [ibflex.CashAction.DEPOSITWITHDRAW]:
                            # Not Tax Relant event
                            continue
                        elif tx_type in [ibflex.CashAction.BROKERINTPAID]:
                            # Interst paid due to negative balance: description starting with "<CURRENCY> DEBIT INT FOR"
                            if description.startswith(f"{currency} DEBIT INT FOR"):
                                # Tax relevant event. Fall through to create a bank payment.
                                pass
                            else:
                                # Negative credit interest on a positive balance
                                # is an expense (eCH-0196 expenseType 29,
                                # "Negativzinsen im Privatvermoegen"), not debt
                                # interest, so it must not land in the liability
                                # section. There is no expenses section yet.
                                logger.info(
                                    "Broker interest charge %s (%s) recorded as an expense.",
                                    description,
                                    amount,
                                )
                                omitted_cash_items.append(
                                    (
                                        description,
                                        amount,
                                        currency,
                                        (
                                            EXPENSE_TYPE_NEGATIVE_INTEREST
                                            if "CREDIT INT" in description.upper()
                                            else EXPENSE_TYPE_OTHER
                                        ),
                                        tx_date,
                                    )
                                )
                                continue
                        elif tx_type in [
                            ibflex.CashAction.FEES,
                            ibflex.CashAction.ADVISORFEES,
                        ]:
                            logger.info("Fee %s recorded as an expense.", description)
                            omitted_cash_items.append(
                                (
                                    description,
                                    amount,
                                    currency,
                                    (
                                        EXPENSE_TYPE_MANAGEMENT
                                        if tx_type == ibflex.CashAction.ADVISORFEES
                                        else EXPENSE_TYPE_OTHER
                                    ),
                                    tx_date,
                                )
                            )
                            continue
                        elif tx_type in [ibflex.CashAction.BROKERINTRCVD]:
                            # Tax relevant event. Fall through to create a bank payment.
                            pass
                        elif tx_type in [ibflex.CashAction.WHTAX]:
                            # Withholding tax not linked to a security (e.g. yield enhancement).
                            # Tax relevant event. Fall through to create a bank payment.
                            pass
                        else:
                            raise ValueError(
                                f"CashTransaction type {tx_type} is not supported for {description}"
                            )
                        if tx_type == ibflex.CashAction.WHTAX:
                            interest_withholding.append((description, amount, currency))

                        cash_pos_key = (account_id, currency, "MAIN_CASH")

                        bank_payment = BankAccountPayment(
                            paymentDate=tx_date,
                            name=description,
                            amountCurrency=currency,
                            amount=amount,
                            is_withholding_tax=(tx_type == ibflex.CashAction.WHTAX),
                        )
                        processed_cash_positions[cash_pos_key]['payments'].append(bank_payment)

        # --- Process Corrections Flex Files ---
        # Import withholding-tax corrections from a post-year-end flex export.
        # Only CashTransactions whose settleDate falls within the tax period
        # are included, so that reversals/adjustments are netted against the
        # original deductions automatically during reconciliation.
        if corrections_filenames:
            self._import_corrections_flex_files(
                corrections_filenames,
                processed_security_positions,
            )

        # --- Assemble the partial TaxStatement and augment it via the shared
        # post-processing stage. The client/institution/canton block below
        # continues to write onto the same object.
        tax_statement = TaxStatement(
            minorVersion=1,
            periodFrom=self.period_from,
            periodTo=self.period_to,
            taxPeriod=self.period_from.year,
        )

        ignore_rights_issues_by_account: Dict[str, bool] = {
            s.account_number: getattr(s, "ignore_rights_issues", False)
            for s in self.account_settings_list
            if getattr(s, "account_number", None)
        }

        # Positions where neither the Flex data nor the ISIN told us a country
        # and we had to fall back to the default.
        guessed_country_positions: List[str] = []

        def _hints_for(sec_pos: SecurityPosition) -> PositionHints:
            asset_cat, _sub_category = security_asset_category_map.get(sec_pos, ("STK", None))
            sec_category = IBKR_ASSET_CATEGORY_TO_ECH_SECURITY_CATEGORY.get(asset_cat)
            if not sec_category:
                raise ValueError(f"Unknown asset category: {asset_cat}")
            is_rights = sec_pos in rights_issue_positions
            skip_if_zero = is_rights and ignore_rights_issues_by_account.get(sec_pos.depot, False)
            # IBKR leaves issuerCountryCode empty on many rows (notably
            # derivatives and older data). The ISIN prefix is a far better
            # second source than assuming the security is American, because the
            # country drives the DA-1 grouping in the statement.
            country = security_country_map.get(sec_pos) or country_from_isin(sec_pos.isin)
            if not country:
                country = DEFAULT_SECURITY_COUNTRY
                guessed_country_positions.append(sec_pos.get_processing_identifier())
            return PositionHints(
                security_category=sec_category,
                country=country,
                is_rights_issue=is_rights,
                skip_if_zero=skip_if_zero,
            )

        augment_list_of_securities(
            tax_statement,
            processed_security_positions,
            name_registry=security_name_registry,
            hints_for=_hints_for,
        )

        if guessed_country_positions:
            logger.warning(
                "No issuer country in the Flex data and no ISIN for %d position(s); "
                "defaulted to '%s'. Verify the country column for: %s%s",
                len(guessed_country_positions),
                DEFAULT_SECURITY_COUNTRY,
                ", ".join(guessed_country_positions[:10]),
                "..." if len(guessed_country_positions) > 10 else "",
            )

        # --- Collect per-account dateOpened / dateClosed + CashReport seeds ---
        account_dates: Dict[str, Dict[str, date | None]] = {}
        account_countries: Dict[str, str] = {}
        for s_stmt in all_flex_statements:
            stmt_account_id = self._get_required_field(s_stmt, 'accountId', 'FlexStatement')
            if s_stmt.AccountInformation:
                acc_info = s_stmt.AccountInformation
                account_dates[stmt_account_id] = {
                    'dateOpened': acc_info.dateOpened,
                    'dateClosed': acc_info.dateClosed,
                }
                entity = str(getattr(acc_info, 'ibEntity', None) or '').strip().upper()
                entity_country = IBKR_ENTITY_TO_COUNTRY.get(entity)
                if entity_country:
                    account_countries[stmt_account_id] = entity_country
                elif entity:
                    logger.warning(
                        "Unknown IBKR entity '%s' for account %s; "
                        "reporting the cash accounts under '%s'.",
                        entity,
                        stmt_account_id,
                        DEFAULT_BANK_ACCOUNT_COUNTRY,
                    )

        seed_entries: List[CashAccountEntry] = []
        for s_stmt in all_flex_statements:
            account_id = s_stmt.accountId
            if not s_stmt.CashReport:
                continue
            for cash_report_currency_obj in s_stmt.CashReport:
                if should_skip_pseudo_account_entry(cash_report_currency_obj):
                    logger.info(
                        "Skipping CashReport entry with pseudo accountId in account %s",
                        account_id,
                    )
                    continue
                curr = cash_report_currency_obj.currency
                if curr is None or curr == "BASE_SUMMARY":
                    continue
                curr = str(curr)

                closing_balance_value: Optional[Decimal] = None
                if cash_report_currency_obj.endingCash is not None:
                    closing_balance_value = self._to_decimal(
                        cash_report_currency_obj.endingCash,
                        'endingCash',
                        f"CashReport {account_id} {curr}",
                    )
                elif (
                    getattr(cash_report_currency_obj, 'balance', None) is not None
                    and getattr(cash_report_currency_obj, 'reportDate', None) == self.period_to
                ):
                    closing_balance_value = self._to_decimal(
                        getattr(cash_report_currency_obj, 'balance'),
                        'balance',
                        f"CashReport {account_id} {curr}",
                    )

                if closing_balance_value is None:
                    continue
                dates_for_account = account_dates.get(account_id, {})
                seed_entries.append(
                    CashAccountEntry(
                        account_id=account_id,
                        currency=curr,
                        closing_balance=closing_balance_value,
                        name=f"{account_id} {curr}",
                        number=f"{account_id}-{curr}",
                        country=account_countries.get(account_id, DEFAULT_BANK_ACCOUNT_COUNTRY),
                        opening_date=dates_for_account.get('dateOpened'),
                        closing_date=dates_for_account.get('dateClosed'),
                    )
                )

        cash_entries = fold_cash_payments(seed_entries, processed_cash_positions)
        augment_list_of_bank_accounts(tax_statement, cash_entries)

        self._verify_against_cash_report(tax_statement, all_flex_statements, booked_cash)
        self._build_list_of_expenses(
            tax_statement, omitted_cash_items, all_flex_statements[0].accountId or ""
        )
        self._warn_about_omitted_cash(tax_statement, omitted_cash_items)
        self._warn_about_interest_withholding(tax_statement, interest_withholding)

        if saw_income_rows and not saw_withholding_rows:
            tax_statement.broker_reports_withholding_tax = False
            logger.warning(
                "The Flex export reports dividends but not a single withholding tax "
                "row. Add the 'Withholding Tax' cash transaction type to the Flex "
                "Query if tax was deducted."
            )
            tax_statement.critical_warnings.append(
                CriticalWarning(
                    category=CriticalWarningCategory.OTHER,
                    message=(
                        "The broker export contains dividends but no withholding tax "
                        "records at all. Any Verrechnungssteuer or DA-1 claim in this "
                        "statement therefore rests on the Kursliste alone and was not "
                        "checked against what was withheld. If tax was deducted, re-run "
                        "the Flex Query with the 'Withholding Tax' cash transaction type "
                        "selected."
                    ),
                    source="IbkrImporter",
                )
            )
        elif saw_withholding_rows:
            tax_statement.broker_reports_withholding_tax = True

        logger.info(
            "Partial TaxStatement created with Trades, OpenPositions, "
            "and basic CashTransactions mapping."
        )

        # Fill in institution
        # Name is sufficient. Avoid setting legal identifiers avoid implying this is
        # officially from the broker.
        tax_statement.institution = Institution(name="Interactive Brokers")

        # --- Create Client object ---
        # TODO: Handle joint accounts
        client_obj: Optional[Client] = None
        if all_flex_statements:
            first_statement = all_flex_statements[0]
            acc_info = getattr(first_statement, 'AccountInformation', None)
            if acc_info:
                canton = parse_swiss_canton(getattr(acc_info, 'stateResidentialAddress', None))
                if canton:
                    tax_statement.canton = canton
                    logger.info(f"Set canton from IBKR stateResidentialAddress: {canton}")

                client_first_name, client_last_name = resolve_first_last_name(
                    first_name=getattr(acc_info, 'firstName', None),
                    last_name=getattr(acc_info, 'lastName', None),
                    full_name=getattr(acc_info, 'name', None),
                    account_holder_name=getattr(acc_info, 'accountHolderName', None),
                )
                client_obj = build_client(
                    client_number=getattr(acc_info, 'accountId', None),
                    first_name=client_first_name,
                    last_name=client_last_name,
                )
        if client_obj:
            tax_statement.client = [client_obj]
        # --- End Client object ---

        return tax_statement


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logger.info("IbkrImporter module loaded.")
    # Example usage:
    # from .config.models import IbkrAccountSettings
    # settings = IbkrAccountSettings(account_id="U1234567")
    # importer = IbkrImporter(
    #     period_from=date(2023, 1, 1),
    #     period_to=date(2023, 12, 31),
    #     account_settings_list=[settings]
    # )
    #
    # # Create a dummy XML file for testing
    # DUMMY_XML_CONTENT = """
    # <FlexQueryResponse queryName="Test Query" type="AF">
    #   <FlexStatements count="1">
    #     <FlexStatement accountId="U1234567" fromDate="2023-01-01"
    #                    toDate="2023-12-31" period="Year"
    #                    whenGenerated="2024-01-15T10:00:00">
    #       <Trades>
    #         <Trade assetCategory="STK" symbol="AAPL" tradeDate="2023-05-10"
    #                quantity="10" tradePrice="150.00" currency="USD" />
    #       </Trades>
    #       <CashTransactions>
    #         <CashTransaction type="Deposits/Withdrawals"
    #                          dateTime="2023-02-01T00:00:00"
    #                          amount="1000" currency="USD" />
    #       </CashTransactions>
    #       <OpenPositions>
    #         <OpenPosition assetCategory="STK" symbol="MSFT" position="100"
    #                       markPrice="300" currency="USD" />
    #       </OpenPositions>
    #     </FlexStatement>
    #   </FlexStatements>
    # </FlexQueryResponse>
    # """
    # DUMMY_FILE = "dummy_ibkr_flex.xml"
    # with open(DUMMY_FILE, "w") as f:
    #     f.write(DUMMY_XML_CONTENT)
    #
    # try:
    #     print(f"Attempting to import dummy file: {DUMMY_FILE}")
    #     statement = importer.import_files([DUMMY_FILE])
    #     from devtools import debug
    #     debug(statement)
    #     print("Dummy import successful.")
    # except Exception as e:
    #     print(f"Error during example usage: {e}")
    # finally:
    #     if os.path.exists(DUMMY_FILE):
    #         os.remove(DUMMY_FILE)
    logger.info(
        "Example usage in __main__ needs IbkrAccountSettings to be defined "
        "in config.models and 'pip install ibflex devtools'."
    )
