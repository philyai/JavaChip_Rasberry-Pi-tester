from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from raspberry_pi_tester.diagnostics import (
    DiagnosticSuite,
    parse_os_release,
    parse_throttle_value,
    parse_windows_serial_driver_errors,
)
from raspberry_pi_tester.models import Health, ResultStatus, TestResult, overall_health
from raspberry_pi_tester.reporting import make_report, save_report
from raspberry_pi_tester.runner import CommandResult, CommandRunner


class FakeRunner(CommandRunner):
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]) -> None:
        self.responses = responses

    def run(self, command, timeout=None):  # type: ignore[no-untyped-def]
        args = tuple(command)
        return self.responses.get(
            args, CommandResult(args, False, None, "", "missing fake response")
        )


def result(key: str, status: ResultStatus) -> TestResult:
    return TestResult(key, key, status).finish()


class DiagnosticsTests(unittest.TestCase):
    def test_parse_os_release(self) -> None:
        self.assertEqual(
            parse_os_release('PRETTY_NAME="Raspberry Pi OS (64-bit)"\nID=raspbian'),
            {"PRETTY_NAME": "Raspberry Pi OS (64-bit)", "ID": "raspbian"},
        )

    def test_parse_throttle_value(self) -> None:
        self.assertEqual(parse_throttle_value("throttled=0x50000"), 0x50000)
        self.assertIsNone(parse_throttle_value("not a throttle value"))

    def test_windows_usb_uart_driver_errors_are_identified(self) -> None:
        output = "CP2102 USB to UART Bridge Controller\nUnrelated display adapter"
        self.assertEqual(
            parse_windows_serial_driver_errors(output),
            ["CP2102 USB to UART Bridge Controller"],
        )

    def test_overall_health_never_treats_unchecked_as_good(self) -> None:
        self.assertIs(overall_health([]), Health.UNKNOWN)
        self.assertIs(
            overall_health([result("x", ResultStatus.NOT_AVAILABLE)]), Health.UNKNOWN
        )
        self.assertIs(
            overall_health([result("x", ResultStatus.MANUAL)]), Health.UNKNOWN
        )
        self.assertIs(overall_health([result("x", ResultStatus.PASS)]), Health.GOOD)
        self.assertIs(
            overall_health([result("x", ResultStatus.WARNING)]), Health.WARNING
        )
        self.assertIs(
            overall_health(
                [result("x", ResultStatus.FAIL), result("y", ResultStatus.PASS)]
            ),
            Health.PROBLEM,
        )

    def test_historical_undervoltage_is_warning_not_pass(self) -> None:
        suite = DiagnosticSuite(
            FakeRunner(
                {
                    ("vcgencmd", "get_throttled"): CommandResult(
                        ("vcgencmd", "get_throttled"), True, 0, "throttled=0x50000", ""
                    ),
                }
            )
        )
        result_value = suite.check_undervoltage()
        self.assertIs(result_value.status, ResultStatus.WARNING)
        self.assertIn("Under-voltage occurred since boot", result_value.summary)

    def test_missing_power_tool_is_not_a_pass(self) -> None:
        suite = DiagnosticSuite(FakeRunner({}))
        self.assertIs(suite.check_power().status, ResultStatus.NOT_AVAILABLE)

    def test_non_pi_model_warns(self) -> None:
        from unittest.mock import patch

        with patch(
            "raspberry_pi_tester.diagnostics.read_text",
            side_effect=lambda path: "Generic Computer" if path.name == "model" else "",
        ):
            suite = DiagnosticSuite(FakeRunner({}))
        check = suite.check_model()
        self.assertIs(check.status, ResultStatus.WARNING)
        self.assertIn("Unsupported", check.summary)

    def test_debian_on_pi_4b_is_supported(self) -> None:
        from unittest.mock import patch

        def device_text(path: Path) -> str:
            if path.name == "model":
                return "Raspberry Pi 4 Model B Rev 1.5"
            if path.name == "os-release":
                return 'PRETTY_NAME="Debian GNU/Linux 12 (trixie)"\nID=debian'
            return ""

        with patch("raspberry_pi_tester.diagnostics.read_text", side_effect=device_text):
            suite = DiagnosticSuite(FakeRunner({}))
        check = suite.check_operating_system()
        self.assertIs(check.status, ResultStatus.PASS)
        self.assertIn("Raspberry Pi 4 Model B", check.summary)

    def test_runner_never_uses_a_shell(self) -> None:
        runner = CommandRunner()
        # A non-existent command must be reported rather than passed through a shell.
        result_value = runner.run(["command-that-does-not-exist-pi-tester"])
        self.assertFalse(result_value.available)
        self.assertIsNone(result_value.returncode)

    def test_report_export_preserves_status_and_evidence(self) -> None:
        suite = DiagnosticSuite(FakeRunner({}))
        results = [
            TestResult(
                "power",
                "Throttling status",
                ResultStatus.WARNING,
                "Under-voltage occurred since boot.",
                evidence=["throttled=0x10000"],
            ).finish()
        ]
        report = make_report(results, suite)
        self.assertEqual(report["overall_health"], Health.WARNING.value)
        self.assertEqual(report["results"][0]["evidence"], ["throttled=0x10000"])
        with TemporaryDirectory() as temporary_directory:
            json_path, text_path = save_report(
                Path(temporary_directory), results, suite
            )
            self.assertTrue(json_path.is_file())
            self.assertTrue(text_path.is_file())
            self.assertIn(
                "Under-voltage occurred since boot.",
                text_path.read_text(encoding="utf-8"),
            )
