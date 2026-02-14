# OpenSteuerAuszug - Quick Usage Guide

## Prerequisites

**IMPORTANT:** Always use the virtual environment Python!

```bash
# Activate virtual environment (or use .venv/bin/python directly)
source .venv/bin/activate

# OR use .venv/bin/python for each command
.venv/bin/python -m opensteuerauszug.steuerauszug --help
```

## Getting Help

```bash
# Show main help (list of commands)
.venv/bin/python -m opensteuerauszug.steuerauszug --help

# Show comprehensive help guide
.venv/bin/python -m opensteuerauszug.steuerauszug info

# Show detailed options for main command
.venv/bin/python -m opensteuerauszug.steuerauszug main --help
```

## Basic Usage

### Generate Tax Statement (IBKR)

```bash
.venv/bin/python -m opensteuerauszug.steuerauszug main \
  --importer ibkr \
  --output out/steuerauszug.pdf \
  --xml-output out/steuerauszug.xml \
  --period-from 2025-01-01 \
  --period-to 2025-12-31 \
  data/ibkr_statement.xml
```

### Generate Tax Statement (Schwab)

```bash
.venv/bin/python -m opensteuerauszug.steuerauszug main \
  --importer schwab \
  --output out/steuerauszug.pdf \
  --xml-output out/steuerauszug.xml \
  data/schwab_directory/
```

## Kursliste Setup

### 1. Download Kursliste

Download from ESTV website:
- https://www.estv.admin.ch/estv/de/home/verrechnungssteuer/dienstleistungen/wertschriftenliste.html

Save to: `data/kursliste/kursliste_2025.xml`

### 2. Convert to SQLite (Fast Lookups)

```bash
.venv/bin/python scripts/convert_kursliste_to_sqlite.py \
  data/kursliste/kursliste_2025.xml \
  data/kursliste/kursliste_2025.sqlite
```

**Example Output:**
```
Conversion complete:
  Shares: 15234
  Bonds: 8921
  Funds: 3456
  Exchange Rates (daily): 12567
  Signs: 245
  DA1 Rates: 189
```

The tool automatically uses `.sqlite` files if available (much faster than XML).

## Manual Prices (for missing securities)

**Good News:** Prices are **automatically extracted** from your IBKR XML! The system extracts all year-end prices from `OpenPosition` data and saves them to year-specific files (e.g., `data/manual_prices_2024.csv`). These prices are automatically applied to securities missing from the Kursliste and marked with an asterisk (*) in the PDF.

### Automatic Price Extraction (IBKR)

**Just run the main command - prices are extracted automatically!**

```bash
.venv/bin/python -m opensteuerauszug.steuerauszug main \
  --importer ibkr \
  --tax-calculation-level fillin \
  --tax-year 2024 \
  data/2024_statement.xml
```

The importer automatically:
1. ✓ Extracts all year-end prices from `OpenPosition` entries
2. ✓ Saves them to `data/manual_prices_2024.csv`
3. ✓ Applies them during tax calculation
4. ✓ Marks them with (*) in the PDF

No manual intervention needed!

### Manual Price Override (Optional)

If you need to override or add prices manually:

1. **Edit the year-specific CSV file:**
   ```bash
   # Edit data/manual_prices_2025.csv
   isin,date,price,currency
   US88160R1014,2025-12-31,350.25,USD
   ```

2. **Or use the extraction script:**
   ```bash
   .venv/bin/python scripts/extract_prices_from_ibkr.py data/2025_statement.xml --year 2025
   ```

3. **Or fetch with Yahoo Finance:**
   ```bash
   .venv/bin/python scripts/update_all_manual_prices.py --year 2025
   ```

### File Organization

Manual prices are organized by tax year:
- `data/manual_prices_2024.csv` - Prices for tax year 2024
- `data/manual_prices_2025.csv` - Prices for tax year 2025
- `data/manual_prices.csv` - Generic fallback (used if year-specific file not found)

The system automatically selects the correct file when you specify `--tax-year` or `--period-to`.

## Configuration

Edit `config.toml`:

```toml
[general]
canton = "SG"
full_name = "Your Name"
institution_name = "LYNX B.V."  # Override broker name in PDF

[general.processing_flags]
detect_foreign_income = true

[overrides]
# Override Kursliste flags for specific securities
# HK0101000591 = "Z"  # Example: Hong Kong stock
```

## Key Options

| Option | Description |
|--------|-------------|
| `--importer ibkr\|schwab` | Broker type |
| `--output FILE` | Output PDF path |
| `--xml-output FILE` | Output XML path (optional) |
| `--period-from DATE` | Start date (YYYY-MM-DD) |
| `--period-to DATE` | End date (YYYY-MM-DD) |
| `--tax-calculation-level` | `none\|minimal\|kursliste\|fillin` (default: kursliste) |
| `--config FILE` | Config file (default: config.toml) |
| `--kursliste-dir DIR` | Kursliste directory (default: data/kursliste) |

## Calculation Levels

- **`none`**: No tax calculations (import only)
- **`minimal`**: Basic calculations without Kursliste
- **`kursliste`**: Use official Kursliste for prices and exchange rates (recommended)
- **`fillin`**: Kursliste + manual prices for missing securities

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `convert_kursliste_to_sqlite.py` | Convert Kursliste XML → SQLite |
| `fetch_prices_yfinance.py` | Fetch single security price |
| `update_all_manual_prices.py` | Batch update manual prices |
| `extract_missing_securities.py` | Extract missing securities from warnings |
| `update_prices_workflow.sh` | Complete automation workflow |

## Examples

### Full workflow with manual prices

```bash
# 1. First run (will show warnings)
.venv/bin/python -m opensteuerauszug.steuerauszug main \
  --importer ibkr \
  --tax-calculation-level fillin \
  --output out/draft.pdf \
  --period-from 2025-01-01 \
  --period-to 2025-12-31 \
  data/ibkr_statement.xml

# 2. Auto-update manual prices
bash scripts/update_prices_workflow.sh 2025

# 3. Final PDF (clean, no warnings)
.venv/bin/python -m opensteuerauszug.steuerauszug main \
  --importer ibkr \
  --tax-calculation-level fillin \
  --output out/final.pdf \
  --xml-output out/final.xml \
  --period-from 2025-01-01 \
  --period-to 2025-12-31 \
  data/ibkr_statement.xml
```

### Override institution name

```bash
# In config.toml
institution_name = "LYNX B.V."

# Generate PDF (will show "LYNX B.V." instead of "Interactive Brokers LLC")
.venv/bin/python -m opensteuerauszug.steuerauszug main ...
```

## Troubleshooting

### "Missing Kursliste entries" warnings

**Solution:** Add manual prices or request ESTV to add securities to Kursliste

1. Run with `--tax-calculation-level fillin`
2. Use `scripts/update_all_manual_prices.py` to fetch prices
3. Manual prices are marked with * in PDF

### Kursliste not found

**Solution:** Download and convert Kursliste:
```bash
# 1. Download from ESTV
# 2. Convert to SQLite
.venv/bin/python scripts/convert_kursliste_to_sqlite.py \
  data/kursliste/kursliste_2025.xml \
  data/kursliste/kursliste_2025.sqlite
```

### Permission denied / File not found

**Solution:** Check paths are correct relative to project root
```bash
# Run from project root directory
cd /path/to/opensteuerauszug
.venv/bin/python -m opensteuerauszug.steuerauszug ...
```

## More Information

- **Full documentation:** See `README.md`
- **Comprehensive help:** `.venv/bin/python -m opensteuerauszug.steuerauszug info`
- **GitHub:** https://github.com/vroonhof/opensteuerauszug
- **Issues:** https://github.com/vroonhof/opensteuerauszug/issues

---

**Remember:** Always use `.venv/bin/python` instead of system `python` to avoid "ModuleNotFoundError"!
