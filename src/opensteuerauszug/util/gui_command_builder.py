from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


VALID_IMPORTERS = {"ibkr", "schwab", "none"}
VALID_TAX_LEVELS = {"none", "minimal", "kursliste", "fillin"}
VALID_PHASES = {"import", "validate", "verify", "calculate", "render"}
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _is_blank_path(path: Path) -> bool:
    return str(path).strip() in {"", "."} or path.name == ""


@dataclass(frozen=True)
class GuiRunConfig:
    input_path: Path
    importer: str
    tax_year: int
    tax_calculation_level: str
    output_pdf: Path
    output_xml: Optional[Path] = None
    institution_name: Optional[str] = None
    config_path: Optional[Path] = None
    kursliste_dir: Optional[Path] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    strict_consistency: bool = True
    filter_to_period: bool = True
    phases: Optional[list[str]] = None
    debug_dump: Optional[Path] = None
    raw_import: bool = False
    identifiers_csv_path: Optional[Path] = None
    log_level: str = "INFO"
    broker: Optional[str] = None
    set_overrides: Optional[list[str]] = None
    org_nr: Optional[str] = None


def validate_gui_run_config(config: GuiRunConfig) -> list[str]:
    errors: list[str] = []

    importer = config.importer.strip().lower()
    tax_level = config.tax_calculation_level.strip().lower()

    if importer not in VALID_IMPORTERS:
        errors.append(f"Unsupported importer '{config.importer}'.")

    if tax_level not in VALID_TAX_LEVELS:
        errors.append(f"Unsupported tax calculation level '{config.tax_calculation_level}'.")

    if config.tax_year < 1900 or config.tax_year > 2200:
        errors.append("Tax year must be between 1900 and 2200.")

    if _is_blank_path(config.input_path):
        errors.append("Input path is required.")
    elif not config.input_path.exists():
        errors.append(f"Input path does not exist: {config.input_path}")

    if importer == "ibkr" and config.input_path.exists() and not config.input_path.is_file():
        errors.append("IBKR importer requires an input XML file.")

    if importer == "schwab" and config.input_path.exists() and not config.input_path.is_dir():
        errors.append("Schwab importer requires an input directory.")

    render_selected = config.phases is None or "render" in config.phases
    if config.raw_import and config.phases is None:
        # Matches CLI behavior: raw-import defaults to no additional phases.
        render_selected = False

    if render_selected and _is_blank_path(config.output_pdf):
        errors.append("Output PDF path is required when render phase is selected.")

    if config.period_from and config.period_to and config.period_from > config.period_to:
        errors.append("Period start must be before or equal to period end.")

    if config.phases is not None and len(config.phases) == 0:
        errors.append("At least one phase must be selected when custom phases are enabled.")

    if config.phases:
        invalid_phases = [phase for phase in config.phases if phase not in VALID_PHASES]
        if invalid_phases:
            errors.append(f"Unsupported phase(s): {', '.join(invalid_phases)}")

    if config.log_level.strip().upper() not in VALID_LOG_LEVELS:
        errors.append(f"Unsupported log level '{config.log_level}'.")

    if config.org_nr is not None and config.org_nr != "":
        if not config.org_nr.isdigit() or len(config.org_nr) != 5:
            errors.append("Organization number must be a 5-digit number.")

    return errors


def build_cli_command(config: GuiRunConfig, python_executable: Optional[str] = None) -> list[str]:
    command = [
        python_executable or sys.executable,
        "-m",
        "opensteuerauszug.steuerauszug",
        "main",
        "--importer",
        config.importer.strip().lower(),
        "--tax-calculation-level",
        config.tax_calculation_level.strip().lower(),
        "--tax-year",
        str(config.tax_year),
    ]

    render_selected = config.phases is None or "render" in config.phases
    if config.raw_import and config.phases is None:
        render_selected = False
    if render_selected or not _is_blank_path(config.output_pdf):
        command.extend(["--output", str(config.output_pdf)])

    if config.output_xml:
        command.extend(["--xml-output", str(config.output_xml)])

    if config.institution_name:
        stripped_name = config.institution_name.strip()
        if stripped_name:
            command.extend(["--institution-name", stripped_name])

    if config.config_path:
        command.extend(["--config", str(config.config_path)])

    if config.kursliste_dir:
        command.extend(["--kursliste-dir", str(config.kursliste_dir)])

    if config.period_from:
        command.extend(["--period-from", config.period_from.isoformat()])

    if config.period_to:
        command.extend(["--period-to", config.period_to.isoformat()])

    if config.phases:
        for phase in config.phases:
            command.extend(["--phases", phase])

    if config.debug_dump:
        command.extend(["--debug-dump", str(config.debug_dump)])

    if config.raw_import:
        command.append("--raw-import")

    if config.identifiers_csv_path:
        command.extend(["--identifiers-csv-path", str(config.identifiers_csv_path)])

    if not config.strict_consistency:
        command.append("--no-strict-consistency")

    if not config.filter_to_period:
        command.append("--no-filter-to-period")

    command.extend(["--log-level", config.log_level.strip().upper()])

    if config.broker:
        stripped_broker = config.broker.strip()
        if stripped_broker:
            command.extend(["--broker", stripped_broker])

    if config.set_overrides:
        for value in config.set_overrides:
            stripped_value = value.strip()
            if stripped_value:
                command.extend(["--set", stripped_value])

    if config.org_nr:
        stripped_org_nr = config.org_nr.strip()
        if stripped_org_nr:
            command.extend(["--org-nr", stripped_org_nr])

    command.append(str(config.input_path))
    return command


def format_cli_command(command: list[str]) -> str:
    return shlex.join(command)


def suggested_output_paths(
    input_path: Path,
    tax_year: int,
    output_dir: Path = Path("out"),
) -> tuple[Path, Path]:
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", input_path.stem).strip("._")
    if not safe_stem:
        safe_stem = "steuerauszug"
    base = f"{tax_year}_{safe_stem}"
    return output_dir / f"{base}.pdf", output_dir / f"{base}.xml"
