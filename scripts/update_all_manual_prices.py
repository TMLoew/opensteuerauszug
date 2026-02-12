#!/usr/bin/env python3
"""
Update all manual prices using Yahoo Finance with a predefined ISIN-to-symbol mapping.

This script maintains a mapping of ISIN codes to Yahoo Finance ticker symbols
and updates all prices in manual_prices.csv automatically.

Usage:
    python scripts/update_all_manual_prices.py --year 2025
    python scripts/update_all_manual_prices.py --year 2025 --dry-run
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


# ISIN to Yahoo Finance ticker symbol mapping
# Add your securities here
ISIN_TO_SYMBOL = {
    'CA06683K1066': 'BYAGF',
    'CA1482391069': 'CGLCF',
    'CA65118M1032': 'NCAUF',  # NEWCORE GOLD LTD
    'KYG436581063': 'HOND',
    'US0094961002': 'AIRS',
    'US02080L1026': 'TKNO',  # ALPHA TEKNOVA INC
    'US0301112076': 'AMSC',
    'US21873S1087': 'CRWV',
    'US30068X1037': 'XGN',  # EXAGEN INC
    'US45783Q1004': 'NOTV',  # INOTIV INC
    'US64131A1051': 'STIM',  # NEURONETICS INC
    'US75383L1026': 'RAPP',
}


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


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
        start_date = target_date.replace(month=12, day=15)
        end_date = target_date.replace(year=target_date.year + 1, month=1, day=15)

        hist = ticker.history(start=start_date, end=end_date)

        if hist.empty:
            print(f"  ⚠ {symbol}: No price data found")
            return None

        # Find the closest date to our target
        hist_dates = [d.date() for d in hist.index]
        closest_date = min(hist_dates, key=lambda d: abs((d - target_date).days))
        closest_idx = hist_dates.index(closest_date)

        close_price = hist['Close'].iloc[closest_idx]

        # Get currency from ticker info
        try:
            info = ticker.info
            currency = info.get('currency', 'USD')
        except:
            currency = 'USD'

        date_diff = (closest_date - target_date).days
        date_note = f" (actual date: {closest_date})" if date_diff != 0 else ""
        print(f"  ✓ {symbol}: {close_price:.2f} {currency}{date_note}")

        return (Decimal(str(round(close_price, 2))), currency)

    except Exception as e:
        print(f"  ✗ {symbol}: ERROR - {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Update all manual prices from Yahoo Finance using predefined ISIN-to-symbol mapping'
    )
    parser.add_argument(
        '--year',
        type=int,
        required=True,
        help='Tax year (e.g., 2025) - will fetch prices for December 31st'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Fetch prices but do not update the CSV file'
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

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Updating prices for {date_str}")
    print(f"CSV file: {csv_path}")
    print(f"Securities to update: {len(ISIN_TO_SYMBOL)}")
    print()

    # Fetch all prices
    updated_entries = []
    success_count = 0
    fail_count = 0

    for isin, symbol in ISIN_TO_SYMBOL.items():
        print(f"Fetching {isin} ({symbol})...")
        result = fetch_price_yfinance(symbol, target_date)

        if result:
            price, currency = result
            updated_entries.append({
                'isin': isin,
                'date': date_str,
                'price': str(price),
                'currency': currency
            })
            success_count += 1
        else:
            fail_count += 1
            # Keep existing entry if we have one
            if csv_path.exists():
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row['isin'] == isin and row['date'] == date_str:
                            updated_entries.append(row)
                            print(f"  → Keeping existing entry")
                            break

    print()
    print(f"Summary: {success_count} updated, {fail_count} failed")

    # Write updated CSV
    if not args.dry_run:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['isin', 'date', 'price', 'currency'])
            writer.writeheader()
            writer.writerows(updated_entries)
        print(f"✓ Updated {csv_path}")
    else:
        print(f"[DRY RUN] Would update {csv_path}")
        print()
        print("Preview of changes:")
        for entry in updated_entries:
            print(f"  {entry['isin']}: {entry['price']} {entry['currency']}")


if __name__ == '__main__':
    main()
