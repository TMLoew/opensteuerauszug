# GUI Development Handoff

## Purpose
Build a cross-platform GUI for OpenSteuerAuszug so non-technical users can generate Swiss tax statements without using the terminal.

## Project Context
OpenSteuerAuszug generates Swiss tax statements (Steuerauszug) in eCH-0196 XML/PDF format from broker exports.

- Main CLI entry point: `src/opensteuerauszug/steuerauszug.py`
- Config example: `config.toml.example`
- Input/reference data: `data/`
- Typical outputs: `out/`

## Current Backend State (Completed)

### 1) CLI institution-name override
A new `--institution-name` option is available and has higher priority than config values.

Usage example:

```bash
.venv/bin/python -m opensteuerauszug.steuerauszug main \
  --importer ibkr \
  --institution-name "LYNX B.V." \
  --tax-year 2024 \
  data/2024_Lynx.xml
```

### 2) Automatic price extraction from IBKR XML
Year-end prices are extracted automatically from IBKR `OpenPosition` entries:

- Price derivation: `positionValue / position`
- Automatically saved to `data/manual_prices_YYYY.csv`
- Only extracted for securities with non-zero year-end positions
- Short positions are supported (negative balances)

### 3) Year-specific manual price files
Price lookup supports year-specific files with fallback:

1. `data/manual_prices_YYYY.csv`
2. `data/manual_prices.csv` (fallback)

### 4) Improved bilingual warning messages
Critical warnings in PDF now clearly distinguish:

- Securities with manual prices applied (marked with `*`)
- Securities with zero year-end position (no price required)

Warnings include English and German text.

### 5) Bug fixes included
- Empty `dateTime` handling: malformed IBKR transactions are skipped
- Missing `buySell` handling: inferred from quantity sign
- Withholding tax on interest: `WHTAX` transaction support
- Short positions: negative balances handled correctly

## GUI Requirements

### Goal
Provide a one-click workflow to generate tax statements.

### Technology preference
Do not use Tkinter.

Recommended options:
- PyQt6/PySide6 (desktop, native feel)
- Streamlit (web-style local app)
- Electron + Python backend
- Gradio

## Functional Requirements

### Input section
- Input XML file picker
- Broker selector (`ibkr`, `schwab`)
- Tax year input (default: current year - 1)
- Optional institution-name override

### Output section
- Output PDF path picker (save dialog)
- Output XML path picker (save dialog)

### Advanced options
- Tax calculation level selector:
  - `fillin` (full with manual prices)
  - `kursliste` (kursliste only)
  - Optional exposure of other CLI-supported values (`none`, `minimal`)

### Execution
- `Generate` button runs the CLI command
- Real-time streamed logs in UI
- Clear success/error state
- Option to open generated PDF after success

## CLI Contract for GUI
The GUI should build commands equivalent to:

```bash
.venv/bin/python -m opensteuerauszug.steuerauszug main \
  --importer ibkr \
  --tax-calculation-level fillin \
  --output out/output.pdf \
  --xml-output out/output.xml \
  --institution-name "LYNX B.V." \
  --period-from 2024-01-01 \
  --period-to 2024-12-31 \
  data/2024_Lynx.xml
```

Also valid: using `--tax-year` when appropriate instead of explicit period dates.

## CLI Options to Expose

| Option | Type | Notes |
| --- | --- | --- |
| `--importer` | choice | `ibkr`, `schwab` |
| `--tax-calculation-level` | choice | `none`, `minimal`, `kursliste`, `fillin` |
| `--tax-year` | int | Convenience for period defaults |
| `--institution-name` | string | Optional override |
| `--output` | path | PDF output path |
| `--xml-output` | path | XML output path |
| `input_file` | path | Positional input XML file |

## UX Goals
- Simple: non-technical users can complete generation without terminal use
- Informative: show progress and meaningful errors
- Validated: check file existence, year range, required fields before run
- Helpful defaults: tax year = previous year, auto-suggest output paths
- Cross-platform: macOS, Windows, Linux

## Acceptance Criteria
- User can select input file and generate outputs without terminal interaction
- Real-time log streaming is visible during generation
- Success and error states are explicit and actionable
- User can open the generated PDF from the GUI
- All required CLI options are accessible in the GUI

## Notes for GUI Scope
Automatic backend features do not need dedicated controls:

- IBKR price extraction
- Year-specific manual price file selection/fallback
- Manual price application for missing Kursliste securities

These should be explained as automatic behavior in the GUI help text.
