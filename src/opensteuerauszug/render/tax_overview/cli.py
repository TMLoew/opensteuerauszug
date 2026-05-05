"""Typer subcommand for the tax-overview mode.

Registered by ``opensteuerauszug.steuerauszug`` via ``app.command(...)`` so the
tax_overview package stays importable without the main CLI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .writer import TaxOverviewRequest, parse_formats, write_tax_overview


def tax_overview_command(
    input_path: Path = typer.Option(
        ..., "--input", "-i", exists=True, file_okay=True, dir_okay=False,
        readable=True, help="Broker statement file (IBKR Flex XML or Schwab CSV/PDF)."
    ),
    broker: str = typer.Option(
        ..., "--broker",
        help="Broker name: 'ibkr' or 'schwab'. Must match the statement format.",
    ),
    tax_year: int = typer.Option(
        ..., "--year", help="Steuerperiode (e.g. 2025)."
    ),
    output_dir: Path = typer.Option(
        Path("./out"), "--output-dir", "-o", file_okay=False, dir_okay=True,
        help="Directory where tax_overview_<year>.{xlsx,html,pdf} are written."
    ),
    formats: Optional[str] = typer.Option(
        None, "--formats",
        help="Comma-separated list of output formats. Default: xlsx,html,pdf."
    ),
    preparer_mode: bool = typer.Option(
        False, "--preparer-mode",
        help="Include hidden KS36 self-check sheets. NEVER share this workbook "
             "with third parties. Omit for a clean third-party export.",
    ),
    prior_year_input: Optional[Path] = typer.Option(
        None, "--prior-year-input",
        exists=True, file_okay=True, dir_okay=False, readable=True,
        help="Prior-year broker statement; its Kursliste-derived closing "
             "values become the current-year opening (2023 Schluss = 2024 Eröffnung).",
    ),
) -> None:
    """Generate a tax-authority-friendly overview workbook for Kanton SG filing."""
    try:
        parsed_formats = parse_formats(formats)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--formats") from exc

    broker_norm = broker.strip().lower()
    if broker_norm not in {"ibkr", "schwab"}:
        raise typer.BadParameter(
            f"unknown broker '{broker}'. Expected 'ibkr' or 'schwab'.",
            param_hint="--broker",
        )

    request = TaxOverviewRequest(
        input_path=input_path,
        broker=broker_norm,
        tax_year=tax_year,
        output_dir=output_dir,
        formats=parsed_formats,
        preparer_mode=preparer_mode,
        prior_year_input_path=prior_year_input,
    )
    produced = write_tax_overview(request)
    for path in produced:
        typer.echo(f"wrote {path}")
