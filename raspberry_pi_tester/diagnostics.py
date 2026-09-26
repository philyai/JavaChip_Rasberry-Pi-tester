from __future__ import annotations

import logging
import platform
import re
from collections.abc import Callable, Iterable
from pathlib import Path

import psutil

from .ld19 import BAUDRATE, LD19Diagnostic, health_assessment
from .models import ResultStatus, TestResult
from .runner import CommandResult, CommandRunner

LOG = logging.getLogger(__name__)

MODEL_PATH = Path("/proc/device-tree/model")
OS_RELEASE_PATH = Path("/etc/os-release")
CPUINFO_PATH = Path("/proc/cpuinfo")
MEMINFO_PATH = Path("/proc/meminfo")
GPIO_CHIP_PATH = Path("/dev/gpiochip0")
WINDOWS_PNP_SERIAL_ERRORS_COMMAND = (
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    "Get-PnpDevice -PresentOnly -Status Error | Select-Object -ExpandProperty FriendlyName",
)

THROTTLE_FLAGS = {
    0: (
        "Under-voltage detected now",
        "Check the official 5V/3A USB-C supply and cable.",
    ),
    1: ("ARM frequency capped now", "Check cooling and power delivery."),
    2: (
        "Throttling active now",
        "Check cooling and power delivery before demanding work.",
    ),
    3: (
        "Soft temperature limit active now",
        "Improve cooling and allow the board to cool.",
    ),
    16: (
        "Under-voltage occurred since boot",
        "Inspect the power supply, cable, and USB load.",
    ),
    17: (
        "ARM frequency cap occurred since boot",
        "Review cooling and power delivery under load.",
    ),
    18: (
        "Throttling occurred since boot",
        "Review cooling and power delivery under load.",
    ),
    19: (
        "Soft temperature limit occurred since boot",
        "Review the case, fan, and thermal conditions.",
    ),
}


def read_text(path: Path) -> str:
    try:
        return (
            path.read_text(encoding="utf-8", errors="replace")
            .replace("\x00", "")
            .strip()
        )
    except OSError:
        return ""


def parse_os_release(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def parse_throttle_value(output: str) -> int | None:
    match = re.search(r"0x([0-9a-fA-F]+)", output)
    return int(match.group(1), 16) if match else None


def parse_windows_serial_driver_errors(output: str) -> list[str]:
    """Keep only present Windows driver failures relevant to USB serial LiDARs."""
    return [
        line.strip()
        for line in output.splitlines()
        if re.search(
            r"cp210|ch34|ftdi|pl2303|usb.*uart|usb.*serial", line, re.IGNORECASE
        )
    ]


def status_for_return(
    command: CommandResult, success_summary: str, failed_summary: str
) -> TestResult:
    status = ResultStatus.PASS if command.ok else ResultStatus.WARNING
    return TestResult(
        "",
        "",
        status,
        success_summary if command.ok else failed_summary,
        evidence=[command.stdout, command.stderr],
    ).finish()


class DiagnosticSuite:
    """Safe, Pi-focused diagnostics. Each check is independently fault-contained."""

    QUICK_KEYS = (
        "model",
        "operating_system",
        "cpu",
        "cpu_load",
        "cpu_frequency",
        "temperature",
        "ram",
        "ram_health",
        "root_filesystem",
        "storage",
        "power",
        "undervoltage",
        "wifi",
        "ethernet",
        "bluetooth",
        "usb_controller",
        "usb_devices",
        "kernel_errors",
    )
    FULL_EXTRA_KEYS = ("gpio", "i2c", "spi", "uart", "camera")
    LIDAR_KEYS = ("ld19_detect", "ld19", "ros2_lidar")

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.model = read_text(MODEL_PATH)
        self.os_release = parse_os_release(read_text(OS_RELEASE_PATH))
        self._checks: dict[str, Callable[[], TestResult]] = {
            "model": self.check_model,
            "operating_system": self.check_operating_system,
            "cpu": self.check_cpu,
            "cpu_load": self.check_cpu_load,
            "cpu_frequency": self.check_cpu_frequency,
            "temperature": self.check_temperature,
            "ram": self.check_ram,
            "ram_health": self.check_ram_health,
            "root_filesystem": self.check_root_filesystem,
            "storage": self.check_storage,
            "power": self.check_power,
            "undervoltage": self.check_undervoltage,
            "wifi": self.check_wifi,
            "ethernet": self.check_ethernet,
            "bluetooth": self.check_bluetooth,
            "usb_controller": self.check_usb_controller,
            "usb_devices": self.check_usb_devices,
            "kernel_errors": self.check_kernel_errors,
            "gpio": self.check_gpio,
            "i2c": lambda: self.check_interface("I2C", "/dev/i2c-", "i2c"),
            "spi": lambda: self.check_interface("SPI", "/dev/spidev", "spi"),
            "uart": lambda: self.check_interface("UART", "/dev/serial", "serial"),
            "camera": self.check_camera,
            "ld19_detect": self.check_ld19_detect,
            "ld19": self.check_ld19,
            "ld19_distance_check": lambda: self.check_ld19_distance(1000),
            "ros2_lidar": self.check_ros2_lidar,
        }

    def device_information(self) -> dict[str, str]:
        return {
            "Device": self.model or "Unable to read /proc/device-tree/model",
            "Architecture": platform.machine() or "Unknown",
            "Operating System": self.os_release.get("PRETTY_NAME", platform.platform()),
            "Kernel": platform.release(),
        }

    def run(
        self,
        keys: Iterable[str],
        progress: Callable[[int, int, TestResult], None] | None = None,
    ) -> list[TestResult]:
        selected = list(keys)
        results: list[TestResult] = []
        for index, key in enumerate(selected, start=1):
            try:
                result = self._checks[key]()
            except Exception as error:  # each test remains isolated
                LOG.exception("Diagnostic '%s' crashed", key)
                result = self.result(
                    key,
                    ResultStatus.WARNING,
                    "Check could not complete.",
                    str(error),
                    recommendation="Review the log and retry this individual check.",
                )
            results.append(result.finish() if not result.finished_at else result)
            if progress:
                progress(index, len(selected), results[-1])
        return results

    def result(
        self,
        key: str,
        status: ResultStatus,
        summary: str,
        details: str = "",
        evidence: list[str] | None = None,
        recommendation: str = "",
    ) -> TestResult:
        names = {
            "model": "Raspberry Pi model",
            "operating_system": "Operating system",
            "cpu": "CPU",
            "cpu_load": "CPU load",
            "cpu_frequency": "CPU frequency",
            "temperature": "CPU temperature",
            "ram": "RAM availability",
            "ram_health": "RAM basic health information",
            "root_filesystem": "Root filesystem",
            "storage": "MicroSD / storage",
            "power": "Throttling status",
            "undervoltage": "Undervoltage history",
            "wifi": "Wi-Fi adapter",
            "ethernet": "Ethernet adapter",
            "bluetooth": "Bluetooth adapter",
            "usb_controller": "USB controller",
            "usb_devices": "USB device detection",
            "kernel_errors": "Recent critical kernel errors",
            "gpio": "GPIO interface",
            "i2c": "I2C interface",
            "spi": "SPI interface",
            "uart": "UART interface",
            "camera": "Camera interface",
            "ld19_detect": "Auto Detect LD19 / D300",
            "ld19": "LD19 / D300 LiDAR",
            "ld19_distance_check": "LD19 distance check",
            "ros2_lidar": "ROS 2 LiDAR integration",
        }
        return TestResult(
            key,
            names.get(key, key),
            status,
            summary,
            details,
            evidence or [],
            recommendation,
        ).finish()

    def check_ld19(self) -> TestResult:
        """Run the bounded raw serial diagnostic; a detected port is not a pass."""
        capture = LD19Diagnostic().run(duration=10.0)
        token, summary, evidence = health_assessment(capture)
        driver_errors = self.windows_serial_driver_errors()
        evidence.extend(f"windows_serial_driver_error={item}" for item in driver_errors)
        if capture.port:
            lsusb = self.runner.run(["lsusb"])
            if lsusb.available:
                evidence.extend(
                    f"lsusb={line}" for line in lsusb.stdout.splitlines() if line
                )
            udev = self.runner.run(
                ["udevadm", "info", "--query=property", "--name", capture.port]
            )
            if udev.ok:
                evidence.extend(
                    f"udevadm={line}" for line in udev.stdout.splitlines() if line
                )
            kernel = self.runner.run(["dmesg", "--level=err,warn"])
            if kernel.ok:
                relevant = [
                    line
                    for line in kernel.stdout.splitlines()
                    if re.search(
                        r"usb|tty|serial|cp210|ch34|ftdi|pl2303", line, re.IGNORECASE
                    )
                ]
                evidence.extend(f"kernel={line}" for line in relevant[-20:])
        status = {
            "PASS": ResultStatus.PASS,
            "WARNING": ResultStatus.WARNING,
            "FAIL": ResultStatus.FAIL,
            "NOT_AVAILABLE": ResultStatus.NOT_AVAILABLE,
        }[token]
        recommendation = ""
        if summary == "NOT CONNECTED":
            if driver_errors:
                summary = "SERIAL DRIVER ERROR"
                recommendation = (
                    "Windows detected the USB-to-UART adapter but did not assign a COM port. "
                    "Install or repair the Silicon Labs CP210x driver, reconnect the D300, "
                    "confirm that Device Manager shows a COM port, then retry."
                )
            else:
                host = "laptop" if platform.system() == "Windows" else "Raspberry Pi"
                recommendation = (
                    "Connect LD19 to the D300 development kit, then connect the D300 USB cable "
                    f"directly to this {host} and retry."
                )
        elif summary == "PORT BUSY":
            recommendation = "Stop the ROS 2 driver, a serial terminal, or another program using this port; then retry."
        elif summary == "PERMISSION DENIED":
            recommendation = "Add the current user to the dialout group, log out and back in, then retry. Do not run the whole application as root."
        elif token == "FAIL":
            recommendation = "Check the LD19-to-D300 cable and power, then retry with the motor running. USB detection alone is not sufficient."
        elif token == "WARNING":
            recommendation = "Review the saved evidence and retry with the sensor unobstructed and a stable USB connection."
        return self.result(
            "ld19", status, summary, evidence=evidence, recommendation=recommendation
        )

    def check_ld19_detect(self) -> TestResult:
        """Short detection pass: it proves protocol data, not full health."""
        diagnostic = LD19Diagnostic()
        candidates = diagnostic.candidates()
        capture = diagnostic.auto_detect(timeout_per_port=2.5)
        driver_errors = self.windows_serial_driver_errors()
        evidence = [
            f"baud={BAUDRATE}",
            f"serial_candidates={', '.join(candidate.device for candidate in candidates) or 'none'}",
            f"selected_port={capture.port or 'none'}",
            f"valid_packets={capture.valid_packets}",
            f"crc_failures={capture.parser.crc_failures}",
            f"serial_detail={capture.error_detail}" if capture.error_detail else "",
        ]
        evidence.extend(f"windows_serial_driver_error={item}" for item in driver_errors)
        if capture.valid_packets >= 5 and capture.port:
            return self.result(
                "ld19_detect",
                ResultStatus.PASS,
                f"LD19 identified on {capture.port} after {capture.valid_packets} consecutive CRC-verified packets.",
                evidence=evidence,
                recommendation="Run TEST LD19 / D300 for the approximately 10-second rotation, coverage, distance, and continuity diagnostic.",
            )
        summary = capture.error_kind or "NOT CONNECTED"
        host = (
            "this Windows laptop"
            if platform.system() == "Windows"
            else "the Raspberry Pi"
        )
        recommendation = (
            "Connect LD19 to D300, then connect its USB cable directly to "
            f"{host}; no fixed serial-port path is assumed."
        )
        if summary == "NOT CONNECTED" and driver_errors:
            summary = "SERIAL DRIVER ERROR"
            recommendation = (
                "Windows detected the USB-to-UART adapter but did not assign a COM port. "
                "Install or repair the Silicon Labs CP210x driver, reconnect the D300, "
                "confirm that Device Manager shows a COM port, then retry."
            )
        elif summary == "PORT BUSY":
            recommendation = "Stop the ROS 2 driver, serial terminal, or other process that owns this port, then retry."
        elif summary == "PERMISSION DENIED":
            recommendation = "Add the current user to dialout, log out and back in, then retry. Do not run the app as root."
        return self.result(
            "ld19_detect",
            ResultStatus.NOT_AVAILABLE,
            summary,
            evidence=evidence,
            recommendation=recommendation,
        )

    def windows_serial_driver_errors(self) -> list[str]:
        """Report a Windows USB-UART driver failure without changing device state."""
        if platform.system() != "Windows":
            return []
        command = self.runner.run(WINDOWS_PNP_SERIAL_ERRORS_COMMAND, timeout=4)
        return parse_windows_serial_driver_errors(command.stdout) if command.ok else []

    def check_ros2_lidar(self) -> TestResult:
        """Check ROS 2 separately after raw serial workers have released their port."""
        topics = self.runner.run(["ros2", "topic", "list"])
        if not topics.available:
            return self.result(
                "ros2_lidar",
                ResultStatus.NOT_AVAILABLE,
                "ROS 2: NOT AVAILABLE.",
                recommendation="Install/source ROS 2 only if your robotics stack uses it; this does not affect the raw LD19 hardware result.",
            )
        if not topics.ok:
            return self.result(
                "ros2_lidar",
                ResultStatus.NOT_AVAILABLE,
                "ROS 2 topic discovery did not complete.",
                evidence=[topics.stdout, topics.stderr],
                recommendation="Source the intended ROS 2 environment and retry. This does not affect the raw LD19 hardware result.",
            )
        if "/scan" not in topics.stdout.splitlines():
            return self.result(
                "ros2_lidar",
                ResultStatus.NOT_AVAILABLE,
                "ROS 2 is available, but /scan is not published.",
                evidence=[topics.stdout],
                recommendation="Start the LD19 ROS 2 driver and retry. Do not run its driver while using the raw LD19 test on the same port.",
            )
        info = self.runner.run(["ros2", "topic", "info", "/scan"])
        sample = self.runner.run(
            ["ros2", "topic", "echo", "/scan", "--once"], timeout=6
        )
        required = (
            "angle_min:",
            "angle_max:",
            "angle_increment:",
            "range_min:",
            "range_max:",
            "ranges:",
            "frame_id:",
        )
        combined = f"{sample.stdout}\n{sample.stderr}"
        if not sample.ok or not all(field in combined for field in required):
            return self.result(
                "ros2_lidar",
                ResultStatus.WARNING,
                "ROS 2 /scan exists but a complete LaserScan message was not verified.",
                evidence=[info.stdout, info.stderr, sample.stdout, sample.stderr],
                recommendation="Confirm the driver publishes sensor_msgs/LaserScan and that it owns the LD19 port while this ROS test runs.",
            )
        rate = self.runner.run(
            ["ros2", "topic", "hz", "/scan", "--window", "5"], timeout=4
        )
        rate_match = re.search(
            r"average rate:\s*([0-9.]+)", f"{rate.stdout}\n{rate.stderr}"
        )
        evidence = [info.stdout, sample.stdout]
        if rate_match:
            evidence.append(f"measured_ros_scan_hz={rate_match.group(1)}")
        return self.result(
            "ros2_lidar",
            ResultStatus.PASS,
            "ROS 2: AVAILABLE; /scan delivered a complete LaserScan message"
            + (f" at {rate_match.group(1)} Hz." if rate_match else "."),
            evidence=evidence,
            recommendation="This confirms ROS integration only. Raw LD19 hardware validation remains a separate test at 230400 baud.",
        )

    def check_ld19_distance(self, target_mm: int) -> TestResult:
        capture, measured = LD19Diagnostic().distance_check(target_mm)
        evidence = [
            f"target_mm={target_mm}",
            f"serial_port={capture.port or 'not detected'}",
            f"valid_packets={capture.valid_packets}",
            f"crc_failures={capture.parser.crc_failures}",
            "angular_region=forward +/-10 degrees",
        ]
        if measured is None:
            result = self.result(
                "ld19_distance_check",
                ResultStatus.NOT_AVAILABLE,
                "No valid forward-region readings were collected for the distance check.",
                evidence=evidence,
                recommendation="Place a flat solid target squarely about the selected distance in front of the LiDAR, ensure the raw port is not busy, and retry. This optional check does not affect normal LD19 health.",
            )
            result.name = f"LD19 distance - {target_mm / 1000:.1f} m"
            return result
        difference = abs(measured - target_mm)
        ratio = difference / target_mm
        evidence.extend(
            (
                f"median_measured_mm={measured:.1f}",
                f"difference_mm={difference:.1f}",
                f"valid_readings={len(capture.metrics.observations)}",
            )
        )
        status = ResultStatus.PASS if ratio <= 0.10 else ResultStatus.WARNING
        result = self.result(
            "ld19_distance_check",
            status,
            f"Target: about {target_mm / 1000:.1f} m; measured median: {measured / 1000:.2f} m; difference: {difference / 1000:.2f} m.",
            evidence=evidence,
            recommendation="Keep the target flat and perpendicular to the sensor, then retry if the difference exceeds 10%."
            if status is ResultStatus.WARNING
            else "Optional distance check passed; it is not required for normal automated LD19 health.",
        )
        result.name = f"LD19 distance - {target_mm / 1000:.1f} m"
        return result

    def check_model(self) -> TestResult:
        model = self.model
        if "Raspberry Pi 4 Model B" in model:
            return self.result(
                "model",
                ResultStatus.PASS,
                model,
                evidence=["/proc/device-tree/model", model],
            )
        if model:
            return self.result(
                "model",
                ResultStatus.WARNING,
                "Unsupported hardware: " + model,
                evidence=["/proc/device-tree/model", model],
                recommendation="This application is designed specifically for Raspberry Pi 4 Model B.",
            )
        return self.result(
            "model",
            ResultStatus.NOT_AVAILABLE,
            "Hardware model information is unavailable.",
            recommendation="Run this on Raspberry Pi OS on a Raspberry Pi 4 Model B.",
        )

    def check_operating_system(self) -> TestResult:
        pretty = self.os_release.get("PRETTY_NAME", "Unknown operating system")
        if "Raspberry Pi OS" in pretty:
            return self.result(
                "operating_system", ResultStatus.PASS, pretty, evidence=[pretty]
            )
        if (
            self.os_release.get("ID") == "debian"
            and "Raspberry Pi 4 Model B" in self.model
        ):
            return self.result(
                "operating_system",
                ResultStatus.PASS,
                f"{pretty} on Raspberry Pi 4 Model B",
                evidence=[pretty, "ID=debian", self.model],
            )
        return self.result(
            "operating_system",
            ResultStatus.WARNING,
            pretty,
            evidence=[pretty],
            recommendation=(
                "Use Raspberry Pi OS 64-bit or Debian 64-bit on a confirmed "
                "Raspberry Pi 4 Model B."
            ),
        )

    def check_cpu(self) -> TestResult:
        cores = psutil.cpu_count(logical=False) or 0
        logical = psutil.cpu_count(logical=True) or 0
        arch = platform.machine()
        evidence = [
            f"architecture={arch}",
            f"physical_cores={cores}",
            f"logical_cores={logical}",
        ]
        if arch in {"aarch64", "arm64"} and logical >= 4:
            return self.result(
                "cpu",
                ResultStatus.PASS,
                f"{logical} logical CPU cores detected ({arch}).",
                evidence=evidence,
            )
        return self.result(
            "cpu",
            ResultStatus.WARNING,
            f"Detected {logical} logical CPU cores ({arch}).",
            evidence=evidence,
            recommendation="A Pi 4B running 64-bit Raspberry Pi OS normally reports aarch64 and four cores.",
        )

    def check_cpu_load(self) -> TestResult:
        load = psutil.cpu_percent(interval=0.5)
        evidence = [f"cpu_percent={load:.1f}"]
        if load < 85:
            return self.result(
                "cpu_load",
                ResultStatus.PASS,
                f"CPU load is {load:.1f}%.",
                evidence=evidence,
            )
        return self.result(
            "cpu_load",
            ResultStatus.WARNING,
            f"CPU load is high at {load:.1f}%.",
            evidence=evidence,
            recommendation="Close demanding applications and retry before interpreting other measurements.",
        )

    def check_cpu_frequency(self) -> TestResult:
        frequency = psutil.cpu_freq()
        if frequency and frequency.current > 0:
            mhz = frequency.current
            status = ResultStatus.PASS if 300 <= mhz <= 2600 else ResultStatus.WARNING
            return self.result(
                "cpu_frequency",
                status,
                f"Current CPU frequency: {mhz:.0f} MHz.",
                evidence=[
                    f"current_mhz={mhz:.2f}",
                    f"min_mhz={frequency.min:.2f}",
                    f"max_mhz={frequency.max:.2f}",
                ],
                recommendation="Frequency changes with workload and temperature; retry while idle if this remains unusual."
                if status is ResultStatus.WARNING
                else "",
            )
        clock = self.runner.run(["vcgencmd", "measure_clock", "arm"])
        match = re.search(r"=(\d+)", clock.stdout)
        if clock.ok and match:
            mhz = int(match.group(1)) / 1_000_000
            return self.result(
                "cpu_frequency",
                ResultStatus.PASS,
                f"Current ARM clock: {mhz:.0f} MHz.",
                evidence=[clock.stdout],
            )
        return self.result(
            "cpu_frequency",
            ResultStatus.NOT_AVAILABLE,
            "CPU frequency could not be read.",
            evidence=[clock.stderr],
            recommendation="Install or enable the usual Raspberry Pi OS tools, then retry.",
        )

    def check_temperature(self) -> TestResult:
        temp_c: float | None = None
        for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            raw = read_text(path)
            if raw.isdigit():
                temp_c = int(raw) / 1000.0
                break
        if temp_c is None:
            command = self.runner.run(["vcgencmd", "measure_temp"])
            match = re.search(r"([0-9]+(?:\.[0-9]+)?)", command.stdout)
            if match:
                temp_c = float(match.group(1))
        if temp_c is None:
            return self.result(
                "temperature",
                ResultStatus.NOT_AVAILABLE,
                "CPU temperature sensor is unavailable.",
                recommendation="Run this check on Raspberry Pi OS with the thermal sensor available.",
            )
        status = (
            ResultStatus.PASS
            if temp_c < 80
            else ResultStatus.WARNING
            if temp_c < 85
            else ResultStatus.FAIL
        )
        recommendation = (
            "Improve cooling before sustained use."
            if status is not ResultStatus.PASS
            else ""
        )
        return self.result(
            "temperature",
            status,
            f"CPU temperature: {temp_c:.1f} °C.",
            evidence=[f"temperature_c={temp_c:.1f}"],
            recommendation=recommendation,
        )

    def check_ram(self) -> TestResult:
        memory = psutil.virtual_memory()
        available_mb = memory.available / 1024 / 1024
        status = ResultStatus.PASS if memory.percent < 85 else ResultStatus.WARNING
        return self.result(
            "ram",
            status,
            f"{available_mb:.0f} MiB available ({memory.percent:.1f}% in use).",
            evidence=[
                f"total_mib={memory.total / 1024 / 1024:.0f}",
                f"available_mib={available_mb:.0f}",
                f"used_percent={memory.percent:.1f}",
            ],
            recommendation="Close memory-heavy applications and retry."
            if status is ResultStatus.WARNING
            else "",
        )

    def check_ram_health(self) -> TestResult:
        meminfo = read_text(MEMINFO_PATH)
        if not meminfo:
            return self.result(
                "ram_health",
                ResultStatus.NOT_AVAILABLE,
                "Memory information is unavailable.",
            )
        relevant = [
            line
            for line in meminfo.splitlines()
            if line.startswith(
                ("MemTotal:", "MemAvailable:", "SwapTotal:", "SwapFree:")
            )
        ]
        return self.result(
            "ram_health",
            ResultStatus.MANUAL,
            "Usage information was collected; a non-destructive RAM fault test is not available in this tool.",
            details="This check does not claim that RAM chips are fault-free.",
            evidence=relevant,
            recommendation="For a suspected RAM fault, use a planned maintenance window and a purpose-built memory test.",
        )

    def check_root_filesystem(self) -> TestResult:
        usage = psutil.disk_usage("/")
        used_percent = usage.percent
        status = (
            ResultStatus.PASS
            if used_percent < 85
            else ResultStatus.WARNING
            if used_percent < 95
            else ResultStatus.FAIL
        )
        return self.result(
            "root_filesystem",
            status,
            f"Root filesystem is {used_percent:.1f}% used.",
            evidence=[
                f"total_gib={usage.total / 1024**3:.2f}",
                f"free_gib={usage.free / 1024**3:.2f}",
                f"used_percent={used_percent:.1f}",
            ],
            recommendation="Free space before updates or data collection."
            if status is not ResultStatus.PASS
            else "",
        )

    def check_storage(self) -> TestResult:
        blocks = self.runner.run(
            [
                "lsblk",
                "--json",
                "--output",
                "NAME,TYPE,SIZE,MODEL,TRAN,MOUNTPOINT,FSTYPE",
            ]
        )
        evidence = [blocks.stdout or blocks.stderr]
        if not blocks.ok:
            return self.result(
                "storage",
                ResultStatus.NOT_AVAILABLE,
                "Storage inventory command is unavailable.",
                evidence=evidence,
            )
        lower = blocks.stdout.lower()
        if "mmcblk" in lower:
            return self.result(
                "storage",
                ResultStatus.PASS,
                "A microSD/MMC block device was detected.",
                evidence=evidence,
            )
        return self.result(
            "storage",
            ResultStatus.WARNING,
            "No microSD/MMC block device was identified.",
            evidence=evidence,
            recommendation="Confirm the boot media and inspect the storage inventory in the report.",
        )

    def _throttle_result(self, key: str, history_only: bool) -> TestResult:
        command = self.runner.run(["vcgencmd", "get_throttled"])
        value = parse_throttle_value(command.stdout)
        if not command.ok or value is None:
            return self.result(
                key,
                ResultStatus.NOT_AVAILABLE,
                "Raspberry Pi power/throttling information is unavailable.",
                evidence=[command.stdout, command.stderr],
                recommendation="vcgencmd is required for this Pi firmware check.",
            )
        bits = range(16, 20) if history_only else range(4)
        findings = [THROTTLE_FLAGS[bit] for bit in bits if value & (1 << bit)]
        if not findings:
            summary = (
                "No historical undervoltage/throttling flags since boot."
                if history_only
                else "No active throttling or voltage flags."
            )
            return self.result(
                key,
                ResultStatus.PASS,
                summary,
                evidence=[command.stdout, f"parsed=0x{value:x}"],
            )
        names = "; ".join(item[0] for item in findings)
        recommendation = " ".join(dict.fromkeys(item[1] for item in findings))
        return self.result(
            key,
            ResultStatus.WARNING,
            names + ".",
            evidence=[command.stdout, f"parsed=0x{value:x}"],
            recommendation=recommendation,
        )

    def check_power(self) -> TestResult:
        return self._throttle_result("power", False)

    def check_undervoltage(self) -> TestResult:
        return self._throttle_result("undervoltage", True)

    def check_wifi(self) -> TestResult:
        command = self.runner.run(["iw", "dev"])
        if not command.available:
            return self.result(
                "wifi",
                ResultStatus.NOT_AVAILABLE,
                "The iw utility is not installed.",
                recommendation="Install iw to inspect the Wi-Fi interface.",
            )
        if command.ok and "Interface" in command.stdout:
            interfaces = re.findall(
                r"^\s*Interface\s+(\S+)", command.stdout, re.MULTILINE
            )
            return self.result(
                "wifi",
                ResultStatus.PASS,
                "Wi-Fi interface detected: " + ", ".join(interfaces) + ".",
                evidence=[command.stdout],
            )
        return self.result(
            "wifi",
            ResultStatus.WARNING,
            "No Wi-Fi interface was reported.",
            evidence=[command.stdout, command.stderr],
            recommendation="Check rfkill, the operating system image, and hardware seating.",
        )

    def check_ethernet(self) -> TestResult:
        command = self.runner.run(["ip", "-brief", "link"])
        if not command.ok:
            return self.result(
                "ethernet",
                ResultStatus.NOT_AVAILABLE,
                "Network interface inventory is unavailable.",
                evidence=[command.stderr],
            )
        candidates = [
            line
            for line in command.stdout.splitlines()
            if re.match(r"^(eth\d+|en\S+)", line)
        ]
        if candidates:
            return self.result(
                "ethernet",
                ResultStatus.PASS,
                "Ethernet interface detected.",
                evidence=candidates,
            )
        return self.result(
            "ethernet",
            ResultStatus.WARNING,
            "No Ethernet interface was identified.",
            evidence=[command.stdout],
            recommendation="Check the OS driver and inspect the Ethernet port LEDs/cable with a manual test.",
        )

    def check_bluetooth(self) -> TestResult:
        command = self.runner.run(["bluetoothctl", "show"])
        if not command.available:
            return self.result(
                "bluetooth",
                ResultStatus.NOT_AVAILABLE,
                "bluetoothctl is not installed.",
                recommendation="Install or enable BlueZ tools to inspect Bluetooth.",
            )
        if command.ok and "Controller" in command.stdout:
            powered = re.search(r"Powered:\s*(yes|no)", command.stdout, re.IGNORECASE)
            if powered and powered.group(1).lower() == "no":
                return self.result(
                    "bluetooth",
                    ResultStatus.WARNING,
                    "Bluetooth controller detected but powered off.",
                    evidence=[command.stdout],
                    recommendation="Enable Bluetooth in Raspberry Pi OS and retry.",
                )
            return self.result(
                "bluetooth",
                ResultStatus.PASS,
                "Bluetooth controller detected.",
                evidence=[command.stdout],
            )
        return self.result(
            "bluetooth",
            ResultStatus.WARNING,
            "No Bluetooth controller was reported.",
            evidence=[command.stdout, command.stderr],
            recommendation="Check rfkill and BlueZ service status.",
        )

    def check_usb_controller(self) -> TestResult:
        command = self.runner.run(["lspci"])
        if not command.available:
            command = self.runner.run(["lsusb", "-t"])
        text = command.stdout.lower()
        if command.ok and ("usb" in text or "xhci" in text):
            return self.result(
                "usb_controller",
                ResultStatus.PASS,
                "USB controller topology was detected.",
                evidence=[command.stdout],
            )
        if not command.available:
            return self.result(
                "usb_controller",
                ResultStatus.NOT_AVAILABLE,
                "Neither lspci nor lsusb is installed.",
            )
        return self.result(
            "usb_controller",
            ResultStatus.WARNING,
            "USB controller topology was not identified.",
            evidence=[command.stdout, command.stderr],
            recommendation="Install usbutils or inspect the system report.",
        )

    def check_usb_devices(self) -> TestResult:
        command = self.runner.run(["lsusb"])
        if not command.available:
            return self.result(
                "usb_devices",
                ResultStatus.NOT_AVAILABLE,
                "lsusb is not installed.",
                recommendation="Install usbutils to list USB devices.",
            )
        devices = [line for line in command.stdout.splitlines() if line.strip()]
        if devices:
            return self.result(
                "usb_devices",
                ResultStatus.PASS,
                f"{len(devices)} USB device(s) reported.",
                evidence=devices,
            )
        return self.result(
            "usb_devices",
            ResultStatus.WARNING,
            "No USB devices were reported.",
            evidence=[command.stdout],
            recommendation="Use the manual USB-port test with a known working device.",
        )

    def check_kernel_errors(self) -> TestResult:
        command = self.runner.run(["dmesg", "--level=err,crit,alert,emerg"])
        if not command.ok:
            return self.result(
                "kernel_errors",
                ResultStatus.NOT_AVAILABLE,
                "Recent kernel error log is unavailable.",
                evidence=[command.stderr],
                recommendation="This can require permission under Raspberry Pi OS; inspect logs manually if needed.",
            )
        entries = [line for line in command.stdout.splitlines() if line.strip()]
        if not entries:
            return self.result(
                "kernel_errors",
                ResultStatus.PASS,
                "No error-level kernel messages were returned.",
                evidence=["dmesg --level=err,crit,alert,emerg returned no lines"],
            )
        return self.result(
            "kernel_errors",
            ResultStatus.WARNING,
            f"{len(entries)} recent kernel error-level message(s) found.",
            evidence=entries[:50],
            recommendation="Review the saved report; messages can be historical and are not automatically assigned to a component.",
        )

    def check_gpio(self) -> TestResult:
        chips = sorted(str(path) for path in Path("/dev").glob("gpiochip*"))
        if chips:
            return self.result(
                "gpio",
                ResultStatus.PASS,
                "GPIO character device detected.",
                evidence=chips,
                recommendation="Use a known-safe external circuit for a physical pin test.",
            )
        return self.result(
            "gpio",
            ResultStatus.NOT_AVAILABLE,
            "No GPIO character device is exposed.",
            recommendation="GPIO may be unavailable due to OS configuration or permissions.",
        )

    def check_interface(self, name: str, path_prefix: str, key: str) -> TestResult:
        parent = Path(path_prefix).parent
        prefix = Path(path_prefix).name
        found = (
            sorted(str(path) for path in parent.glob(prefix + "*"))
            if parent.exists()
            else []
        )
        if found:
            return self.result(
                key,
                ResultStatus.PASS,
                f"{name} device interface is enabled.",
                evidence=found,
            )
        return self.result(
            key,
            ResultStatus.NOT_AVAILABLE,
            f"{name} device interface is not enabled or exposed.",
            recommendation=f"Enable {name} in Raspberry Pi Configuration only if your robotics project requires it.",
        )

    def check_camera(self) -> TestResult:
        command = self.runner.run(["libcamera-hello", "--list-cameras"], timeout=12)
        if not command.available:
            command = self.runner.run(["rpicam-hello", "--list-cameras"], timeout=12)
        if not command.available:
            return self.result(
                "camera",
                ResultStatus.NOT_AVAILABLE,
                "No libcamera/rpicam utility is installed.",
                recommendation="Install the standard camera applications if a camera is part of the project.",
            )
        combined = f"{command.stdout}\n{command.stderr}"
        if command.returncode == 0 and re.search(
            r"Available cameras|[0-9]+\s*:\s*", combined, re.IGNORECASE
        ):
            return self.result(
                "camera",
                ResultStatus.PASS,
                "Camera utility completed its safe inventory check.",
                evidence=[combined],
            )
        if "no cameras" in combined.lower() or "0 available" in combined.lower():
            return self.result(
                "camera",
                ResultStatus.NOT_AVAILABLE,
                "No camera was detected.",
                evidence=[combined],
                recommendation="Connect a supported camera before testing this interface.",
            )
        return self.result(
            "camera",
            ResultStatus.WARNING,
            "Camera inventory did not complete cleanly.",
            evidence=[combined],
            recommendation="Review the report and check camera cabling/configuration.",
        )


MANUAL_TESTS = [
    (
        "usb_ports",
        "USB ports",
        "Connect a known-good USB keyboard, mouse, or flash drive to each USB port. Confirm each device is detected and remains stable.",
    ),
    (
        "ethernet_link",
        "Ethernet link and traffic",
        "Connect a known-good Ethernet cable to a live network. Confirm link LEDs and test a known local/network connection.",
    ),
    (
        "hdmi",
        "HDMI output",
        "Test each micro-HDMI port separately with a known-good display and cable. Confirm a stable image and audio if required.",
    ),
    (
        "audio",
        "Audio output",
        "Test the intended audio route, such as HDMI or a USB sound device, with known-good speakers/headphones.",
    ),
    (
        "camera_connector",
        "CSI camera connector",
        "With power disconnected, inspect and correctly seat a supported camera ribbon cable. Then run the camera inventory check.",
    ),
    (
        "gpio_pins",
        "GPIO header",
        "With power disconnected, inspect header pins for bent/damaged pins. Use a known-safe, voltage-correct circuit for functional pin testing.",
    ),
    (
        "wireless_range",
        "Wi-Fi and Bluetooth range",
        "Test connection stability at the normal operating distance. Adapter detection alone does not verify antenna/range performance.",
    ),
    (
        "cooling",
        "Cooling under intended workload",
        "Observe temperature during the real robotics workload. This application intentionally does not run a stress test.",
    ),
]
