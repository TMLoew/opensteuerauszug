import csv
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Tuple
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ManualPriceProvider:
    """Provides manual prices for securities missing from the Kursliste.

    This provider reads prices from a CSV file with the format:
    isin,date,price,currency

    Example:
    CA65118M1032,2025-12-31,0.50,USD
    US45783Q1004,2025-12-31,3.25,USD
    """

    def __init__(self, csv_path: Optional[str] = None):
        """Initialize the manual price provider.

        Args:
            csv_path: Path to the CSV file containing manual prices.
                     If None, no manual prices will be loaded.
        """
        self._prices: Dict[Tuple[str, str], Tuple[Decimal, str]] = {}
        if csv_path:
            self._load_from_csv(csv_path)

    def _load_from_csv(self, file_path: str):
        """Loads manual prices from a CSV file.

        The CSV should have columns: isin, date, price, currency
        Prices are indexed by (isin, date) tuple for fast lookup.
        """
        try:
            csv_file = Path(file_path)
            if not csv_file.exists():
                logger.info(f"Manual prices CSV file not found: {file_path}")
                return

            with open(file_path, mode='r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)

                required_fields = {'isin', 'date', 'price', 'currency'}
                if not required_fields.issubset(set(reader.fieldnames or [])):
                    logger.warning(
                        f"Manual prices CSV {file_path} missing required fields. "
                        f"Expected: {required_fields}, Got: {reader.fieldnames}"
                    )
                    return

                count = 0
                for row in reader:
                    isin = row['isin'].strip().upper()
                    date_str = row['date'].strip()
                    price_str = row['price'].strip()
                    currency = row['currency'].strip().upper()

                    if not isin or not date_str or not price_str or not currency:
                        continue

                    try:
                        # Parse and validate the date
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')

                        # Parse price as Decimal for precision
                        price = Decimal(price_str)

                        # Store by (isin, date_str) tuple
                        key = (isin, date_str)
                        self._prices[key] = (price, currency)
                        count += 1

                    except ValueError as e:
                        logger.warning(
                            f"Invalid entry in manual prices CSV: {row}. Error: {e}"
                        )
                        continue

                logger.info(f"Loaded {count} manual prices from {file_path}")

        except FileNotFoundError:
            logger.info(f"Manual prices CSV file not found: {file_path}")
        except Exception as e:
            logger.warning(f"Could not load manual prices from {file_path}: {e}")

    def get_price(self, isin: str, date: str) -> Optional[Tuple[Decimal, str]]:
        """Get the manual price for a security on a specific date.

        Args:
            isin: The ISIN of the security
            date: The date in YYYY-MM-DD format

        Returns:
            Tuple of (price, currency) if found, None otherwise
        """
        key = (isin.upper(), date)
        return self._prices.get(key)

    def has_price(self, isin: str, date: str) -> bool:
        """Check if a manual price exists for a security on a specific date.

        Args:
            isin: The ISIN of the security
            date: The date in YYYY-MM-DD format

        Returns:
            True if a manual price exists, False otherwise
        """
        return self.get_price(isin, date) is not None
