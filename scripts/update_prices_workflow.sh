#!/bin/bash
#
# Complete workflow to update manual prices for OpenSteuerAuszug
#
# This script:
# 1. Runs opensteuerauszug to generate warnings about missing securities
# 2. Extracts ISINs and symbols from the warnings
# 3. Fetches current prices from Yahoo Finance
# 4. Regenerates the tax statement with updated prices
#
# Usage:
#   ./scripts/update_prices_workflow.sh --year 2025 --input data/your_file.xml
#

set -e  # Exit on error

# Default values
YEAR=""
INPUT_FILE=""
IMPORTER="ibkr"
OUTPUT_PDF="out/output.pdf"
OUTPUT_XML="out/output.xml"
TAX_CALC="fillin"
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --year)
      YEAR="$2"
      shift 2
      ;;
    --input)
      INPUT_FILE="$2"
      shift 2
      ;;
    --importer)
      IMPORTER="$2"
      shift 2
      ;;
    --output)
      OUTPUT_PDF="$2"
      shift 2
      ;;
    --xml-output)
      OUTPUT_XML="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help)
      echo "Usage: $0 --year YEAR --input FILE [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --year YEAR            Tax year (required)"
      echo "  --input FILE           Input file (required)"
      echo "  --importer IMPORTER    Importer type (default: ibkr)"
      echo "  --output FILE          Output PDF (default: out/output.pdf)"
      echo "  --xml-output FILE      Output XML (default: out/output.xml)"
      echo "  --dry-run              Preview changes without updating"
      echo "  --help                 Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Validate required arguments
if [ -z "$YEAR" ] || [ -z "$INPUT_FILE" ]; then
  echo "ERROR: --year and --input are required"
  echo "Use --help for usage information"
  exit 1
fi

# Check if input file exists
if [ ! -f "$INPUT_FILE" ]; then
  echo "ERROR: Input file not found: $INPUT_FILE"
  exit 1
fi

# Determine period dates
PERIOD_FROM="${YEAR}-01-01"
PERIOD_TO="${YEAR}-12-31"

echo "========================================"
echo "OpenSteuerAuszug Manual Price Updater"
echo "========================================"
echo ""
echo "Year:        $YEAR"
echo "Input:       $INPUT_FILE"
echo "Importer:    $IMPORTER"
echo "Output PDF:  $OUTPUT_PDF"
echo "Output XML:  $OUTPUT_XML"
echo ""

# Step 1: Run opensteuerauszug and extract missing securities
echo "Step 1/4: Extracting missing securities..."
echo "----------------------------------------"

.venv/bin/python -m opensteuerauszug.steuerauszug \
  --importer "$IMPORTER" \
  --tax-calculation-level "$TAX_CALC" \
  --output "$OUTPUT_PDF" \
  --xml-output "$OUTPUT_XML" \
  --period-from "$PERIOD_FROM" \
  --period-to "$PERIOD_TO" \
  "$INPUT_FILE" 2>&1 | .venv/bin/python scripts/extract_missing_securities.py --update-mapping

echo ""

# Step 2: Fetch prices from Yahoo Finance
echo "Step 2/4: Fetching prices from Yahoo Finance..."
echo "----------------------------------------"

if [ "$DRY_RUN" = true ]; then
  .venv/bin/python scripts/update_all_manual_prices.py --year "$YEAR" --dry-run
  echo ""
  echo "[DRY RUN] Would proceed to regenerate tax statement"
  echo "Run without --dry-run to actually update prices"
  exit 0
else
  .venv/bin/python scripts/update_all_manual_prices.py --year "$YEAR"
fi

echo ""

# Step 3: Regenerate with updated prices
echo "Step 3/4: Regenerating tax statement with updated prices..."
echo "----------------------------------------"

.venv/bin/python -m opensteuerauszug.steuerauszug \
  --importer "$IMPORTER" \
  --tax-calculation-level "$TAX_CALC" \
  --output "$OUTPUT_PDF" \
  --xml-output "$OUTPUT_XML" \
  --period-from "$PERIOD_FROM" \
  --period-to "$PERIOD_TO" \
  "$INPUT_FILE"

echo ""

# Step 4: Summary
echo "Step 4/4: Summary"
echo "----------------------------------------"
echo "✓ Manual prices updated in data/manual_prices.csv"
echo "✓ Tax statement generated:"
echo "  - PDF: $OUTPUT_PDF"
echo "  - XML: $OUTPUT_XML"
echo ""
echo "Review the PDF to verify all prices are correct."
echo "Manual prices are marked with: 'Manual price (not from official Kursliste)'"
