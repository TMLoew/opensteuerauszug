# OpenSteuerAuszug GUI Guide

## Launching the GUI

```bash
# Install GUI dependencies (if not already installed)
pip install -e ".[gui]"

# Launch the GUI
python -m opensteuerauszug.util.gui_launcher
```

## Features

### Simple Mode (Default)
Perfect for most users - just fill in:
1. **Input file**: Your broker XML file (IBKR) or directory (Schwab)
2. **Broker**: Select IBKR or Schwab
3. **Tax year**: Usually the previous year (auto-filled)
4. **Institution name** (optional): Override broker name (e.g., "LYNX B.V.")

Click "Generate Tax Statement" and you're done!

### Expert Mode
Toggle with **Ctrl+E** or the checkbox to access:
- Custom period dates
- Kursliste directory selection
- Phase selection (import, validate, calculate, render)
- Debug dump options
- Advanced logging levels
- Configuration overrides

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Ctrl+Return** | Generate tax statement |
| **Escape** | Cancel running generation |
| **Ctrl+L** | Clear output log |
| **Ctrl+E** | Toggle expert mode |

## Visual Indicators

### Status Label
- **Gray "Ready"**: Waiting for input
- **Green "Running generation..."**: Processing
- **Green "✓ Generation completed successfully"**: Success!
- **Red "✗ Generation failed"**: Error occurred
- **Gray "Cancelled"**: User cancelled

### Progress Bar
- Appears during generation
- Indeterminate (animated) progress
- Disappears when complete

## Automatic Features

The GUI automatically:
- ✅ **Extracts prices** from IBKR OpenPosition data
- ✅ **Saves year-specific files** (manual_prices_2024.csv, etc.)
- ✅ **Applies manual prices** to securities missing from Kursliste
- ✅ **Marks manual prices** with asterisks (*) in PDF
- ✅ **Suggests output paths** based on input file
- ✅ **Opens PDF** after successful generation (optional)

## Tooltips

Hover over any field to see helpful information:
- What the field does
- Expected input format
- Tips and recommendations
- Keyboard shortcuts (for buttons)

## Command Preview

In Expert Mode, see the exact CLI command that will be executed in the "Command preview" box. Perfect for:
- Learning the CLI syntax
- Debugging issues
- Creating scripts

## Bilingual Warnings

Generated PDFs include warnings in both English and German:
- Securities with manual prices applied (✓)
- Securities with zero year-end position (no price needed)
- German text in italics with ■ ■ ■ markers

## Troubleshooting

**GUI doesn't launch?**
```bash
pip install -e ".[gui]"  # Install PySide6 dependencies
```

**Generation fails?**
- Check the "Run Log" for detailed error messages
- Verify input file exists and is valid
- Ensure tax year matches your data period

**Need more control?**
- Enable Expert Mode (Ctrl+E)
- Use the CLI directly (see command preview)

## Tips

1. **First time?** Stick to Simple Mode - it has everything you need
2. **Recurring use?** Output paths auto-update based on input file
3. **Multiple years?** The GUI remembers year-specific manual prices
4. **Want to learn CLI?** Check the command preview in Expert Mode
5. **PDF opens automatically?** Uncheck "Open PDF after successful generation" if you prefer not

## Support

For issues or questions:
- Check [USAGE.md](USAGE.md) for detailed documentation
- Report bugs at https://github.com/anthropics/opensteuerauszug/issues
- CLI help: `python -m opensteuerauszug.steuerauszug --help`
