from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from raspberry_pi_tester.gui import DiagnosticWorker, LD19DistanceDialog, MainWindow
from raspberry_pi_tester.models import ResultStatus


class GuiInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_distance_picker_opens_after_individual_tests_dialog_closes(self) -> None:
        window = MainWindow()
        distance_picker_seen: list[bool] = []

        def click_distance_check() -> None:
            individual_dialog = next(
                dialog
                for dialog in QApplication.topLevelWidgets()
                if dialog.windowTitle() == "Individual Tests"
            )
            distance_button = next(
                button
                for button in individual_dialog.findChildren(QPushButton)
                if button.text() == "DISTANCE CHECK (LD19)"
            )
            distance_button.click()

        def verify_and_close_picker() -> None:
            picker = QApplication.activeModalWidget()
            distance_picker_seen.append(isinstance(picker, LD19DistanceDialog))
            if picker is not None:
                picker.reject()

        QTimer.singleShot(0, click_distance_check)
        QTimer.singleShot(50, verify_and_close_picker)
        window.show_individual_tests()
        self.assertEqual(distance_picker_seen, [True])

    def test_main_distance_button_guides_all_three_checks_in_order(self) -> None:
        class RecordingWindow(MainWindow):
            def __init__(self) -> None:
                self.started_runs: list[tuple[tuple[str, ...], str, int | None]] = []
                super().__init__()

            def _confirm_distance_target(self, target_mm: int, step: int) -> bool:
                return True

            def start_run(
                self,
                keys: tuple[str, ...],
                label: str,
                distance_target_mm: int | None = None,
            ) -> None:
                self.started_runs.append((keys, label, distance_target_mm))

        window = RecordingWindow()
        window.distance_button.click()
        window._on_thread_finished()
        self.app.processEvents()
        window._on_thread_finished()
        self.app.processEvents()
        window._on_thread_finished()
        self.app.processEvents()
        self.assertEqual(
            window.started_runs,
            [
                ((), "Distance 1 of 3 at 0.5 m", 500),
                ((), "Distance 2 of 3 at 1.0 m", 1000),
                ((), "Distance 3 of 3 at 2.0 m", 2000),
            ],
        )
        self.assertFalse(window.distance_sequence_active)

    def test_new_result_is_selected_and_shown_automatically(self) -> None:
        window = MainWindow()
        result = window.suite.result(
            "ld19_distance_check",
            ResultStatus.PASS,
            "Measured distance is visible.",
            evidence=["median_measured_mm=1000"],
        )
        window.progress_bar.setRange(0, 0)
        window._on_progress(1, 1, result)
        self.assertEqual(window.results_table.currentRow(), 0)
        self.assertEqual(window.detail_summary.text(), "Measured distance is visible.")
        self.assertEqual(
            (window.progress_bar.minimum(), window.progress_bar.maximum()), (0, 100)
        )

    def test_finished_run_reenables_next_test_and_clears_thread_references(
        self,
    ) -> None:
        window = MainWindow()
        window.thread = QThread()
        window.worker = DiagnosticWorker(())
        window._set_busy(True)

        window._on_thread_finished()

        self.assertIsNone(window.thread)
        self.assertIsNone(window.worker)
        self.assertTrue(window.lidar_button.isEnabled())
        self.assertTrue(window.distance_button.isEnabled())

    def test_completed_run_preserves_previous_results(self) -> None:
        window = MainWindow()
        previous = window.suite.result(
            "ld19", ResultStatus.PASS, "Previous LiDAR result"
        )
        latest = window.suite.result(
            "ld19_distance_check", ResultStatus.PASS, "Latest distance result"
        )
        window.results = [previous]
        window._populate_results()
        window.current_run_start_index = 1

        window._on_complete((window.suite, [latest]))

        self.assertEqual(window.results, [previous, latest])
        self.assertEqual(window.results_table.rowCount(), 2)
        self.assertEqual(window.results_table.currentRow(), 1)
