from datetime import date
from pathlib import Path

from opensteuerauszug.util.gui_command_builder import (
    GuiRunConfig,
    build_cli_command,
    suggested_output_paths,
    validate_gui_run_config,
)


def test_cli_command_contains_required_flags_for_ibkr(tmp_path: Path):
    input_file = tmp_path / "ibkr.xml"
    input_file.write_text("<xml/>")
    output_pdf = tmp_path / "result.pdf"

    config = GuiRunConfig(
        input_path=input_file,
        importer="ibkr",
        tax_year=2025,
        tax_calculation_level="fillin",
        output_pdf=output_pdf,
    )

    command = build_cli_command(config, python_executable="python3")

    assert command[0] == "python3"
    assert "opensteuerauszug.steuerauszug" in command
    assert "--importer" in command
    assert "--tax-year" in command
    assert "--output" in command
    assert command[-1] == str(input_file)


def test_cli_command_includes_optional_overrides_when_set(tmp_path: Path):
    input_file = tmp_path / "ibkr.xml"
    input_file.write_text("<xml/>")
    output_pdf = tmp_path / "result.pdf"
    output_xml = tmp_path / "result.xml"
    config_path = tmp_path / "config.toml"
    kursliste_dir = tmp_path / "kursliste"
    kursliste_dir.mkdir()

    config = GuiRunConfig(
        input_path=input_file,
        importer="ibkr",
        tax_year=2025,
        tax_calculation_level="kursliste",
        output_pdf=output_pdf,
        output_xml=output_xml,
        institution_name="LYNX B.V.",
        config_path=config_path,
        kursliste_dir=kursliste_dir,
        period_from=date(2025, 1, 1),
        period_to=date(2025, 12, 31),
        strict_consistency=False,
        filter_to_period=False,
    )

    command = build_cli_command(config)

    assert "--xml-output" in command
    assert "--institution-name" in command
    assert "--config" in command
    assert "--kursliste-dir" in command
    assert "--period-from" in command
    assert "--period-to" in command
    assert "--no-strict-consistency" in command
    assert "--no-filter-to-period" in command
    assert "--log-level" in command


def test_validation_rejects_non_file_input_for_ibkr(tmp_path: Path):
    input_dir = tmp_path / "input_dir"
    input_dir.mkdir()
    output_pdf = tmp_path / "result.pdf"

    config = GuiRunConfig(
        input_path=input_dir,
        importer="ibkr",
        tax_year=2025,
        tax_calculation_level="fillin",
        output_pdf=output_pdf,
    )

    errors = validate_gui_run_config(config)

    assert errors
    assert "IBKR importer requires an input XML file." in errors


def test_validation_requires_output_pdf_path(tmp_path: Path):
    input_file = tmp_path / "ibkr.xml"
    input_file.write_text("<xml/>")

    config = GuiRunConfig(
        input_path=input_file,
        importer="ibkr",
        tax_year=2025,
        tax_calculation_level="fillin",
        output_pdf=Path(""),
    )

    errors = validate_gui_run_config(config)

    assert "Output PDF path is required when render phase is selected." in errors


def test_cli_command_includes_full_expert_options(tmp_path: Path):
    input_file = tmp_path / "raw.xml"
    input_file.write_text("<xml/>")

    config = GuiRunConfig(
        input_path=input_file,
        importer="none",
        tax_year=2025,
        tax_calculation_level="none",
        output_pdf=Path(""),
        phases=["validate", "verify"],
        debug_dump=tmp_path / "debug",
        raw_import=True,
        identifiers_csv_path=tmp_path / "identifiers.csv",
        log_level="DEBUG",
        broker="ibkr",
        set_overrides=["general.canton=ZH", "calculate.keep_existing_payments=true"],
        org_nr="12345",
    )

    command = build_cli_command(config, python_executable="python3")

    assert "--output" not in command
    assert "--raw-import" in command
    assert "--phases" in command
    assert "--debug-dump" in command
    assert "--identifiers-csv-path" in command
    assert "--log-level" in command
    assert "--broker" in command
    assert command.count("--set") == 2
    assert "--org-nr" in command


def test_validation_allows_missing_output_for_raw_import_without_render(tmp_path: Path):
    input_file = tmp_path / "input.xml"
    input_file.write_text("<xml/>")

    config = GuiRunConfig(
        input_path=input_file,
        importer="none",
        tax_year=2025,
        tax_calculation_level="none",
        output_pdf=Path(""),
        raw_import=True,
    )

    errors = validate_gui_run_config(config)

    assert "Output PDF path is required when render phase is selected." not in errors


def test_validation_rejects_empty_custom_phase_selection(tmp_path: Path):
    input_file = tmp_path / "input.xml"
    input_file.write_text("<xml/>")

    config = GuiRunConfig(
        input_path=input_file,
        importer="ibkr",
        tax_year=2025,
        tax_calculation_level="fillin",
        output_pdf=tmp_path / "out.pdf",
        phases=[],
    )

    errors = validate_gui_run_config(config)

    assert "At least one phase must be selected when custom phases are enabled." in errors


def test_suggested_output_paths_include_tax_year_prefix():
    output_pdf, output_xml = suggested_output_paths(Path("data/My Statement.xml"), 2025)

    assert output_pdf == Path("out/2025_My_Statement.pdf")
    assert output_xml == Path("out/2025_My_Statement.xml")
