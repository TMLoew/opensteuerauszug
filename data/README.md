# Data Directory

This directory contains sensitive tax and financial data files that should **NEVER** be committed to version control.

## Files (NOT in git)

### `manual_prices.csv`
Contains manually-entered prices for securities not in the official Kursliste.

**Format:**
```csv
isin,date,price,currency
US88160R1014,2025-12-31,350.25,USD
```

**To create:** Copy `manual_prices.csv.example` to `manual_prices.csv` and add your securities.

**Auto-update:** Use the scripts in `scripts/` directory:
```bash
# See scripts/README.md for detailed instructions
.venv/bin/python scripts/update_all_manual_prices.py --year 2025
```

### `security_identifiers.csv`
Maps ISINs to Swiss Valor numbers for securities in your portfolio.

**Format:**
```csv
isin,valorNumber
US88160R1014,11448182
```

**To create:** Copy `security_identifiers.csv.example` to `security_identifiers.csv` and add your mappings.

### `*.xml` (Your broker statements)
XML files exported from your broker (e.g., IBKR Flex Query, Schwab statements).

**IMPORTANT:** These contain your complete trading history and should NEVER be committed to git.

## Files (IN git)

### `kursliste/`
Downloaded official Swiss tax valuation lists (Kursliste) from ESTV.

**Note:** Only the README is tracked. Downloaded SQLite databases are in `.gitignore`.

## Security Notice

⚠️ **All personal financial data files are protected by `.gitignore`**

Never commit files containing:
- Your broker account numbers
- Your trading history
- Your portfolio holdings
- Your personal information
- Tax values or calculations

If you accidentally commit sensitive data, immediately:
1. Remove the file: `git rm --cached filename`
2. Commit the removal
3. Consider the data compromised if already pushed to a remote repository
