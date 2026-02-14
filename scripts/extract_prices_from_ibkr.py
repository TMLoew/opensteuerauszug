#!/usr/bin/env python3
"""
Extract year-end prices from IBKR XML and create manual_prices CSV.

This script parses the IBKR Flex Query XML and extracts prices from OpenPosition
entries, calculating price = positionValue / position for each security.

Usage:
    python scripts/extract_prices_from_ibkr.py data/2024_Lynx.xml --year 2024
    python scripts/extract_prices_from_ibkr.py data/2024_Lynx.xml --year 2024 --output data/manual_prices_2024.csv
"""

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Dict


def extract_prices_from_ibkr_xml(xml_path: Path, year: int) -> List[Dict[str, str]]:
    """
    Extract year-end prices from IBKR XML.

    Args:
        xml_path: Path to IBKR Flex Query XML file
        year: Tax year (used to construct date as YYYY-12-31)

    Returns:
        List of dicts with keys: isin, date, price, currency
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"ERROR: Failed to parse XML file: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"ERROR: File not found: {xml_path}")
        sys.exit(1)

    # Target date (December 31st of the tax year)
    target_date = f"{year}-12-31"

    prices = []
    skipped = []

    # Find all OpenPosition elements
    for open_pos in root.iter('OpenPosition'):
        isin = open_pos.get('isin', '')
        symbol = open_pos.get('symbol', 'N/A')
        currency = open_pos.get('currency', '')
        position_str = open_pos.get('position', '')
        position_value_str = open_pos.get('positionValue', '')
        report_date = open_pos.get('reportDate', '')

        # Skip if missing required fields
        if not isin or not currency or not position_str or not position_value_str:
            skipped.append(f"{symbol}: Missing required fields (ISIN={isin})")
            continue

        # Skip if not the target report date
        expected_report_date = target_date.replace('-', '')  # Format: YYYYMMDD
        if report_date != expected_report_date:
            continue

        # Skip options (no ISIN)
        if not isin or isin == '':
            skipped.append(f"{symbol}: No ISIN (likely option or derivative)")
            continue

        try:
            position = Decimal(position_str)
            position_value = Decimal(position_value_str)

            # Skip if position is zero
            if position == 0:
                skipped.append(f"{symbol}: Zero position")
                continue

            # Handle negative positions (short sales) - use absolute values for price
            price = abs(position_value / position)

            # Round to reasonable precision (2-4 decimal places depending on price)
            if price < Decimal('1'):
                price = price.quantize(Decimal('0.0001'))  # 4 decimals for penny stocks
            elif price < Decimal('100'):
                price = price.quantize(Decimal('0.01'))    # 2 decimals for normal stocks
            else:
                price = price.quantize(Decimal('0.01'))    # 2 decimals for expensive stocks

            prices.append({
                'isin': isin,
                'date': target_date,
                'price': str(price),
                'currency': currency,
                'symbol': symbol,  # For debugging, not written to CSV
                'position': str(position),  # For debugging
            })

        except (InvalidOperation, ZeroDivisionError) as e:
            skipped.append(f"{symbol}: Invalid numeric data ({e})")
            continue

    return prices, skipped


def main():
    parser = argparse.ArgumentParser(
        description='Extract year-end prices from IBKR XML and create manual_prices CSV'
    )
    parser.add_argument(
        'xml_file',
        type=Path,
        help='Path to IBKR Flex Query XML file'
    )
    parser.add_argument(
        '--year',
        type=int,
        required=True,
        help='Tax year (e.g., 2024)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output CSV file (default: data/manual_prices_YYYY.csv)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be extracted without writing the file'
    )

    args = parser.parse_args()

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        project_root = Path(__file__).parent.parent
        output_path = project_root / 'data' / f'manual_prices_{args.year}.csv'

    print(f"Extracting prices from: {args.xml_file}")
    print(f"Target date: {args.year}-12-31")
    print(f"Output file: {output_path}")
    print()

    # Extract prices
    prices, skipped = extract_prices_from_ibkr_xml(args.xml_file, args.year)

    print(f"Extracted {len(prices)} prices from IBKR XML")
    if skipped:
        print(f"Skipped {len(skipped)} entries:")
        for reason in skipped[:10]:  # Show first 10
            print(f"  - {reason}")
        if len(skipped) > 10:
            print(f"  ... and {len(skipped) - 10} more")
    print()

    if args.dry_run:
        print("[DRY RUN] Preview of extracted prices:")
        print(f"{'Symbol':<10} {'ISIN':<15} {'Price':>10} {'Currency':<5} {'Position':>10}")
        print("-" * 60)
        for p in prices:
            print(f"{p['symbol']:<10} {p['isin']:<15} {p['price']:>10} {p['currency']:<5} {p['position']:>10}")
        print()
        print(f"[DRY RUN] Would write to: {output_path}")
    else:
        # Write to CSV
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['isin', 'date', 'price', 'currency'])
            writer.writeheader()
            for p in prices:
                # Only write the required fields
                writer.writerow({
                    'isin': p['isin'],
                    'date': p['date'],
                    'price': p['price'],
                    'currency': p['currency']
                })
        print(f"✓ Wrote {len(prices)} prices to {output_path}")


if __name__ == '__main__':
    main()
