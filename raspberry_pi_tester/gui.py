from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .diagnostics import MANUAL_TESTS, DiagnosticSuite
from .models import Health, ResultStatus, TestResult, overall_health
from .reporting import make_report, report_text, save_report
from .theme import (
    HEALTH_STATUS,
    STATUS_COLORS,
    BenchProgressBar,
    StatusLabel,
    apply_theme,
    mono_font,
    status_icon,
    style_results_table,
)

LOG = logging.getLogger(__name__)


class DiagnosticWorker(QObject):
    progress = Signal(int, int, object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self, keys: tuple[str, ...], distance_target_mm: int | None = None
    ) -> None:
        super().__init__()
        self.keys = keys
        self.distance_target_mm = distance_target_mm

    def run(self) -> None:
        try:
            suite = DiagnosticSuite()
            if self.distance_target_mm is None:
                results = suite.run(
                    self.keys,
                    lambda done, total, item: self.progress.emit(done, total, item),
                )
            else:
                item = suite.check_ld19_distance(self.distance_target_mm)
                self.progress.emit(1, 1, item)
                results = [item]
            self.completed.emit((suite, results))
        except Exception as error:
            LOG.exception("Diagnostic worker failed")
            self.failed.emit(str(error))


class DetailDialog(QDialog):
    def __init__(self, title: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 580)
        layout = QVBoxLayout(self)
        editor = QPlainTextEdit(text)
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        editor.setFont(mono_font())
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class ManualTestsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manual Hardware Tests")
        self.resize(770, 590)
        layout = QVBoxLayout(self)
        heading = QLabel("Manual Hardware Tests")
        heading.setObjectName("dialogTitle")
        intro = QLabel(
            "These checks require real equipment or observation and are deliberately not marked PASS automatically. Record the steps you completed in your report notes if needed."
        )
        intro.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(intro)
        table = QTableWidget(len(MANUAL_TESTS), 2)
        table.setAlternatingRowColors(True)
        table.setColumnWidth(0, 162)
        table.setHorizontalHeaderLabels(["Test", "How to check safely"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for row, (_, name, instruction) in enumerate(MANUAL_TESTS):
            table.setItem(row, 0, QTableWidgetItem(name))
            item = QTableWidgetItem(instruction)
            item.setToolTip(instruction)
            table.setItem(row, 1, item)
        table.resizeRowsToContents()
        layout.addWidget(table)
        QTimer.singleShot(0, table.resizeRowsToContents)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class LD19DistanceDialog(QDialog):
    """A short guided, optional measurement; normal LD19 health never needs it."""

    def __init__(self, start_check, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LD19 Distance Check")
        self.resize(500, 260)
        layout = QVBoxLayout(self)
        heading = QLabel("Optional LD19 distance check")
        heading.setObjectName("dialogTitle")
        instructions = QLabel(
            "Place a flat, solid target squarely in front of the LiDAR at the selected approximate distance. The check collects several CRC-verified points in the forward ±10° region and reports their median. It is not required for the normal automated LD19 health test."
        )
        instructions.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(instructions)
        buttons = QHBoxLayout()
        for target in (500, 1000, 2000):
            button = QPushButton(f"{target / 1000:.1f} m")
            button.clicked.connect(
                lambda _checked=False, value=target: (self.accept(), start_check(value))
            )
            buttons.addWidget(button)
        layout.addLayout(buttons)
        skip = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        skip.rejected.connect(self.reject)
        layout.addWidget(skip)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.suite = DiagnosticSuite()
        self.is_supported_pi = "Raspberry Pi 4 Model B" in self.suite.model
        self.results: list[TestResult] = []
        self.thread: QThread | None = None
        self.worker: DiagnosticWorker | None = None
        self.current_run_start_index = 0
        self.distance_sequence_active = False
        self.distance_queue: list[int] = []
        self.setWindowTitle("Raspberry Pi 4B Hardware Tester")
        self.resize(1180, 780)
        self.setMinimumSize(920, 620)
        self._build_ui()
        self._refresh_device_info()
        self._show_model_warning_if_needed()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("JavaChip Raspberry pi Tester")
        title.setObjectName("title")
        subtitle = QLabel(
            "Safe, evidence-based checks for Raspberry Pi 4 Model B"
            if self.is_supported_pi
            else "Laptop mode: directly test a connected LD19 / D300 LiDAR"
        )
        subtitle.setObjectName("subtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()
        health_box = QVBoxLayout()
        health_label = QLabel("OVERALL HEALTH")
        health_label.setObjectName("healthLabel")
        self.health_value = StatusLabel(Health.UNKNOWN.value)
        self.health_value.setObjectName("healthValue")
        self._set_health(Health.UNKNOWN)
        health_box.addWidget(health_label, alignment=Qt.AlignmentFlag.AlignRight)
        health_box.addWidget(self.health_value, alignment=Qt.AlignmentFlag.AlignRight)
        header.addLayout(health_box)
        root.addLayout(header)

        info_frame = QFrame()
        info_frame.setObjectName("infoFrame")
        grid = QGridLayout(info_frame)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.setHorizontalSpacing(20)
        self.info_values: dict[str, QLabel] = {}
        for index, field in enumerate(
            ("Device", "Architecture", "Operating System", "Kernel")
        ):
            label = QLabel(field)
            label.setObjectName("infoLabel")
            value = QLabel("Loading…")
            value.setObjectName("infoValue")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, index // 2, (index % 2) * 2)
            grid.addWidget(value, index // 2, (index % 2) * 2 + 1)
            self.info_values[field] = value
        root.addWidget(info_frame)

        control_row = QHBoxLayout()
        self.quick_button = self._button("Quick Test", self.run_quick, primary=True)
        self.full_button = self._button(
            "Full Hardware Test", self.run_full, primary=True
        )
        self.lidar_button = self._button("Test Connected LiDAR", self.run_lidar)
        self.lidar_button.setToolTip(
            "Run the 10-second, read-only LD19/D300 serial capture on a connected USB LiDAR."
        )
        self.distance_button = self._button(
            "Test All 3 Distances", self.run_all_distances
        )
        self.distance_button.setToolTip(
            "Guides you through 0.5 m, 1.0 m, and 2.0 m measurements in one test."
        )
        self.individual_button = self._button(
            "Individual Tests", self.show_individual_tests
        )
        self.manual_button = self._button(
            "Manual Hardware Tests", self.show_manual_tests
        )
        control_row.addWidget(self.quick_button)
        control_row.addWidget(self.full_button)
        control_row.addWidget(self.lidar_button)
        control_row.addWidget(self.distance_button)
        control_row.addWidget(self.individual_button)
        control_row.addWidget(self.manual_button)
        control_row.addStretch()
        root.addLayout(control_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        section = QLabel("Diagnostic results")
        section.setObjectName("sectionTitle")
        self.results_table = QTableWidget(0, 3)
        style_results_table(self.results_table)
        self.results_table.setHorizontalHeaderLabels(["Check", "Status", "Summary"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.results_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.itemSelectionChanged.connect(self.show_selected_details)
        left_layout.addWidget(section)
        left_layout.addWidget(self.results_table)
        splitter.addWidget(left)

        detail = QFrame()
        detail.setObjectName("detailFrame")
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(18, 16, 18, 16)
        detail_title = QLabel("Selected result")
        detail_title.setObjectName("sectionTitle")
        self.detail_status = StatusLabel("NOT TESTED")
        self.detail_status.setObjectName("detailStatus")
        self.detail_summary = QLabel(
            "Run a diagnostic to see evidence and practical next steps here."
        )
        self.detail_summary.setWordWrap(True)
        self.detail_summary.setObjectName("detailSummary")
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("Evidence will appear here.")
        detail_layout.addWidget(detail_title)
        detail_layout.addWidget(self.detail_status)
        detail_layout.addWidget(self.detail_summary)
        detail_layout.addWidget(self.detail_text)
        splitter.addWidget(detail)
        splitter.setSizes([760, 360])
        root.addWidget(splitter, 1)

        progress_layout = QHBoxLayout()
        self.progress_label = QLabel("Ready. No hardware checks have run yet.")
        self.progress_label.setObjectName("progressLabel")
        self.progress_label.setWordWrap(True)
        self.progress_bar = BenchProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_label, 1)
        progress_layout.addWidget(self.progress_bar, 1)
        root.addLayout(progress_layout)

        footer = QHBoxLayout()
        self.system_button = self._button(
            "View System Information", self.view_system_information
        )
        self.report_button = self._button("View Report", self.view_report)
        self.save_button = self._button("Save Report", self.save_report)
        self.logs_button = self._button("Open Logs", self.open_logs)
        exit_button = self._button("Exit", self.close)
        for button in (
            self.system_button,
            self.report_button,
            self.save_button,
            self.logs_button,
            exit_button,
        ):
            footer.addWidget(button)
        footer.addStretch()
        root.addLayout(footer)

    def _button(self, text: str, callback, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(callback)
        if primary:
            button.setProperty("primary", True)
        return button

    def _refresh_device_info(self) -> None:
        for key, value in self.suite.device_information().items():
            self.info_values[key].setText(value)

    def _show_model_warning_if_needed(self) -> None:
        if not self.is_supported_pi:
            self.progress_label.setText(
                "Laptop mode is ready. Connect the D300 USB cable, then select Test Connected LiDAR. Pi-only checks remain unavailable here."
            )

    def _set_health(self, health: Health) -> None:
        self.health_value.setText(health.value)
        self.health_value.set_status(HEALTH_STATUS[health])

    def _set_busy(self, busy: bool) -> None:
        for button in (
            self.quick_button,
            self.full_button,
            self.lidar_button,
            self.distance_button,
            self.individual_button,
            self.manual_button,
            self.system_button,
            self.report_button,
            self.save_button,
        ):
            button.setDisabled(busy)
        self.logs_button.setDisabled(False)

    def run_quick(self) -> None:
        self.start_run(DiagnosticSuite.QUICK_KEYS, "Quick test")

    def run_full(self) -> None:
        self.start_run(
            DiagnosticSuite.QUICK_KEYS + DiagnosticSuite.FULL_EXTRA_KEYS,
            "Full hardware test",
        )

    def run_lidar(self) -> None:
        self.start_run(("ld19",), "Connected LiDAR test")

    def run_all_distances(self) -> None:
        if self._run_is_active() or self.distance_sequence_active:
            return
        self.distance_queue = [500, 1000, 2000]
        self.distance_sequence_active = True
        self._prompt_next_distance()

    def _prompt_next_distance(self) -> None:
        if not self.distance_sequence_active:
            return
        if not self.distance_queue:
            self.distance_sequence_active = False
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            self.progress_label.setText(
                "All three distance checks completed. The results remain in the table."
            )
            return

        target_mm = self.distance_queue[0]
        step = 4 - len(self.distance_queue)
        if not self._confirm_distance_target(target_mm, step):
            self.distance_queue.clear()
            self.distance_sequence_active = False
            self.progress_label.setText(
                "Three-distance test canceled. Completed results remain in the table."
            )
            return

        self.distance_queue.pop(0)
        target_m = target_mm / 1000
        self.start_run(
            (),
            f"Distance {step} of 3 at {target_m:.1f} m",
            target_mm,
        )

    def _confirm_distance_target(self, target_mm: int, step: int) -> bool:
        target_m = target_mm / 1000
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle(f"Distance {step} of 3")
        message.setText(
            f"Place the flat target {target_m:.1f} m in front of the LiDAR."
        )
        message.setInformativeText(
            "Keep it centered, flat, and perpendicular to the sensor, then start the capture."
        )
        capture = message.addButton(
            f"Capture {target_m:.1f} m", QMessageBox.ButtonRole.AcceptRole
        )
        message.addButton(QMessageBox.StandardButton.Cancel)
        message.exec()
        return message.clickedButton() is capture

    def start_run(
        self, keys: tuple[str, ...], label: str, distance_target_mm: int | None = None
    ) -> None:
        if self._run_is_active():
            return
        self.current_run_start_index = len(self.results)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText(f"{label} running…")
        self._set_health(Health.UNKNOWN)
        self._set_busy(True)
        self.thread = QThread(self)
        self.worker = DiagnosticWorker(keys, distance_target_mm)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.completed.connect(self._on_complete)
        self.worker.failed.connect(self._on_failed)
        self.worker.completed.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._on_thread_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _run_is_active(self) -> bool:
        if self.thread is None:
            return False
        try:
            return self.thread.isRunning()
        except RuntimeError:
            # A deleted Qt thread wrapper must never block the next test.
            self.thread = None
            self.worker = None
            return False

    def _on_thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        self._set_busy(False)
        if self.distance_sequence_active:
            QTimer.singleShot(0, self._prompt_next_distance)

    def _on_progress(self, completed: int, total: int, result: TestResult) -> None:
        self.results.append(result)
        self._append_result(result)
        self.results_table.selectRow(self.results_table.rowCount() - 1)
        self.progress_bar.setRange(0, 100)
        percent = round(completed / total * 100) if total else 0
        self.progress_bar.setValue(percent)
        self.progress_label.setText(f"Testing {result.name} ({completed} of {total})…")
        self._set_health(overall_health(self.results))

    def _on_complete(self, payload: tuple[DiagnosticSuite, list[TestResult]]) -> None:
        self.suite, final_results = payload
        # Progress signals are queued before this signal, but ensure no result is lost on unusual Qt delivery order.
        expected_count = self.current_run_start_index + len(final_results)
        if len(self.results) != expected_count:
            previous_results = self.results[: self.current_run_start_index]
            self.results = previous_results + final_results
            self._populate_results()
            if self.results:
                self.results_table.selectRow(len(self.results) - 1)
        self._refresh_device_info()
        self._set_health(overall_health(self.results))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_label.setText(
            "Diagnostic run completed. Select a row for the evidence and next step."
        )

    def _on_failed(self, message: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setText(
            "Diagnostic run stopped unexpectedly. See logs for details."
        )
        QMessageBox.critical(self, "Diagnostic error", message)

    def _append_result(self, result: TestResult) -> None:
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        self.results_table.setItem(row, 0, QTableWidgetItem(result.name))
        status = QTableWidgetItem(result.status.value)
        status.setForeground(QColor(STATUS_COLORS[result.status]))
        status.setFont(mono_font(bold=True))
        status.setIcon(status_icon(result.status))
        self.results_table.setItem(row, 1, status)
        self.results_table.setItem(row, 2, QTableWidgetItem(result.summary))
        self.results_table.resizeRowToContents(row)

    def _populate_results(self) -> None:
        self.results_table.setRowCount(0)
        for result in self.results:
            self._append_result(result)

    def show_selected_details(self) -> None:
        selected = self.results_table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        if row >= len(self.results):
            return
        result = self.results[row]
        self.detail_status.setText(result.status.value)
        self.detail_status.set_status(result.status)
        self.detail_summary.setText(result.summary)
        chunks = []
        if result.details:
            chunks += ["Details", result.details, ""]
        if result.recommendation:
            chunks += ["Recommended next step", result.recommendation, ""]
        chunks.append("Evidence")
        chunks.extend(result.evidence or ["No evidence was captured."])
        self.detail_text.setPlainText("\n".join(chunks))

    def show_individual_tests(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Individual Tests")
        dialog.resize(510, 650)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Run one safe diagnostic at a time."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        choices = QWidget()
        choices_layout = QVBoxLayout(choices)
        for key in (
            DiagnosticSuite.QUICK_KEYS
            + DiagnosticSuite.FULL_EXTRA_KEYS
            + DiagnosticSuite.LIDAR_KEYS
        ):
            name = self.suite.result(key, ResultStatus.NOT_TESTED, "").name
            button = QPushButton(name)
            button.clicked.connect(
                lambda _checked=False, test_key=key, run_name=name: (
                    dialog.accept(),
                    self.start_run((test_key,), run_name),
                )
            )
            choices_layout.addWidget(button)
        distance_check_requested = False

        def request_distance_check() -> None:
            nonlocal distance_check_requested
            distance_check_requested = True
            dialog.accept()

        distance = QPushButton("DISTANCE CHECK (LD19)")
        distance.clicked.connect(request_distance_check)
        choices_layout.addWidget(distance)
        choices_layout.addStretch()
        scroll.setWidget(choices)
        layout.addWidget(scroll, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()
        # Leave the first modal event loop before opening the distance picker.
        # Opening it inside the button's clicked event can cause it to close
        # immediately on Windows when the parent modal unwinds.
        if distance_check_requested:
            self.show_ld19_distance_check()

    def show_ld19_distance_check(self) -> None:
        dialog = LD19DistanceDialog(
            lambda target: self.start_run((), "LD19 distance check", target), self
        )
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.raise_()
        dialog.activateWindow()
        dialog.exec()

    def show_manual_tests(self) -> None:
        ManualTestsDialog(self).exec()

    def view_system_information(self) -> None:
        info = self.suite.device_information()
        text = "\n".join(f"{key}: {value}" for key, value in info.items())
        DetailDialog("System Information", text, self).exec()

    def _current_report(self) -> dict:
        return make_report(self.results, self.suite)

    def view_report(self) -> None:
        DetailDialog(
            "Diagnostic Report", report_text(self._current_report()), self
        ).exec()

    def save_report(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose report folder", str(Path.home())
        )
        if not folder:
            return
        try:
            json_path, text_path = save_report(Path(folder), self.results, self.suite)
        except OSError as error:
            QMessageBox.critical(self, "Could not save report", str(error))
            return
        QMessageBox.information(
            self, "Report saved", f"Saved:\n{json_path}\n{text_path}"
        )

    def open_logs(self) -> None:
        log_file = log_path()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.touch(exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_file.parent))):
            QMessageBox.information(self, "Log location", str(log_file))


def log_path() -> Path:
    return Path.home() / ".local" / "state" / "pi4b-hardware-tester" / "tester.log"


def configure_logging() -> None:
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            handlers=[
                logging.FileHandler(path, encoding="utf-8"),
                logging.StreamHandler(sys.stderr),
            ],
        )
    except OSError:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )


def launch() -> int:
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Raspberry Pi 4B Hardware Tester")
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()
