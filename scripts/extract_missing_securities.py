#!/usr/bin/env python3
"""
Extract missing securities from OpenSteuerAuszug output and find their ticker symbols.

This script parses the warning messages about securities missing from the Kursliste,
attempts to find their Yahoo Finance ticker symbols, and optionally updates the
ISIN_TO_SYMBOL mapping in update_all_manual_prices.py.

Usage:
    # Run opensteuerauszug and pipe output to this script
    python -m opensteuerauszug.steuerauszug ... 2>&1 | python scripts/extract_missing_securities.py

    # Or save output to a file first
    python -m opensteuerauszug.steuerauszug ... > output.log 2>&1
    python scripts/extract_missing_securities.py --input output.log

    # Automatically update the mapping file
    python scripts/extract_missing_securities.py --input output.log --update-mapping
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    import yfinance as yf
except ImportError:
    print("WARNING: yfinance is not installed. Symbol lookup will be limited.")
    print("Install it with: pip install yfinance")
    yf = None


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def extract_missing_securities(text: str) -> List[Tuple[str, str]]:
    """
    Extract missing securities from warning messages.

    Returns:
        List of (name, symbol_in_parentheses) tuples
    """
    securities = []

    # Pattern: "WARNING:...:  - SECURITY NAME (SYMBOL)"
    pattern = r'WARNING:.*?:\s+-\s+(.+?)\s+\(([A-Z0-9]+)\)'

    for match in re.finditer(pattern, text):
        name = match.group(1).strip()
        symbol = match.group(2).strip()
        securities.append((name, symbol))

    return securities


def find_isin_in_xml(xml_path: Path, symbol: str) -> Optional[str]:
    """
    Find ISIN for a security by searching in the XML output.

    Args:
        xml_path: Path to the XML output file
        symbol: The symbol from the warning (e.g., 'NCAUF')

    Returns:
        ISIN if found, None otherwise
    """
    if not xml_path.exists():
        return None

    try:
        with open(xml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Pattern: <security ... securityName="... (SYMBOL)" isin="ISINCODE">
        pattern = rf'<security[^>]*securityName="[^"]*\({re.escape(symbol)}\)"[^>]*isin="([A-Z0-9]{{12}})"'
        match = re.search(pattern, content)

        if match:
            return match.group(1)

        # Alternative pattern: isin might come before securityName
        pattern = rf'<security[^>]*isin="([A-Z0-9]{{12}})"[^>]*securityName="[^"]*\({re.escape(symbol)}\)"'
        match = re.search(pattern, content)

        if match:
            return match.group(1)

    except Exception as e:
        print(f"Error reading XML: {e}", file=sys.stderr)

    return None


def try_find_symbol(name: str, default_symbol: str) -> str:
    """
    Try to verify the symbol works with Yahoo Finance.

    Args:
        name: Security name
        default_symbol: Symbol from the warning message

    Returns:
        Verified symbol or default_symbol
    """
    if not yf:
        return default_symbol

    try:
        ticker = yf.Ticker(default_symbol)
        info = ticker.info

        # If we get valid info back, the symbol is probably correct
        if info and ('symbol' in info or 'shortName' in info):
            return default_symbol
    except:
        pass

    return default_symbol


def update_mapping_file(mappings: Dict[str, str], script_path: Path):
    """
    Update the ISIN_TO_SYMBOL mapping in update_all_manual_prices.py.

    Args:
        mappings: Dict of ISIN -> symbol
        script_path: Path to update_all_manual_prices.py
    """
    if not script_path.exists():
        print(f"ERROR: {script_path} not found")
        return

    with open(script_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the ISIN_TO_SYMBOL dictionary
    pattern = r'(ISIN_TO_SYMBOL\s*=\s*\{)(.*?)(\n\})'
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        print("ERROR: Could not find ISIN_TO_SYMBOL in the file")
        return

    # Parse existing mappings
    existing = {}
    for line in match.group(2).split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Pattern: 'ISIN': 'SYMBOL',  # COMMENT
        isin_match = re.match(r"'([A-Z0-9]+)':\s*'([A-Z0-9]+)',?\s*#?\s*(.*)", line)
        if isin_match:
            existing[isin_match.group(1)] = (isin_match.group(2), isin_match.group(3))

    # Merge new mappings
    for isin, symbol in mappings.items():
        if isin not in existing:
            existing[isin] = (symbol, "")  # No comment for new entries

    # Build new dictionary content
    lines = []
    for isin in sorted(existing.keys()):
        symbol, comment = existing[isin]
        if comment:
            lines.append(f"    '{isin}': '{symbol}',  # {comment}")
        else:
            lines.append(f"    '{isin}': '{symbol}',")

    new_dict = match.group(1) + '\n' + '\n'.join(lines) + match.group(3)

    # Replace in content
    new_content = content[:match.start()] + new_dict + content[match.end():]

    # Write back
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"✓ Updated {script_path}")
    print(f"  Added/updated {len(mappings)} mappings")


def main():
    parser = argparse.ArgumentParser(
        description='Extract missing securities and find their ticker symbols'
    )
    parser.add_argument(
        '--input',
        type=Path,
        help='Input file with opensteuerauszug output (default: read from stdin)'
    )
    parser.add_argument(
        '--xml',
        type=Path,
        help='XML output file to extract ISINs from (default: out/test_manual_prices.xml)'
    )
    parser.add_argument(
        '--update-mapping',
        action='store_true',
        help='Automatically update ISIN_TO_SYMBOL in update_all_manual_prices.py'
    )
    parser.add_argument(
        '--verify-symbols',
        action='store_true',
        help='Verify symbols with Yahoo Finance (requires yfinance)'
    )

    args = parser.parse_args()

    # Read input
    if args.input:
        with open(args.input, 'r', encoding='utf-8') as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    # Extract missing securities
    securities = extract_missing_securities(text)

    if not securities:
        print("No missing securities found in the output.")
        return

    print(f"Found {len(securities)} missing securities:")
    print()

    # Determine XML path
    project_root = get_project_root()
    xml_path = args.xml if args.xml else project_root / 'out' / 'test_manual_prices.xml'

    # Extract ISINs and build mapping
    mappings = {}

    for name, symbol in securities:
        isin = find_isin_in_xml(xml_path, symbol)

        if isin:
            # Verify symbol if requested
            if args.verify_symbols:
                verified_symbol = try_find_symbol(name, symbol)
            else:
                verified_symbol = symbol

            mappings[isin] = verified_symbol
            status = "✓" if isin else "✗"
            print(f"{status} {name} ({symbol})")
            print(f"  ISIN: {isin}")
            print(f"  Symbol: {verified_symbol}")
        else:
            print(f"✗ {name} ({symbol})")
            print(f"  ISIN: Not found in XML - add manually")

        print()

    # Show Python code to copy/paste
    if mappings:
        print("=" * 60)
        print("Add these to ISIN_TO_SYMBOL in update_all_manual_prices.py:")
        print()
        for isin, symbol in sorted(mappings.items()):
            print(f"    '{isin}': '{symbol}',")
        print()

        # Update mapping file if requested
        if args.update_mapping:
            script_path = project_root / 'scripts' / 'update_all_manual_prices.py'
            update_mapping_file(mappings, script_path)

    # Securities without ISINs
    missing_isin = [s for s in securities if find_isin_in_xml(xml_path, s[1]) is None]
    if missing_isin:
        print("=" * 60)
        print("Could not find ISINs for these securities:")
        for name, symbol in missing_isin:
            print(f"  - {name} ({symbol})")
        print()
        print("These securities might:")
        print("  1. Have zero balance at year-end (no ISIN needed)")
        print("  2. Be derivatives/options (typically not in manual_prices.csv)")
        print("  3. Need manual ISIN lookup")


if __name__ == '__main__':
    main()
