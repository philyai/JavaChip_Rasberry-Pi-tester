"""LDROBOT LD19/D300 USB diagnostic support.

The wire format and CRC are taken from the LD19 Development Manual and the
LDROBOT ldlidar SDK.  This module deliberately has no GUI dependency so its
parser and health decisions can be exercised without a physical sensor.
"""

from __future__ import annotations

import errno
import statistics
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

BAUDRATE = 230400
HEADER = 0x54
VER_LEN = 0x2C
POINTS_PER_PACKET = 12
PACKET_LENGTH = 47
MIN_SCAN_HZ = 5.0
MAX_SCAN_HZ = 13.0


def _ld19_crc_table() -> tuple[int, ...]:
    """Build the complete 256-entry table used by LDROBOT's CrcTable."""
    table = []
    for value in range(256):
        crc = value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x4D) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        table.append(crc)
    return tuple(table)


# The LDROBOT SDK table is CRC-8 polynomial 0x4D, initial value 0x00, no xorout.
CRC_TABLE = _ld19_crc_table()


def ld19_crc(data: bytes) -> int:
    """Return the documented LD19 CRC-8 for all frame bytes except CRC."""
    crc = 0
    for value in data:
        crc = CRC_TABLE[(crc ^ value) & 0xFF]
    return crc


@dataclass(frozen=True, slots=True)
class LD19Point:
    angle_deg: float
    distance_mm: int
    confidence: int


@dataclass(frozen=True, slots=True)
class LD19Packet:
    speed_dps: int
    start_angle_deg: float
    end_angle_deg: float
    timestamp_ms: int
    points: tuple[LD19Point, ...]
    raw: bytes


class LD19StreamParser:
    """Buffered, self-resynchronising parser for normal LD19 measurement frames."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.valid_packets = 0
        self.invalid_packets = 0
        self.crc_failures = 0
        self.discarded_bytes = 0

    def feed(self, data: bytes) -> list[LD19Packet]:
        self.buffer.extend(data)
        packets: list[LD19Packet] = []
        while True:
            header_at = self.buffer.find(bytes((HEADER,)))
            if header_at < 0:
                # Keep no arbitrary trailing byte: a header is one byte.
                self.discarded_bytes += len(self.buffer)
                self.buffer.clear()
                break
            if header_at:
                self.discarded_bytes += header_at
                del self.buffer[:header_at]
            if len(self.buffer) < 2:
                break
            if self.buffer[1] != VER_LEN:
                self.invalid_packets += 1
                self.discarded_bytes += 1
                del self.buffer[0]
                continue
            if len(self.buffer) < PACKET_LENGTH:
                break
            frame = bytes(self.buffer[:PACKET_LENGTH])
            if ld19_crc(frame[:-1]) != frame[-1]:
                self.invalid_packets += 1
                self.crc_failures += 1
                # Discard only this header so a valid frame embedded after a
                # corrupt length/header can still be found on the next pass.
                self.discarded_bytes += 1
                del self.buffer[0]
                continue
            packets.append(self._parse_frame(frame))
            self.valid_packets += 1
            del self.buffer[:PACKET_LENGTH]
        return packets

    @staticmethod
    def _parse_frame(frame: bytes) -> LD19Packet:
        speed = int.from_bytes(frame[2:4], "little")
        start_raw = int.from_bytes(frame[4:6], "little")
        end_raw = int.from_bytes(frame[42:44], "little")
        start = start_raw / 100.0
        end = end_raw / 100.0
        # A packet crossing 359.99 -> 0.00 is a forward, not negative, span.
        span = (end - start) % 360.0
        points: list[LD19Point] = []
        for index in range(POINTS_PER_PACKET):
            offset = 6 + index * 3
            distance = int.from_bytes(frame[offset : offset + 2], "little")
            confidence = frame[offset + 2]
            fraction = index / (POINTS_PER_PACKET - 1)
            points.append(
                LD19Point((start + span * fraction) % 360.0, distance, confidence)
            )
        return LD19Packet(
            speed_dps=speed,
            start_angle_deg=start,
            end_angle_deg=end,
            timestamp_ms=int.from_bytes(frame[44:46], "little"),
            points=tuple(points),
            raw=frame,
        )


@dataclass(slots=True)
class LD19Metrics:
    """Observed values only. No simulated values are ever introduced here."""

    packet_times: list[float] = field(default_factory=list)
    speeds_dps: list[int] = field(default_factory=list)
    distances_mm: list[int] = field(default_factory=list)
    confidences: list[int] = field(default_factory=list)
    observations: list[LD19Point] = field(default_factory=list)
    angle_bins: set[int] = field(default_factory=set)
    rotations: int = 0
    continuity_gaps: int = 0
    _last_start_angle: float | None = None
    _last_packet_time: float | None = None

    def record(self, packets: Iterable[LD19Packet], observed_at: float) -> None:
        for packet in packets:
            if (
                self._last_packet_time is not None
                and observed_at - self._last_packet_time > 0.5
            ):
                self.continuity_gaps += 1
            if (
                self._last_start_angle is not None
                and packet.start_angle_deg + 30 < self._last_start_angle
            ):
                self.rotations += 1
            self._last_start_angle = packet.start_angle_deg
            self._last_packet_time = observed_at
            self.packet_times.append(observed_at)
            self.speeds_dps.append(packet.speed_dps)
            for point in packet.points:
                self.angle_bins.add(int(point.angle_deg) % 360)
                if 20 <= point.distance_mm <= 12000:
                    self.distances_mm.append(point.distance_mm)
                    self.confidences.append(point.confidence)
                    self.observations.append(point)

    @property
    def scan_hz(self) -> float | None:
        return statistics.fmean(self.speeds_dps) / 360.0 if self.speeds_dps else None

    @property
    def point_rate(self) -> float | None:
        if len(self.packet_times) < 2:
            return None
        elapsed = self.packet_times[-1] - self.packet_times[0]
        return (
            len(self.packet_times) * POINTS_PER_PACKET / elapsed
            if elapsed > 0
            else None
        )

    @property
    def angular_coverage_deg(self) -> int:
        return len(self.angle_bins)

    def distance_summary(self) -> tuple[int, int, float] | None:
        if not self.distances_mm:
            return None
        return (
            min(self.distances_mm),
            max(self.distances_mm),
            statistics.median(self.distances_mm),
        )


class SerialLike(Protocol):
    def read(self, size: int = 1) -> bytes: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SerialCandidate:
    device: str
    description: str = ""
    hwid: str = ""


@dataclass(slots=True)
class LD19Capture:
    port: str | None = None
    parser: LD19StreamParser = field(default_factory=LD19StreamParser)
    metrics: LD19Metrics = field(default_factory=LD19Metrics)
    error_kind: str = ""
    error_detail: str = ""
    disconnected: bool = False

    @property
    def valid_packets(self) -> int:
        return self.parser.valid_packets


def classify_serial_error(error: BaseException) -> str:
    text = str(error).lower()
    if (
        isinstance(error, PermissionError)
        or "permission denied" in text
        or "access is denied" in text
    ):
        return "PERMISSION DENIED"
    if getattr(error, "errno", None) in {errno.EBUSY, errno.EAGAIN} or any(
        word in text
        for word in (
            "resource busy",
            "device or resource busy",
            "in use",
            "cannot access",
        )
    ):
        return "PORT BUSY"
    if getattr(error, "errno", None) in {errno.ENODEV, errno.ENOENT, errno.EIO} or any(
        word in text
        for word in (
            "no such file",
            "filenotfounderror",
            "system cannot find",
            "disconnected",
            "input/output error",
        )
    ):
        return "LD19 DISCONNECTED"
    return "SERIAL ERROR"


class LD19Diagnostic:
    """Bounded raw-serial detector and diagnostic; it owns one port at a time."""

    def __init__(
        self,
        serial_factory: Callable[[str], SerialLike] | None = None,
        port_provider: Callable[[], list[SerialCandidate]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._serial_factory = serial_factory
        self._port_provider = port_provider
        self._clock = clock

    @staticmethod
    def is_lidar_serial_candidate(candidate: SerialCandidate) -> bool:
        """Return whether a serial port can plausibly be a wired LiDAR.

        Windows creates Bluetooth virtual COM ports for paired devices. They
        are not a D300 USB connection, so omit them while retaining physical
        COM and USB UART ports.
        """
        device = candidate.device.upper()
        description = candidate.description.upper()
        hwid = candidate.hwid.upper()
        if "BTHENUM" in hwid or "BLUETOOTH" in description:
            return False
        return device.startswith(("/DEV/TTYUSB", "/DEV/TTYACM", "/DEV/SERIAL", "COM"))

    @staticmethod
    def available_ports() -> list[SerialCandidate]:
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        ports = []
        for port in list_ports.comports():
            candidate = SerialCandidate(
                str(port.device), str(port.description or ""), str(port.hwid or "")
            )
            # The development kit is normally USB serial, but do not reject a
            # legitimate USB UART merely because its Windows COM name varies.
            if LD19Diagnostic.is_lidar_serial_candidate(candidate):
                ports.append(candidate)
        return ports

    def candidates(self) -> list[SerialCandidate]:
        return self._port_provider() if self._port_provider else self.available_ports()

    def _open(self, device: str) -> SerialLike:
        if self._serial_factory:
            return self._serial_factory(device)
        try:
            import serial
        except ImportError as error:
            raise RuntimeError("pyserial is not installed") from error
        try:
            return serial.Serial(
                device, BAUDRATE, timeout=0.15, write_timeout=0.15, exclusive=True
            )
        except TypeError:  # pyserial/platform combination without exclusive support
            return serial.Serial(device, BAUDRATE, timeout=0.15, write_timeout=0.15)

    def capture_port(
        self, device: str, duration: float, min_consecutive: int = 0
    ) -> LD19Capture:
        capture = LD19Capture(port=device)
        serial_port: SerialLike | None = None
        try:
            serial_port = self._open(device)
            deadline = self._clock() + duration
            consecutive = 0
            while self._clock() < deadline:
                try:
                    data = serial_port.read(512)
                except OSError as error:
                    capture.error_kind = classify_serial_error(error)
                    capture.error_detail = str(error)
                    capture.disconnected = capture.error_kind == "LD19 DISCONNECTED"
                    break
                now = self._clock()
                if not data:
                    continue
                packets = capture.parser.feed(data)
                capture.metrics.record(packets, now)
                consecutive = consecutive + len(packets) if packets else 0
                if min_consecutive and consecutive >= min_consecutive:
                    break
        except (OSError, RuntimeError) as error:
            capture.error_kind = classify_serial_error(error)
            capture.error_detail = str(error)
        finally:
            if serial_port is not None:
                try:
                    serial_port.close()
                except OSError:
                    pass
        return capture

    def auto_detect(
        self, timeout_per_port: float = 2.5, max_total_seconds: float = 12.0
    ) -> LD19Capture:
        candidates = self.candidates()
        if not candidates:
            return LD19Capture(
                error_kind="NOT CONNECTED",
                error_detail="No USB serial candidates were found.",
            )
        last = LD19Capture(
            error_kind="NOT CONNECTED",
            error_detail="No candidate produced verified LD19 frames.",
        )
        deadline = self._clock() + max_total_seconds
        for candidate in candidates:
            remaining = deadline - self._clock()
            if remaining <= 0:
                last.error_detail = "LD19 autodetection time limit reached before all candidates could be sampled."
                break
            capture = self.capture_port(
                candidate.device, min(timeout_per_port, remaining), min_consecutive=5
            )
            if capture.valid_packets >= 5:
                return capture
            # A stale/disconnected candidate merely means it is not the LiDAR;
            # preserve actionable ownership/permission failures instead.
            if capture.error_kind in {"PORT BUSY", "PERMISSION DENIED"}:
                last = capture
        return last

    def run(self, duration: float = 10.0) -> LD19Capture:
        detected = self.auto_detect()
        if detected.valid_packets < 5 or not detected.port:
            return detected
        return self.capture_port(detected.port, duration)

    def distance_check(
        self, target_mm: int, duration: float = 3.0
    ) -> tuple[LD19Capture, float | None]:
        """Measure the median in the forward +/-10 degree region of a target."""
        detected = self.auto_detect()
        if detected.valid_packets < 5 or not detected.port:
            return detected, None
        capture = self.capture_port(detected.port, duration)
        values = [
            point.distance_mm
            for point in capture.metrics.observations
            if point.angle_deg <= 10.0 or point.angle_deg >= 350.0
        ]
        return capture, statistics.median(values) if values else None


def health_assessment(capture: LD19Capture) -> tuple[str, str, list[str]]:
    """Return status token, user summary, and reportable evidence for an LD19 run."""
    metrics = capture.metrics
    evidence = [
        "device=LDROBOT LD19",
        "development_kit=D300",
        f"baud={BAUDRATE}",
        f"serial_port={capture.port or 'not detected'}",
        f"valid_packets={capture.valid_packets}",
        f"invalid_packets={capture.parser.invalid_packets}",
        f"crc_failures={capture.parser.crc_failures}",
        f"complete_rotations={metrics.rotations}",
        f"angular_coverage_degrees={metrics.angular_coverage_deg}",
        f"continuity_gaps={metrics.continuity_gaps}",
    ]
    if capture.error_kind:
        evidence.append(f"serial_error={capture.error_detail}")
        return "NOT_AVAILABLE", capture.error_kind, evidence
    if not capture.port:
        return "NOT_AVAILABLE", "NOT CONNECTED", evidence
    scan_hz = metrics.scan_hz
    point_rate = metrics.point_rate
    if scan_hz is not None:
        evidence.append(f"measured_scan_hz={scan_hz:.2f}")
    if point_rate is not None:
        evidence.append(f"measured_point_rate={point_rate:.0f}")
    distance = metrics.distance_summary()
    if distance:
        evidence.extend(
            (
                f"minimum_valid_distance_mm={distance[0]}",
                f"maximum_valid_distance_mm={distance[1]}",
                f"median_valid_distance_mm={distance[2]:.1f}",
                f"valid_distance_readings={len(metrics.distances_mm)}",
            )
        )
    if capture.valid_packets == 0:
        return "FAIL", "No CRC-verified LD19 packets were received.", evidence
    if metrics.rotations < 2 or metrics.angular_coverage_deg < 330:
        return (
            "FAIL",
            "Valid packets arrived but the scanner did not demonstrate multiple 360-degree rotations.",
            evidence,
        )
    if not distance:
        return (
            "FAIL",
            "Valid packets arrived but no valid distance readings were decoded.",
            evidence,
        )
    warnings = []
    if scan_hz is None or not MIN_SCAN_HZ <= scan_hz <= MAX_SCAN_HZ:
        warnings.append("scan rate is outside the normal 5-13 Hz operating region")
    if metrics.continuity_gaps:
        warnings.append("one or more data-stream gaps were observed")
    if (
        capture.parser.crc_failures
        and capture.parser.crc_failures > capture.valid_packets * 0.05
    ):
        warnings.append("CRC failures exceed 5% of valid packets")
    if warnings:
        return (
            "WARNING",
            "LD19 data is functional, but " + "; ".join(warnings) + ".",
            evidence,
        )
    return (
        "PASS",
        "LD19/D300 stream is stable with verified packets, rotations, angular coverage, and distance data.",
        evidence,
    )
