from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDate, QEvent, QProcess, QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDropEvent, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
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
from .performance_tab import PerformanceTab


class OpenSteuerAuszugWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenSteuerAuszug")
        self._process: Optional[QProcess] = None
        self._manual_pdf_output = False
        self._manual_xml_output = False
        self._settings = QSettings("OpenSteuerAuszug", "OpenSteuerAuszug")
        self._recent_files: list[str] = []
        self._load_recent_files()
        self._restore_window_state()
        self._build_ui()
        self._setup_menu_bar()
        self._setup_shortcuts()
        self._wire_events()
        self._apply_defaults()
        self._update_command_preview()
        self.setAcceptDrops(True)

    def _apply_native_styling(self) -> None:
        """Apply native macOS styling with dark mode support."""
        # Use system palette for automatic dark mode support
        app = QApplication.instance()
        if app:
            app.setStyle("Fusion")  # Fusion style works better with custom palettes

        # Detect if dark mode is active
        palette = self.palette()
        is_dark = palette.color(QPalette.Window).lightness() < 128

        # Native macOS-style stylesheet that adapts to system theme
        stylesheet = """
            QMainWindow {
                background-color: palette(window);
            }
            QWidget {
                font-family: ".AppleSystemUIFont", "Helvetica Neue", sans-serif;
                font-size: 13px;
                color: palette(text);
            }
            QLabel {
                padding-right: 8px;
            }
            #heroTitle {
                font-size: 28px;
                font-weight: 600;
                color: palette(text);
                padding: 8px 0 4px 0;
                letter-spacing: -0.5px;
            }
            #heroSubtitle {
                font-size: 13px;
                color: palette(mid);
                padding: 0 0 16px 0;
                line-height: 1.5;
            }
            QGroupBox {
                border: 1px solid palette(mid);
                border-radius: 10px;
                margin-top: 16px;
                padding-top: 20px;
                font-weight: 600;
                background: palette(base);
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                top: 0px;
                padding: 2px 8px;
                background: palette(window);
                color: palette(text);
            }
            QPushButton {
                border: 1px solid palette(mid);
                border-radius: 6px;
                background: palette(button);
                padding: 7px 16px;
                min-width: 100px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: palette(light);
                border-color: palette(dark);
            }
            QPushButton:pressed {
                background: palette(mid);
            }
            QPushButton:disabled {
                color: palette(mid);
                border-color: palette(midlight);
            }
            QPushButton#generateButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #34c759, stop:1 #30b350);
                color: white;
                border: 1px solid #2ea043;
                font-weight: 600;
                min-height: 36px;
                font-size: 14px;
            }
            QPushButton#generateButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #30b350, stop:1 #2ea043);
            }
            QPushButton#generateButton:pressed {
                background: #2ea043;
            }
            QPushButton#cancelButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #ff3b30, stop:1 #e6352b);
                color: white;
                border: 1px solid #d92b21;
            }
            QPushButton#cancelButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #e6352b, stop:1 #d92b21);
            }
            QLineEdit, QComboBox, QSpinBox, QDateEdit {
                border: 1px solid palette(mid);
                border-radius: 6px;
                background: palette(base);
                padding: 6px 10px;
                selection-background-color: #007aff;
                selection-color: white;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {
                border: 2px solid #007aff;
                padding: 5px 9px;
            }
            QPlainTextEdit {
                font-family: "Monaco", "Menlo", "Consolas", monospace;
                font-size: 11px;
                border: 1px solid palette(mid);
                border-radius: 6px;
                background: palette(base);
                padding: 8px;
                selection-background-color: #007aff;
                selection-color: white;
            }
            QPlainTextEdit#commandPreview {
                font-size: 10px;
                min-height: 60px;
            }
            QPlainTextEdit#logOutput {
                min-height: 200px;
            }
            QCheckBox {
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid palette(mid);
                background: palette(base);
            }
            QCheckBox::indicator:checked {
                background: #007aff;
                border-color: #007aff;
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iOSIgdmlld0JveD0iMCAwIDEyIDkiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik0xIDQuNUw0LjUgOEwxMSAxIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgo8L3N2Zz4K);
            }
            #statusLabel {
                font-weight: 600;
                font-size: 13px;
                padding: 6px 0;
            }
            #statusLabel[status="ready"] {
                color: palette(mid);
            }
            #statusLabel[status="running"] {
                color: #34c759;
            }
            #statusLabel[status="success"] {
                color: #34c759;
            }
            #statusLabel[status="error"] {
                color: #ff3b30;
            }
            #progressBar {
                border: none;
                background: palette(midlight);
                border-radius: 2px;
                min-height: 4px;
                max-height: 4px;
            }
            #progressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #34c759, stop:1 #30b350);
                border-radius: 2px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAiIGhlaWdodD0iNiIgdmlld0JveD0iMCAwIDEwIDYiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik0xIDFMNSA1TDkgMSIgc3Ryb2tlPSIjODg4ODg4IiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgo8L3N2Zz4K);
            }
            QMenuBar {
                background: transparent;
                border: none;
            }
            QMenuBar::item {
                padding: 4px 10px;
                background: transparent;
            }
            QMenuBar::item:selected {
                background: palette(highlight);
                color: palette(highlighted-text);
            }
            QMenu {
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #007aff;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background: palette(mid);
                margin: 4px 8px;
            }
            QScrollBar:vertical {
                border: none;
                background: palette(base);
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: palette(mid);
                min-height: 30px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: palette(dark);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                border: none;
                background: palette(base);
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: palette(mid);
                min-width: 30px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal:hover {
                background: palette(dark);
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QTabWidget::pane {
                border: 1px solid palette(mid);
                border-radius: 8px;
                background: palette(window);
            }
            QTabBar::tab {
                background: palette(button);
                color: palette(text);
                border: 1px solid palette(mid);
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 6px 20px;
                margin-right: 2px;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background: palette(window);
                font-weight: 600;
            }
            QTabBar::tab:hover:!selected {
                background: palette(light);
            }
            QTableWidget {
                border: 1px solid palette(mid);
                border-radius: 6px;
                gridline-color: palette(mid);
                background: palette(base);
                alternate-background-color: palette(window);
            }
            QHeaderView::section {
                background: palette(button);
                color: palette(text);
                border: none;
                border-right: 1px solid palette(mid);
                border-bottom: 1px solid palette(mid);
                padding: 4px 8px;
                font-weight: 600;
                font-size: 12px;
            }
        """
        self.setStyleSheet(stylesheet)

    def _build_ui(self) -> None:
        # Top-level tab widget
        tabs = QTabWidget(self)
        self.setCentralWidget(tabs)

        # ── Tab 1: Generator (existing UI) ──────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.NoFrame)

        # Create content widget
        root = QWidget()
        scroll.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header with icon and title
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        title = QLabel("Swiss Tax Statement Generator")
        title.setObjectName("heroTitle")
        subtitle = QLabel(
            "One-click generation from broker exports. Prices are automatically extracted from your data."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroSubtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

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
        layout.addWidget(self._build_log_group())
        layout.addStretch()  # Add stretch at bottom to push content up

        tabs.addTab(scroll, "Generator")

        # ── Tab 2: Performance ──────────────────────────────────────────
        self._performance_tab = PerformanceTab(self)
        tabs.addTab(self._performance_tab, "Performance")

        self._apply_native_styling()

    def _build_input_group(self) -> QGroupBox:
        group = QGroupBox("Input")
        grid = QGridLayout(group)
        grid.setColumnMinimumWidth(0, 200)  # Ensure labels have enough space
        grid.setColumnStretch(1, 1)

        self.input_path_edit = QLineEdit()
        self.input_path_edit.setToolTip("Select your broker statement file (XML for IBKR, directory for Schwab)")
        self.input_browse_btn = QPushButton("Browse...")
        self.input_browse_btn.setToolTip("Browse for input file or directory")

        self.importer_combo = QComboBox()
        self.importer_combo.addItem("Interactive Brokers (IBKR)", "ibkr")
        self.importer_combo.addItem("Charles Schwab", "schwab")
        self.importer_combo.addItem("None (raw/advanced workflows)", "none")
        self.importer_combo.setToolTip("Select your broker type - prices are automatically extracted from IBKR statements")

        self.tax_year_spin = QSpinBox()
        self.tax_year_spin.setRange(1900, 2200)
        self.tax_year_spin.setToolTip("The tax year for which to generate the statement (usually last year)")

        self.tax_calc_combo = QComboBox()
        self.tax_calc_combo.addItem("Full (fill missing via manual prices)", "fillin")
        self.tax_calc_combo.addItem("Kursliste only", "kursliste")
        self.tax_calc_combo.addItem("Minimal", "minimal")
        self.tax_calc_combo.addItem("None", "none")
        self.tax_calc_combo.setToolTip(
            "Full: Use Kursliste + automatic price extraction from broker data (recommended)\n"
            "Kursliste only: Only use official Swiss Kursliste\n"
            "Minimal/None: Basic calculations without exchange rates"
        )

        self.institution_name_edit = QLineEdit()
        self.institution_name_edit.setPlaceholderText("Optional, e.g. LYNX B.V.")
        self.institution_name_edit.setToolTip(
            "Override the institution name in the PDF output.\n"
            "Useful for correcting broker names (e.g., 'LYNX B.V.' instead of 'Interactive Brokers')"
        )

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
        grid.setColumnMinimumWidth(0, 200)  # Ensure labels have enough space
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
        self.command_preview.setObjectName("commandPreview")
        self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumBlockCount(200)
        self.command_preview.setMinimumHeight(60)
        self.command_preview.setMaximumHeight(120)
        self.command_preview.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.command_preview.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.command_preview.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

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
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)

        # Status and progress
        status_row = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("progressBar")
        self.progress_bar.setMaximum(0)  # Indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)

        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)
        layout.addWidget(self.progress_bar)

        # Buttons
        button_row = QHBoxLayout()
        self.generate_btn = QPushButton("Generate Tax Statement")
        self.generate_btn.setObjectName("generateButton")
        self.generate_btn.setToolTip("Generate tax statement from broker data (Ctrl+Return)")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("cancelButton")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setToolTip("Cancel running generation (Esc)")
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.setToolTip("Clear the output log (Ctrl+L)")

        button_row.addWidget(self.generate_btn)
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.clear_log_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)
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
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.log_output.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.log_output.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self.log_output)
        return group

    def _setup_shortcuts(self) -> None:
        """Set up keyboard shortcuts."""
        # Generate: Ctrl+Return
        generate_action = QAction(self)
        generate_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_Return))
        generate_action.triggered.connect(self._run_generation)
        self.addAction(generate_action)

        # Cancel: Escape (when running)
        cancel_action = QAction(self)
        cancel_action.setShortcut(QKeySequence(Qt.Key_Escape))
        cancel_action.triggered.connect(self._cancel_generation)
        self.addAction(cancel_action)

        # Clear log: Ctrl+L
        clear_log_action = QAction(self)
        clear_log_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_L))
        clear_log_action.triggered.connect(self.log_output.clear)
        self.addAction(clear_log_action)

        # Expert mode toggle: Ctrl+E
        expert_action = QAction(self)
        expert_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_E))
        expert_action.triggered.connect(lambda: self.expert_mode_checkbox.setChecked(
            not self.expert_mode_checkbox.isChecked()
        ))
        self.addAction(expert_action)

    def _setup_menu_bar(self) -> None:
        """Set up native macOS menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")

        # Open action
        open_action = QAction("Open...", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._browse_input)
        file_menu.addAction(open_action)

        # Recent files submenu
        self.recent_menu = QMenu("Open Recent", self)
        self._update_recent_menu()
        file_menu.addMenu(self.recent_menu)

        file_menu.addSeparator()

        # Close action
        close_action = QAction("Close Window", self)
        close_action.setShortcut(QKeySequence.Close)
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

        # View menu
        view_menu = menubar.addMenu("View")

        # Expert mode toggle
        expert_action = QAction("Expert Mode", self)
        expert_action.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_E))
        expert_action.setCheckable(True)
        expert_action.triggered.connect(lambda checked: self.expert_mode_checkbox.setChecked(checked))
        view_menu.addAction(expert_action)
        self.expert_menu_action = expert_action

        # Help menu
        help_menu = menubar.addMenu("Help")

        # Documentation
        docs_action = QAction("Documentation", self)
        docs_action.triggered.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://github.com/anthropics/opensteuerauszug")
        ))
        help_menu.addAction(docs_action)

    def _load_recent_files(self) -> None:
        """Load recent files from settings."""
        self._recent_files = self._settings.value("recent_files", [], type=list)[:10]  # Keep last 10

    def _save_recent_file(self, file_path: str) -> None:
        """Add file to recent files list."""
        if file_path in self._recent_files:
            self._recent_files.remove(file_path)
        self._recent_files.insert(0, file_path)
        self._recent_files = self._recent_files[:10]  # Keep only 10 most recent
        self._settings.setValue("recent_files", self._recent_files)
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        """Update the recent files menu."""
        if not hasattr(self, 'recent_menu'):
            return

        self.recent_menu.clear()
        if not self._recent_files:
            action = QAction("No Recent Files", self)
            action.setEnabled(False)
            self.recent_menu.addAction(action)
            return

        for file_path in self._recent_files:
            if Path(file_path).exists():
                action = QAction(Path(file_path).name, self)
                action.setData(file_path)
                action.triggered.connect(lambda checked=False, f=file_path: self._open_recent_file(f))
                self.recent_menu.addAction(action)

        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent Files", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def _open_recent_file(self, file_path: str) -> None:
        """Open a file from recent files."""
        if Path(file_path).exists():
            self.input_path_edit.setText(file_path)
        else:
            QMessageBox.warning(self, "File Not Found", f"The file no longer exists:\n{file_path}")
            self._recent_files.remove(file_path)
            self._settings.setValue("recent_files", self._recent_files)
            self._update_recent_menu()

    def _clear_recent_files(self) -> None:
        """Clear recent files list."""
        self._recent_files = []
        self._settings.setValue("recent_files", self._recent_files)
        self._update_recent_menu()

    def _restore_window_state(self) -> None:
        """Restore window size and position from settings."""
        geometry = self._settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1100, 800)

        # Set minimum window size to prevent text cutoff
        self.setMinimumWidth(900)

    def _save_window_state(self) -> None:
        """Save window size and position to settings."""
        self._settings.setValue("window_geometry", self.saveGeometry())

    def closeEvent(self, event) -> None:
        """Handle window close event."""
        self._save_window_state()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        """Handle application state changes including theme changes."""
        super().changeEvent(event)
        # Note: Qt/PySide6 doesn't reliably support dynamic theme switching without crashes
        # The app will respect the system theme when launched, but requires restart to update
        # This is common behavior for many Qt applications on macOS

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Handle drag enter event for file drops."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle drop event for file drops."""
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path:
                self.input_path_edit.setText(file_path)
                self._save_recent_file(file_path)
                event.acceptProposedAction()

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
                self._save_recent_file(selected)
        elif importer == "none":
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select input file",
                "",
                "All Files (*)",
            )
            if selected:
                self.input_path_edit.setText(selected)
                self._save_recent_file(selected)
        else:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select IBKR XML file",
                "",
                "XML Files (*.xml);;All Files (*)",
            )
            if selected:
                self.input_path_edit.setText(selected)
                self._save_recent_file(selected)

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
        self._update_status("Running generation...", "running")
        self.progress_bar.setVisible(True)

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
        self.progress_bar.setVisible(False)

        success = exit_status == QProcess.NormalExit and exit_code == 0
        if success:
            self._update_status("✓ Generation completed successfully", "success")
            self.log_output.appendPlainText("\n[GUI] Generation finished successfully.\n")
            output_pdf = self.output_pdf_edit.text().strip()
            if self.open_pdf_checkbox.isChecked() and output_pdf and Path(output_pdf).exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(output_pdf).resolve())))
            QMessageBox.information(self, "Success", "Tax statement generated successfully!")
        else:
            self._update_status("✗ Generation failed", "error")
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

        self._update_status("Cancelling...", "error")
        self.log_output.appendPlainText("\n[GUI] Cancelling run...\n")
        self._process.terminate()
        if not self._process.waitForFinished(2000):
            self._process.kill()
            self._process.waitForFinished(1000)
        self.progress_bar.setVisible(False)
        self._update_status("Cancelled", "ready")

    def _update_status(self, message: str, status: str = "ready") -> None:
        """Update the status label with message and status color.

        Args:
            message: Status message to display
            status: Status type - "ready", "running", "success", "error"
        """
        self.status_label.setText(message)
        self.status_label.setProperty("status", status)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

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
