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

    The provider supports year-specific CSV files. If a tax_year is provided,
    it will look for a file named 'manual_prices_YYYY.csv' first, then fall back
    to the generic 'manual_prices.csv' if the year-specific file doesn't exist.
    """

    def __init__(self, csv_path: Optional[str] = None, tax_year: Optional[int] = None):
        """Initialize the manual price provider.

        Args:
            csv_path: Path to the CSV file containing manual prices, or path to directory
                     containing year-specific files. If None, no manual prices will be loaded.
            tax_year: The tax year to load prices for. If provided, will look for
                     year-specific file (e.g., manual_prices_2025.csv) in the same
                     directory as csv_path, falling back to csv_path if not found.
        """
        self._prices: Dict[Tuple[str, str], Tuple[Decimal, str]] = {}
        if csv_path:
            # Determine which file to load based on tax_year
            file_to_load = self._resolve_csv_path(csv_path, tax_year)
            if file_to_load:
                self._load_from_csv(file_to_load)

    def _resolve_csv_path(self, csv_path: str, tax_year: Optional[int]) -> Optional[str]:
        """Resolve the CSV file path, checking for year-specific files.

        Args:
            csv_path: Base CSV path (file or directory)
            tax_year: Tax year to look for

        Returns:
            Path to the CSV file to load, or None if no file found
        """
        csv_file = Path(csv_path)

        # If tax_year is provided, try year-specific file first
        if tax_year:
            # If csv_path is a directory, look for year-specific file in it
            if csv_file.is_dir():
                year_specific_path = csv_file / f"manual_prices_{tax_year}.csv"
                if year_specific_path.exists():
                    logger.info(f"Using year-specific manual prices file: {year_specific_path}")
                    return str(year_specific_path)
                # Fall back to generic file in directory
                generic_path = csv_file / "manual_prices.csv"
                if generic_path.exists():
                    logger.info(f"Year-specific file not found, using generic: {generic_path}")
                    return str(generic_path)
            else:
                # csv_path is a file path, construct year-specific path in same directory
                parent_dir = csv_file.parent
                year_specific_path = parent_dir / f"manual_prices_{tax_year}.csv"
                if year_specific_path.exists():
                    logger.info(f"Using year-specific manual prices file: {year_specific_path}")
                    return str(year_specific_path)
                # Fall back to the original csv_path
                if csv_file.exists():
                    logger.info(f"Year-specific file not found, using: {csv_path}")
                    return csv_path
        else:
            # No tax_year provided, use the path as-is
            if csv_file.is_dir():
                generic_path = csv_file / "manual_prices.csv"
                if generic_path.exists():
                    return str(generic_path)
            elif csv_file.exists():
                return csv_path

        logger.info(f"No manual prices file found for path: {csv_path}" +
                   (f", tax year: {tax_year}" if tax_year else ""))
        return None

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
