from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDate, QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .gui_command_builder import (
    GuiRunConfig,
    build_cli_command,
    format_cli_command,
    suggested_output_paths,
    validate_gui_run_config,
)


class OpenSteuerAuszugWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenSteuerAuszug")
        self.resize(1080, 760)
        self._process: Optional[QProcess] = None
        self._manual_pdf_output = False
        self._manual_xml_output = False
        self._build_ui()
        self._wire_events()
        self._apply_defaults()
        self._update_command_preview()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Swiss Tax Statement Generator")
        title.setObjectName("heroTitle")
        subtitle = QLabel(
            "One-click generation from broker exports. Automatic price extraction and year-specific "
            "manual prices are applied in the backend."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        mode_row = QHBoxLayout()
        self.expert_mode_checkbox = QCheckBox("Expert mode")
        self.expert_mode_checkbox.setToolTip("Show full CLI options including advanced and expert flags")
        mode_row.addWidget(self.expert_mode_checkbox)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        layout.addWidget(self._build_input_group())
        layout.addWidget(self._build_output_group())
        self.advanced_group = self._build_advanced_group()
        self.expert_group = self._build_expert_group()
        layout.addWidget(self.advanced_group)
        layout.addWidget(self.expert_group)
        layout.addWidget(self._build_execution_group())
        layout.addWidget(self._build_log_group(), stretch=1)

        self.setStyleSheet(
            """
            QWidget {
                background: #f7f6f2;
                color: #1f2a37;
                font-family: "Avenir Next", "Segoe UI", "Helvetica Neue", sans-serif;
                font-size: 13px;
            }
            #heroTitle {
                font-size: 26px;
                font-weight: 700;
                color: #0f1724;
                padding: 2px 0 0 0;
            }
            #heroSubtitle {
                color: #465569;
                padding: 0 0 8px 0;
            }
            QGroupBox {
                border: 1px solid #d7dde6;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 12px;
                font-weight: 600;
                background: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                top: -6px;
                padding: 0 4px;
                color: #1c3a4d;
                background: #f7f6f2;
            }
            QPushButton {
                border: 1px solid #b8c5d3;
                border-radius: 6px;
                background: #ecf0f5;
                padding: 6px 12px;
                min-width: 96px;
            }
            QPushButton:hover {
                background: #dde7f1;
            }
            QPushButton#generateButton {
                background: #1e7d4f;
                color: #ffffff;
                border: 1px solid #19663f;
                font-weight: 600;
            }
            QPushButton#generateButton:hover {
                background: #19663f;
            }
            QPushButton#cancelButton {
                background: #a9412b;
                color: #ffffff;
                border: 1px solid #8d3724;
            }
            QLineEdit, QComboBox, QSpinBox, QDateEdit, QPlainTextEdit {
                border: 1px solid #c5cfdb;
                border-radius: 5px;
                background: #ffffff;
                padding: 5px 8px;
            }
            QPlainTextEdit {
                font-family: "Menlo", "Consolas", monospace;
                font-size: 12px;
            }
            """
        )

    def _build_input_group(self) -> QGroupBox:
        group = QGroupBox("Input")
        grid = QGridLayout(group)
        grid.setColumnStretch(1, 1)

        self.input_path_edit = QLineEdit()
        self.input_browse_btn = QPushButton("Browse...")
        self.importer_combo = QComboBox()
        self.importer_combo.addItem("Interactive Brokers (IBKR)", "ibkr")
        self.importer_combo.addItem("Charles Schwab", "schwab")
        self.importer_combo.addItem("None (raw/advanced workflows)", "none")
        self.tax_year_spin = QSpinBox()
        self.tax_year_spin.setRange(1900, 2200)
        self.tax_calc_combo = QComboBox()
        self.tax_calc_combo.addItem("Full (fill missing via manual prices)", "fillin")
        self.tax_calc_combo.addItem("Kursliste only", "kursliste")
        self.tax_calc_combo.addItem("Minimal", "minimal")
        self.tax_calc_combo.addItem("None", "none")
        self.institution_name_edit = QLineEdit()
        self.institution_name_edit.setPlaceholderText("Optional, e.g. LYNX B.V.")

        grid.addWidget(QLabel("Input file/directory"), 0, 0)
        grid.addWidget(self.input_path_edit, 0, 1)
        grid.addWidget(self.input_browse_btn, 0, 2)
        grid.addWidget(QLabel("Broker importer"), 1, 0)
        grid.addWidget(self.importer_combo, 1, 1)
        grid.addWidget(QLabel("Tax year"), 2, 0)
        grid.addWidget(self.tax_year_spin, 2, 1)
        grid.addWidget(QLabel("Tax calculation level"), 3, 0)
        grid.addWidget(self.tax_calc_combo, 3, 1)
        grid.addWidget(QLabel("Institution name override"), 4, 0)
        grid.addWidget(self.institution_name_edit, 4, 1, 1, 2)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("Output")
        grid = QGridLayout(group)
        grid.setColumnStretch(1, 1)

        self.output_pdf_edit = QLineEdit()
        self.output_pdf_browse_btn = QPushButton("Save PDF...")
        self.output_xml_edit = QLineEdit()
        self.output_xml_browse_btn = QPushButton("Save XML...")
        self.open_pdf_checkbox = QCheckBox("Open PDF after successful generation")
        self.open_pdf_checkbox.setChecked(True)

        grid.addWidget(QLabel("Output PDF"), 0, 0)
        grid.addWidget(self.output_pdf_edit, 0, 1)
        grid.addWidget(self.output_pdf_browse_btn, 0, 2)
        grid.addWidget(QLabel("Output XML"), 1, 0)
        grid.addWidget(self.output_xml_edit, 1, 1)
        grid.addWidget(self.output_xml_browse_btn, 1, 2)
        grid.addWidget(self.open_pdf_checkbox, 2, 1, 1, 2)
        return group

    def _build_advanced_group(self) -> QGroupBox:
        group = QGroupBox("Advanced")
        form = QFormLayout(group)

        self.config_edit = QLineEdit("config.toml")
        self.config_browse_btn = QPushButton("Browse...")
        config_layout = QHBoxLayout()
        config_layout.addWidget(self.config_edit)
        config_layout.addWidget(self.config_browse_btn)

        self.kursliste_edit = QLineEdit("data/kursliste")
        self.kursliste_browse_btn = QPushButton("Browse...")
        kursliste_layout = QHBoxLayout()
        kursliste_layout.addWidget(self.kursliste_edit)
        kursliste_layout.addWidget(self.kursliste_browse_btn)

        self.period_from_edit = QDateEdit()
        self.period_from_edit.setCalendarPopup(True)
        self.period_to_edit = QDateEdit()
        self.period_to_edit.setCalendarPopup(True)
        self.use_explicit_period_checkbox = QCheckBox("Use explicit period dates instead of tax-year defaults")
        period_layout = QHBoxLayout()
        period_layout.addWidget(QLabel("From"))
        period_layout.addWidget(self.period_from_edit)
        period_layout.addWidget(QLabel("To"))
        period_layout.addWidget(self.period_to_edit)
        period_layout.addStretch(1)

        self.strict_consistency_checkbox = QCheckBox("Strict consistency checks")
        self.strict_consistency_checkbox.setChecked(True)
        self.filter_to_period_checkbox = QCheckBox("Filter events to tax period")
        self.filter_to_period_checkbox.setChecked(True)

        self.command_preview = QPlainTextEdit()
        self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumBlockCount(200)
        self.command_preview.setFixedHeight(80)

        form.addRow("Config file", config_layout)
        form.addRow("Kursliste directory", kursliste_layout)
        form.addRow(self.use_explicit_period_checkbox)
        form.addRow("Period", period_layout)
        form.addRow(self.strict_consistency_checkbox)
        form.addRow(self.filter_to_period_checkbox)
        form.addRow("Command preview", self.command_preview)
        return group

    def _build_execution_group(self) -> QGroupBox:
        group = QGroupBox("Execution")
        row = QHBoxLayout(group)
        row.setContentsMargins(8, 8, 8, 8)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setObjectName("generateButton")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancelButton")
        self.cancel_btn.setEnabled(False)
        self.clear_log_btn = QPushButton("Clear log")

        row.addWidget(self.generate_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.clear_log_btn)
        row.addStretch(1)
        return group

    def _build_expert_group(self) -> QGroupBox:
        group = QGroupBox("Expert Options")
        form = QFormLayout(group)

        self.raw_import_checkbox = QCheckBox("Raw import mode (--raw-import)")

        self.use_custom_phases_checkbox = QCheckBox("Use custom phases")
        phases_row = QHBoxLayout()
        self.phase_import_cb = QCheckBox("import")
        self.phase_validate_cb = QCheckBox("validate")
        self.phase_verify_cb = QCheckBox("verify")
        self.phase_calculate_cb = QCheckBox("calculate")
        self.phase_render_cb = QCheckBox("render")
        phases_row.addWidget(self.phase_import_cb)
        phases_row.addWidget(self.phase_validate_cb)
        phases_row.addWidget(self.phase_verify_cb)
        phases_row.addWidget(self.phase_calculate_cb)
        phases_row.addWidget(self.phase_render_cb)
        phases_row.addStretch(1)

        self.debug_dump_edit = QLineEdit()
        self.debug_dump_browse_btn = QPushButton("Browse...")
        debug_dump_row = QHBoxLayout()
        debug_dump_row.addWidget(self.debug_dump_edit)
        debug_dump_row.addWidget(self.debug_dump_browse_btn)

        self.identifiers_csv_edit = QLineEdit()
        self.identifiers_csv_browse_btn = QPushButton("Browse...")
        identifiers_row = QHBoxLayout()
        identifiers_row.addWidget(self.identifiers_csv_edit)
        identifiers_row.addWidget(self.identifiers_csv_browse_btn)

        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level_combo.setCurrentText("INFO")

        self.broker_edit = QLineEdit()
        self.broker_edit.setPlaceholderText("Optional broker name from config")

        self.org_nr_edit = QLineEdit()
        self.org_nr_edit.setPlaceholderText("Optional 5-digit barcode org number")

        self.set_overrides_edit = QPlainTextEdit()
        self.set_overrides_edit.setPlaceholderText("One override per line, e.g. general.canton=ZH")
        self.set_overrides_edit.setFixedHeight(70)

        form.addRow(self.raw_import_checkbox)
        form.addRow(self.use_custom_phases_checkbox)
        form.addRow("Phases", phases_row)
        form.addRow("Debug dump directory", debug_dump_row)
        form.addRow("Identifiers CSV path", identifiers_row)
        form.addRow("Log level", self.log_level_combo)
        form.addRow("Broker override", self.broker_edit)
        form.addRow("Barcode org number", self.org_nr_edit)
        form.addRow("--set overrides", self.set_overrides_edit)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Run Log")
        layout = QVBoxLayout(group)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.log_output)
        return group

    def _wire_events(self) -> None:
        self.input_browse_btn.clicked.connect(self._browse_input)
        self.output_pdf_browse_btn.clicked.connect(self._browse_output_pdf)
        self.output_xml_browse_btn.clicked.connect(self._browse_output_xml)
        self.expert_mode_checkbox.toggled.connect(self._update_mode_visibility)
        self.config_browse_btn.clicked.connect(self._browse_config)
        self.kursliste_browse_btn.clicked.connect(self._browse_kursliste_dir)
        self.debug_dump_browse_btn.clicked.connect(self._browse_debug_dump_dir)
        self.identifiers_csv_browse_btn.clicked.connect(self._browse_identifiers_csv)
        self.generate_btn.clicked.connect(self._run_generation)
        self.cancel_btn.clicked.connect(self._cancel_generation)
        self.clear_log_btn.clicked.connect(self.log_output.clear)

        self.importer_combo.currentIndexChanged.connect(self._on_inputs_changed)
        self.tax_year_spin.valueChanged.connect(self._on_inputs_changed)
        self.tax_calc_combo.currentIndexChanged.connect(self._update_command_preview)
        self.institution_name_edit.textChanged.connect(self._update_command_preview)
        self.config_edit.textChanged.connect(self._update_command_preview)
        self.kursliste_edit.textChanged.connect(self._update_command_preview)
        self.input_path_edit.textChanged.connect(self._on_inputs_changed)
        self.output_pdf_edit.textChanged.connect(self._update_command_preview)
        self.output_xml_edit.textChanged.connect(self._update_command_preview)
        self.use_explicit_period_checkbox.toggled.connect(self._update_period_enabled_state)
        self.use_explicit_period_checkbox.toggled.connect(self._update_command_preview)
        self.period_from_edit.dateChanged.connect(self._update_command_preview)
        self.period_to_edit.dateChanged.connect(self._update_command_preview)
        self.strict_consistency_checkbox.toggled.connect(self._update_command_preview)
        self.filter_to_period_checkbox.toggled.connect(self._update_command_preview)
        self.raw_import_checkbox.toggled.connect(self._update_command_preview)
        self.use_custom_phases_checkbox.toggled.connect(self._update_phases_enabled_state)
        self.use_custom_phases_checkbox.toggled.connect(self._update_command_preview)
        self.phase_import_cb.toggled.connect(self._update_command_preview)
        self.phase_validate_cb.toggled.connect(self._update_command_preview)
        self.phase_verify_cb.toggled.connect(self._update_command_preview)
        self.phase_calculate_cb.toggled.connect(self._update_command_preview)
        self.phase_render_cb.toggled.connect(self._update_command_preview)
        self.debug_dump_edit.textChanged.connect(self._update_command_preview)
        self.identifiers_csv_edit.textChanged.connect(self._update_command_preview)
        self.log_level_combo.currentIndexChanged.connect(self._update_command_preview)
        self.broker_edit.textChanged.connect(self._update_command_preview)
        self.org_nr_edit.textChanged.connect(self._update_command_preview)
        self.set_overrides_edit.textChanged.connect(self._update_command_preview)

        self.output_pdf_edit.textEdited.connect(self._mark_pdf_manual)
        self.output_xml_edit.textEdited.connect(self._mark_xml_manual)

    def _apply_defaults(self) -> None:
        today = date.today()
        default_year = today.year - 1
        self.tax_year_spin.setValue(default_year)
        self.period_from_edit.setDate(QDate(default_year, 1, 1))
        self.period_to_edit.setDate(QDate(default_year, 12, 31))
        self._update_period_enabled_state()
        self._update_phases_enabled_state()
        self._update_mode_visibility()

    def _update_period_enabled_state(self) -> None:
        enabled = self.use_explicit_period_checkbox.isChecked()
        self.period_from_edit.setEnabled(enabled)
        self.period_to_edit.setEnabled(enabled)

    def _update_mode_visibility(self) -> None:
        expert_mode = self.expert_mode_checkbox.isChecked()
        self.advanced_group.setVisible(expert_mode)
        self.expert_group.setVisible(expert_mode)

    def _update_phases_enabled_state(self) -> None:
        enabled = self.use_custom_phases_checkbox.isChecked()
        self.phase_import_cb.setEnabled(enabled)
        self.phase_validate_cb.setEnabled(enabled)
        self.phase_verify_cb.setEnabled(enabled)
        self.phase_calculate_cb.setEnabled(enabled)
        self.phase_render_cb.setEnabled(enabled)

    def _on_inputs_changed(self) -> None:
        self._autofill_outputs()
        self._update_command_preview()

    def _mark_pdf_manual(self, _: str) -> None:
        self._manual_pdf_output = True

    def _mark_xml_manual(self, _: str) -> None:
        self._manual_xml_output = True

    def _autofill_outputs(self) -> None:
        input_text = self.input_path_edit.text().strip()
        if not input_text:
            return

        input_path = Path(input_text)
        output_pdf, output_xml = suggested_output_paths(input_path, self.tax_year_spin.value())
        if not self._manual_pdf_output:
            self.output_pdf_edit.setText(str(output_pdf))
        if not self._manual_xml_output:
            self.output_xml_edit.setText(str(output_xml))

    def _current_importer(self) -> str:
        return str(self.importer_combo.currentData())

    def _current_tax_level(self) -> str:
        return str(self.tax_calc_combo.currentData())

    def _browse_input(self) -> None:
        importer = self._current_importer()
        if importer == "schwab":
            selected = QFileDialog.getExistingDirectory(self, "Select Schwab input directory")
            if selected:
                self.input_path_edit.setText(selected)
        elif importer == "none":
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select input file",
                "",
                "All Files (*)",
            )
            if selected:
                self.input_path_edit.setText(selected)
        else:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select IBKR XML file",
                "",
                "XML Files (*.xml);;All Files (*)",
            )
            if selected:
                self.input_path_edit.setText(selected)

    def _browse_output_pdf(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self, "Save output PDF", self.output_pdf_edit.text().strip(), "PDF Files (*.pdf)"
        )
        if selected:
            self._manual_pdf_output = True
            self.output_pdf_edit.setText(selected)

    def _browse_output_xml(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self, "Save output XML", self.output_xml_edit.text().strip(), "XML Files (*.xml)"
        )
        if selected:
            self._manual_xml_output = True
            self.output_xml_edit.setText(selected)

    def _browse_config(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select config file",
            self.config_edit.text().strip() or "config.toml",
            "TOML Files (*.toml);;All Files (*)",
        )
        if selected:
            self.config_edit.setText(selected)

    def _browse_kursliste_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Select Kursliste directory", self.kursliste_edit.text().strip()
        )
        if selected:
            self.kursliste_edit.setText(selected)

    def _browse_debug_dump_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Select debug dump directory", self.debug_dump_edit.text().strip()
        )
        if selected:
            self.debug_dump_edit.setText(selected)

    def _browse_identifiers_csv(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select identifiers CSV",
            self.identifiers_csv_edit.text().strip(),
            "CSV Files (*.csv);;All Files (*)",
        )
        if selected:
            self.identifiers_csv_edit.setText(selected)

    def _selected_phases(self) -> Optional[list[str]]:
        if not self.use_custom_phases_checkbox.isChecked():
            return None

        selected: list[str] = []
        if self.phase_import_cb.isChecked():
            selected.append("import")
        if self.phase_validate_cb.isChecked():
            selected.append("validate")
        if self.phase_verify_cb.isChecked():
            selected.append("verify")
        if self.phase_calculate_cb.isChecked():
            selected.append("calculate")
        if self.phase_render_cb.isChecked():
            selected.append("render")
        return selected

    def _set_overrides(self) -> Optional[list[str]]:
        lines = [line.strip() for line in self.set_overrides_edit.toPlainText().splitlines()]
        values = [line for line in lines if line]
        return values or None

    def _build_run_config(self) -> GuiRunConfig:
        input_text = self.input_path_edit.text().strip()
        output_pdf_text = self.output_pdf_edit.text().strip()
        output_xml_text = self.output_xml_edit.text().strip()
        config_text = self.config_edit.text().strip()
        kursliste_text = self.kursliste_edit.text().strip()
        institution_text = self.institution_name_edit.text().strip()
        debug_dump_text = self.debug_dump_edit.text().strip()
        identifiers_csv_text = self.identifiers_csv_edit.text().strip()
        broker_text = self.broker_edit.text().strip()
        org_nr_text = self.org_nr_edit.text().strip()

        period_from = None
        period_to = None
        if self.use_explicit_period_checkbox.isChecked():
            period_from_qt = self.period_from_edit.date()
            period_to_qt = self.period_to_edit.date()
            period_from = date(period_from_qt.year(), period_from_qt.month(), period_from_qt.day())
            period_to = date(period_to_qt.year(), period_to_qt.month(), period_to_qt.day())

        return GuiRunConfig(
            input_path=Path(input_text) if input_text else Path(""),
            importer=self._current_importer(),
            tax_year=self.tax_year_spin.value(),
            tax_calculation_level=self._current_tax_level(),
            output_pdf=Path(output_pdf_text) if output_pdf_text else Path(""),
            output_xml=Path(output_xml_text) if output_xml_text else None,
            institution_name=institution_text or None,
            config_path=Path(config_text) if config_text else None,
            kursliste_dir=Path(kursliste_text) if kursliste_text else None,
            period_from=period_from,
            period_to=period_to,
            strict_consistency=self.strict_consistency_checkbox.isChecked(),
            filter_to_period=self.filter_to_period_checkbox.isChecked(),
            phases=self._selected_phases(),
            debug_dump=Path(debug_dump_text) if debug_dump_text else None,
            raw_import=self.raw_import_checkbox.isChecked(),
            identifiers_csv_path=Path(identifiers_csv_text) if identifiers_csv_text else None,
            log_level=self.log_level_combo.currentText(),
            broker=broker_text or None,
            set_overrides=self._set_overrides(),
            org_nr=org_nr_text or None,
        )

    def _update_command_preview(self) -> None:
        try:
            run_config = self._build_run_config()
            command = build_cli_command(run_config, python_executable=sys.executable)
            self.command_preview.setPlainText(format_cli_command(command))
        except Exception:
            self.command_preview.setPlainText("")

    def _run_generation(self) -> None:
        if self._process and self._process.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Already running", "A generation process is already running.")
            return

        run_config = self._build_run_config()
        errors = validate_gui_run_config(run_config)
        if errors:
            QMessageBox.warning(self, "Input validation failed", "\n".join(errors))
            return

        selected_phases = run_config.phases
        render_selected = selected_phases is None or "render" in selected_phases
        if render_selected:
            run_config.output_pdf.parent.mkdir(parents=True, exist_ok=True)
        if run_config.output_xml:
            run_config.output_xml.parent.mkdir(parents=True, exist_ok=True)

        command = build_cli_command(run_config, python_executable=sys.executable)
        self.command_preview.setPlainText(format_cli_command(command))
        self.log_output.clear()
        self.log_output.appendPlainText("Starting OpenSteuerAuszug...\n")
        self.log_output.appendPlainText(f"$ {format_cli_command(command)}\n")

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self._drain_process_output)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)
        process.start(command[0], command[1:])

        if not process.waitForStarted(2500):
            QMessageBox.critical(
                self,
                "Failed to start",
                "Could not start the CLI process. Verify your Python environment.",
            )
            return

        self._process = process
        self._set_running(True)

    def _drain_process_output(self) -> None:
        if not self._process:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if chunk:
            self.log_output.insertPlainText(chunk)
            self.log_output.ensureCursorVisible()

    def _on_process_error(self, process_error: QProcess.ProcessError) -> None:
        self.log_output.appendPlainText(f"\n[GUI] Process error: {process_error}\n")

    def _on_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._drain_process_output()
        self._set_running(False)

        success = exit_status == QProcess.NormalExit and exit_code == 0
        if success:
            self.log_output.appendPlainText("\n[GUI] Generation finished successfully.\n")
            output_pdf = self.output_pdf_edit.text().strip()
            if self.open_pdf_checkbox.isChecked() and output_pdf and Path(output_pdf).exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(output_pdf).resolve())))
            QMessageBox.information(self, "Success", "Tax statement generated successfully.")
        else:
            self.log_output.appendPlainText(
                f"\n[GUI] Generation failed (exit code {exit_code}, status {int(exit_status)}).\n"
            )
            QMessageBox.warning(
                self,
                "Generation failed",
                f"The CLI process exited with code {exit_code}. Check the run log for details.",
            )

    def _cancel_generation(self) -> None:
        if not self._process or self._process.state() == QProcess.NotRunning:
            return

        self.log_output.appendPlainText("\n[GUI] Cancelling run...\n")
        self._process.terminate()
        if not self._process.waitForFinished(2000):
            self._process.kill()
            self._process.waitForFinished(1000)

    def _set_running(self, running: bool) -> None:
        self.expert_mode_checkbox.setEnabled(not running)
        self.generate_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.input_browse_btn.setEnabled(not running)
        self.output_pdf_browse_btn.setEnabled(not running)
        self.output_xml_browse_btn.setEnabled(not running)
        self.config_browse_btn.setEnabled(not running)
        self.kursliste_browse_btn.setEnabled(not running)
        self.debug_dump_browse_btn.setEnabled(not running)
        self.identifiers_csv_browse_btn.setEnabled(not running)


def launch_gui() -> int:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("OpenSteuerAuszug")
    window = OpenSteuerAuszugWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(launch_gui())
