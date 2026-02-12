#!/usr/bin/env python3
"""
Fetch end-of-year prices for securities using Yahoo Finance and update manual_prices.csv.

This script reads the current manual_prices.csv file and fetches the latest prices
from Yahoo Finance for the specified date. It can also identify securities missing
from the Kursliste by analyzing warnings from a recent run.

Usage:
    python scripts/fetch_prices_yfinance.py --year 2025
    python scripts/fetch_prices_yfinance.py --year 2025 --isin US88160R1014 --symbol TSLA
    python scripts/fetch_prices_yfinance.py --year 2025 --update-all
"""

import argparse
import csv
import sys
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance is not installed.")
    print("Please install it with: pip install yfinance")
    sys.exit(1)


def get_project_root() -> Path:
    """Get the project root directory."""
    # This script is in scripts/, so go up one level
    return Path(__file__).parent.parent


def read_manual_prices(csv_path: Path) -> List[Dict[str, str]]:
    """Read existing manual prices from CSV."""
    entries = []
    if csv_path.exists():
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                entries.append(row)
    return entries


def write_manual_prices(csv_path: Path, entries: List[Dict[str, str]]):
    """Write manual prices to CSV."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['isin', 'date', 'price', 'currency'])
        writer.writeheader()
        writer.writerows(entries)
    print(f"Updated {csv_path}")


def fetch_price_yfinance(symbol: str, target_date: date) -> Optional[Tuple[Decimal, str]]:
    """
    Fetch the closing price for a symbol on a specific date using Yahoo Finance.

    Args:
        symbol: The ticker symbol (e.g., 'TSLA', 'AAPL')
        target_date: The date to fetch the price for

    Returns:
        Tuple of (price, currency) or None if not found
    """
    try:
        ticker = yf.Ticker(symbol)

        # Fetch historical data for a range around the target date
        # Yahoo Finance might not have data for the exact date (weekends, holidays)
        # so we fetch a range and find the closest date
        start_date = target_date.replace(month=12, day=15)  # Start from mid-December
        end_date = target_date.replace(month=12, day=31) if target_date.month == 12 else target_date

        hist = ticker.history(start=start_date, end=end_date)

        if hist.empty:
            print(f"  WARNING: No price data found for {symbol}")
            return None

        # Get the last available closing price
        last_date = hist.index[-1]
        close_price = hist['Close'].iloc[-1]

        # Get currency from ticker info
        try:
            info = ticker.info
            currency = info.get('currency', 'USD')
        except:
            currency = 'USD'  # Default to USD if we can't get the currency

        print(f"  ✓ {symbol}: {close_price:.2f} {currency} (date: {last_date.date()})")

        return (Decimal(str(round(close_price, 2))), currency)

    except Exception as e:
        print(f"  ERROR fetching {symbol}: {e}")
        return None


def get_symbol_from_isin(isin: str) -> Optional[str]:
    """
    Try to derive a ticker symbol from an ISIN.
    This is a best-effort approach and may not work for all securities.
    """
    # Common patterns:
    # US ISINs: US + 9-char CUSIP + check digit
    # For US stocks, we can try looking up by ISIN directly in yfinance

    # Try to search by ISIN first (some APIs support this)
    try:
        ticker = yf.Ticker(isin)
        info = ticker.info
        if 'symbol' in info and info['symbol']:
            return info['symbol']
    except:
        pass

    return None


def main():
    parser = argparse.ArgumentParser(
        description='Fetch security prices from Yahoo Finance and update manual_prices.csv'
    )
    parser.add_argument(
        '--year',
        type=int,
        required=True,
        help='Tax year (e.g., 2025) - will fetch prices for December 31st'
    )
    parser.add_argument(
        '--isin',
        type=str,
        help='Specific ISIN to update'
    )
    parser.add_argument(
        '--symbol',
        type=str,
        help='Yahoo Finance ticker symbol (required if --isin is specified)'
    )
    parser.add_argument(
        '--update-all',
        action='store_true',
        help='Update all entries in the CSV (requires symbols to be known)'
    )
    parser.add_argument(
        '--csv',
        type=Path,
        help='Path to manual_prices.csv (default: data/manual_prices.csv)'
    )

    args = parser.parse_args()

    # Determine paths
    project_root = get_project_root()
    csv_path = args.csv if args.csv else project_root / 'data' / 'manual_prices.csv'

    # Target date (end of year)
    target_date = date(args.year, 12, 31)
    date_str = target_date.strftime('%Y-%m-%d')

    print(f"Fetching prices for {date_str}")
    print(f"CSV file: {csv_path}")
    print()

    # Read existing entries
    entries = read_manual_prices(csv_path)
    entries_by_isin = {entry['isin']: entry for entry in entries}

    if args.isin and args.symbol:
        # Update specific ISIN
        print(f"Fetching price for {args.isin} ({args.symbol})...")
        result = fetch_price_yfinance(args.symbol, target_date)

        if result:
            price, currency = result
            entry = {
                'isin': args.isin,
                'date': date_str,
                'price': str(price),
                'currency': currency
            }

            if args.isin in entries_by_isin:
                # Update existing entry
                entries_by_isin[args.isin].update(entry)
                print(f"Updated existing entry for {args.isin}")
            else:
                # Add new entry
                entries.append(entry)
                print(f"Added new entry for {args.isin}")

            write_manual_prices(csv_path, entries)

    elif args.update_all:
        print("ERROR: --update-all requires a mapping of ISIN to symbol.")
        print("Please create a symbol mapping first or update entries individually.")
        print()
        print("Known mappings (add these as needed):")
        print("  CA65118M1032 -> NCAUF")
        print("  US45783Q1004 -> NOTV")
        print("  US64131A1051 -> STIM")
        print("  US02080L1026 -> TKNO")
        print("  US30068X1037 -> XGN")
        sys.exit(1)

    else:
        # Interactive mode: show current entries and prompt for updates
        print("Current manual prices:")
        print()

        if not entries:
            print("  (No entries found)")
        else:
            for entry in entries:
                print(f"  {entry['isin']}: {entry['price']} {entry['currency']} on {entry['date']}")

        print()
        print("To update prices, use:")
        print(f"  python scripts/fetch_prices_yfinance.py --year {args.year} --isin <ISIN> --symbol <SYMBOL>")
        print()
        print("Example:")
        print(f"  python scripts/fetch_prices_yfinance.py --year {args.year} --isin CA65118M1032 --symbol NCAUF")


if __name__ == '__main__':
    main()
