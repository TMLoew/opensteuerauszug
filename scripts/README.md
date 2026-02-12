# Scripts for OpenSteuerAuszug

This directory contains utility scripts for managing manual price data and other maintenance tasks.

## Manual Price Management

When securities are not available in the official Swiss Kursliste, you can manually specify their end-of-year prices using the `data/manual_prices.csv` file. These scripts help automate fetching prices from Yahoo Finance.

### Prerequisites

Install required dependencies:

```bash
pip install yfinance
```

Or install in the virtual environment:

```bash
.venv/bin/pip install yfinance
```

### Automated Workflow (Recommended)

The easiest way to update all manual prices is to use the extraction script with the update script:

```bash
# Step 1: Run opensteuerauszug and extract missing securities
python -m opensteuerauszug.steuerauszug --importer ibkr --tax-calculation-level fillin \
  --output out/output.pdf --xml-output out/output.xml \
  --period-from 2025-01-01 --period-to 2025-12-31 \
  data/your_file.xml 2>&1 | python scripts/extract_missing_securities.py --update-mapping

# Step 2: Fetch all prices
python scripts/update_all_manual_prices.py --year 2025

# Step 3: Regenerate with updated prices
python -m opensteuerauszug.steuerauszug --importer ibkr --tax-calculation-level fillin \
  --output out/output.pdf --xml-output out/output.xml \
  --period-from 2025-01-01 --period-to 2025-12-31 \
  data/your_file.xml
```

### extract_missing_securities.py

**New!** Automatically extracts securities missing from the Kursliste and finds their ISINs and ticker symbols.

#### Usage

```bash
# Extract and display missing securities (reads from stdin)
python -m opensteuerauszug.steuerauszug ... 2>&1 | python scripts/extract_missing_securities.py

# Or save output first, then extract
python -m opensteuerauszug.steuerauszug ... > output.log 2>&1
python scripts/extract_missing_securities.py --input output.log

# Automatically update the ISIN_TO_SYMBOL mapping
python scripts/extract_missing_securities.py --input output.log --update-mapping

# Verify symbols with Yahoo Finance
python scripts/extract_missing_securities.py --input output.log --verify-symbols
```

The script:
1. Parses warning messages about missing Kursliste entries
2. Extracts ISINs from the XML output
3. Matches them with ticker symbols from the warnings
4. Optionally updates `update_all_manual_prices.py` automatically

### update_all_manual_prices.py

**Recommended approach** - Updates all securities with a predefined ISIN-to-symbol mapping.

#### Usage

```bash
# Dry run to preview changes
python scripts/update_all_manual_prices.py --year 2025 --dry-run

# Actually update the CSV
python scripts/update_all_manual_prices.py --year 2025
```

#### Adding New Securities

You can either:
1. Use `extract_missing_securities.py --update-mapping` (recommended)
2. Manually edit the `ISIN_TO_SYMBOL` dictionary in `update_all_manual_prices.py`:

```python
ISIN_TO_SYMBOL = {
    'CA65118M1032': 'NCAUF',      # NEWCORE GOLD LTD
    'US45783Q1004': 'NOTV',       # INOTIV INC
    'US64131A1051': 'STIM',       # NEURONETICS INC
    'US02080L1026': 'TKNO',       # ALPHA TEKNOVA INC
    'US30068X1037': 'XGN',        # EXAGEN INC
    # Add your securities here
    'US88160R1014': 'TSLA',       # TESLA INC
}
```

### fetch_prices_yfinance.py

Lower-level script for updating individual securities or exploring prices.

#### Usage

```bash
# Show current manual prices
python scripts/fetch_prices_yfinance.py --year 2025

# Update a specific security
python scripts/fetch_prices_yfinance.py --year 2025 --isin US88160R1014 --symbol TSLA

# Use custom CSV path
python scripts/fetch_prices_yfinance.py --year 2025 --isin US88160R1014 --symbol TSLA --csv my_prices.csv
```

## Finding Ticker Symbols

To find the Yahoo Finance ticker symbol for a security:

1. Go to https://finance.yahoo.com
2. Search for the security by name or ISIN
3. The symbol appears in the URL: `https://finance.yahoo.com/quote/TSLA`

For OTC/Pink Sheet securities (common for small-cap stocks):
- US securities often have a 5-letter symbol ending in 'F' (e.g., NCAUF, NOTV)
- Check the company's investor relations page
- Search on Yahoo Finance by company name

## How Manual Prices Work

1. The `ManualPriceProvider` reads prices from `data/manual_prices.csv`
2. During tax calculation, if a security is not in the Kursliste, the manual price is used
3. Manual prices are marked in the XML with `name="Manual price (not from official Kursliste)"`
4. The PDF includes notices in German and English about manually-set prices

## CSV Format

The `manual_prices.csv` file has the following format:

```csv
isin,date,price,currency
CA65118M1032,2025-12-31,0.45,USD
US45783Q1004,2025-12-31,0.56,USD
```

- **isin**: The ISIN code of the security
- **date**: The valuation date (typically December 31st of the tax year)
- **price**: The closing price on that date
- **currency**: The currency of the price (will be converted to CHF automatically)

## Notes

- Prices are fetched for the closest available trading date to December 31st
- Yahoo Finance may not have data for weekends/holidays - the script uses the last available trading day
- The currency is automatically detected from Yahoo Finance (usually USD for US securities)
- Prices are rounded to 2 decimal places
- If fetching fails, existing entries are preserved
