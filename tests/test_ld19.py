from __future__ import annotations

import unittest

from raspberry_pi_tester.ld19 import (
    HEADER,
    PACKET_LENGTH,
    VER_LEN,
    LD19Capture,
    LD19Diagnostic,
    LD19Metrics,
    LD19StreamParser,
    SerialCandidate,
    classify_serial_error,
    health_assessment,
    ld19_crc,
)


def frame(
    start_centidegrees: int = 0, end_centidegrees: int = 1100, speed: int = 3600
) -> bytes:
    """A protocol-shaped software fixture, never a claimed hardware capture."""
    payload = bytearray((HEADER, VER_LEN))
    payload.extend(speed.to_bytes(2, "little"))
    payload.extend(start_centidegrees.to_bytes(2, "little"))
    for index in range(12):
        payload.extend((1000 + index).to_bytes(2, "little"))
        payload.append(120 + index)
    payload.extend(end_centidegrees.to_bytes(2, "little"))
    payload.extend((1234).to_bytes(2, "little"))
    payload.append(ld19_crc(bytes(payload)))
    assert len(payload) == PACKET_LENGTH
    return bytes(payload)


class ReadThenDisconnect:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False

    def read(self, _size: int = 1) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        raise OSError("device disconnected")

    def close(self) -> None:
        self.closed = True


class EmptySerial:
    def read(self, _size: int = 1) -> bytes:
        return b""

    def close(self) -> None:
        pass


class AdvancingClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.1
        return self.value


class LD19ParserTests(unittest.TestCase):
    def test_crc_matches_documented_packet(self) -> None:
        # Example frame from the LD19 Development Manual: final CRC is 0x50.
        documented = bytes.fromhex(
            "54 2c 68 08 ab 7e e0 00 e4 dc 00 e2 d9 00 e5 d5 00 e3 "
            "d3 00 e4 d0 00 e9 cd 00 e4 ca 00 e2 c7 00 e9 c5 00 e5 "
            "c2 00 e5 c0 00 e5 be 82 3a 1a 50"
        )
        self.assertEqual(len(documented), PACKET_LENGTH)
        self.assertEqual(ld19_crc(documented[:-1]), 0x50)

    def test_parses_header_distance_confidence_angles_speed_and_timestamp(self) -> None:
        parser = LD19StreamParser()
        packet = parser.feed(frame(35000, 1000))[0]
        self.assertEqual(packet.speed_dps, 3600)
        self.assertEqual(packet.timestamp_ms, 1234)
        self.assertEqual(packet.points[0].distance_mm, 1000)
        self.assertEqual(packet.points[0].confidence, 120)
        self.assertAlmostEqual(packet.points[0].angle_deg, 350.0)
        self.assertAlmostEqual(packet.points[-1].angle_deg, 10.0)
        self.assertEqual(parser.valid_packets, 1)

    def test_rejects_invalid_crc_and_modified_payload(self) -> None:
        parser = LD19StreamParser()
        corrupted = bytearray(frame())
        corrupted[10] ^= 0x01
        self.assertEqual(parser.feed(bytes(corrupted)), [])
        self.assertEqual(parser.crc_failures, 1)
        self.assertEqual(parser.invalid_packets, 1)

    def test_truncated_frame_waits_for_more_bytes(self) -> None:
        parser = LD19StreamParser()
        packet = frame()
        self.assertEqual(parser.feed(packet[:-1]), [])
        self.assertEqual(parser.valid_packets, 0)
        self.assertEqual(len(parser.feed(packet[-1:])), 1)

    def test_garbage_then_frame_resynchronises(self) -> None:
        parser = LD19StreamParser()
        packets = parser.feed(b"\x00\x55garbage" + frame())
        self.assertEqual(len(packets), 1)
        self.assertGreater(parser.discarded_bytes, 0)

    def test_two_consecutive_frames_and_split_reads(self) -> None:
        parser = LD19StreamParser()
        stream = frame() + frame(1200, 2300)
        output = []
        for part in (stream[:5], stream[5:61], stream[61:]):
            output.extend(parser.feed(part))
        self.assertEqual(len(output), 2)
        self.assertEqual(parser.valid_packets, 2)

    def test_corrupt_frame_does_not_prevent_next_valid_frame(self) -> None:
        parser = LD19StreamParser()
        broken = bytearray(frame())
        broken[-1] ^= 0xFF
        packets = parser.feed(bytes(broken) + frame(2000, 3100))
        self.assertEqual(len(packets), 1)
        self.assertEqual(parser.crc_failures, 1)


class LD19DiagnosticTests(unittest.TestCase):
    def test_bluetooth_virtual_com_ports_are_not_lidar_candidates(self) -> None:
        bluetooth = SerialCandidate(
            "COM6", "Standard Serial over Bluetooth link (COM6)", "BTHENUM\\device"
        )
        usb_uart = SerialCandidate(
            "COM9", "USB Serial Device (COM9)", "USB VID:PID=10C4:EA60"
        )
        self.assertFalse(LD19Diagnostic.is_lidar_serial_candidate(bluetooth))
        self.assertTrue(LD19Diagnostic.is_lidar_serial_candidate(usb_uart))

    def _healthy_capture(self) -> LD19Capture:
        parser = LD19StreamParser()
        metrics = LD19Metrics()
        # Thirty-four 11-degree packets cross zero twice and provide nearly all
        # angle bins, two rotations, distances, and a 10 Hz speed estimate.
        for index in range(70):
            start = (index * 1100) % 36000
            packets = parser.feed(frame(start, (start + 1100) % 36000))
            metrics.record(packets, index * 0.01)
        return LD19Capture(port="/dev/ttyUSB7", parser=parser, metrics=metrics)

    def test_health_pass_warning_and_fail_logic(self) -> None:
        capture = self._healthy_capture()
        status, _summary, evidence = health_assessment(capture)
        self.assertEqual(status, "PASS")
        self.assertTrue(
            any(item.startswith("measured_scan_hz=10") for item in evidence)
        )
        capture.metrics.speeds_dps = [7200]
        self.assertEqual(health_assessment(capture)[0], "WARNING")
        capture.metrics.rotations = 0
        self.assertEqual(health_assessment(capture)[0], "FAIL")

    def test_disconnect_and_permission_are_classified_and_closed(self) -> None:
        serial_port = ReadThenDisconnect([frame()])
        diagnostic = LD19Diagnostic(serial_factory=lambda _device: serial_port)
        capture = diagnostic.capture_port("/dev/ttyUSB0", duration=0.02)
        self.assertEqual(capture.error_kind, "LD19 DISCONNECTED")
        self.assertTrue(serial_port.closed)
        self.assertEqual(
            classify_serial_error(PermissionError("permission denied")),
            "PERMISSION DENIED",
        )
        self.assertEqual(
            classify_serial_error(OSError(16, "Device or resource busy")), "PORT BUSY"
        )

    def test_missing_candidate_is_not_a_pass(self) -> None:
        capture = LD19Diagnostic(port_provider=list).auto_detect()
        self.assertEqual(capture.error_kind, "NOT CONNECTED")
        self.assertEqual(health_assessment(capture)[0], "NOT_AVAILABLE")

    def test_timeout_busy_permission_and_reconnect_paths(self) -> None:
        timeout_capture = LD19Diagnostic(
            serial_factory=lambda _device: EmptySerial(), clock=AdvancingClock()
        ).capture_port("/dev/ttyUSB0", duration=0.3)
        self.assertEqual(timeout_capture.valid_packets, 0)
        self.assertEqual(timeout_capture.error_kind, "")

        def busy(_device: str):
            raise OSError(16, "Device or resource busy")

        def denied(_device: str):
            raise PermissionError("permission denied")

        self.assertEqual(
            LD19Diagnostic(serial_factory=busy)
            .capture_port("/dev/ttyUSB0", 0.01)
            .error_kind,
            "PORT BUSY",
        )
        self.assertEqual(
            LD19Diagnostic(serial_factory=denied)
            .capture_port("/dev/ttyUSB0", 0.01)
            .error_kind,
            "PERMISSION DENIED",
        )

        # A retry gets a fresh serial handle; no handle is retained after the
        # first disconnect.
        connections = [ReadThenDisconnect([]), ReadThenDisconnect([frame()])]
        diagnostic = LD19Diagnostic(serial_factory=lambda _device: connections.pop(0))
        self.assertEqual(
            diagnostic.capture_port("/dev/ttyUSB0", 0.01).error_kind,
            "LD19 DISCONNECTED",
        )
        reconnected = diagnostic.capture_port("/dev/ttyUSB0", 0.01)
        self.assertEqual(reconnected.valid_packets, 1)
        self.assertEqual(reconnected.error_kind, "LD19 DISCONNECTED")

    def test_auto_detection_requires_several_valid_frames(self) -> None:
        diagnostic = LD19Diagnostic(
            serial_factory=lambda _device: ReadThenDisconnect([frame() * 5]),
            port_provider=lambda: [SerialCandidate("/dev/ttyACM1")],
        )
        capture = diagnostic.auto_detect()
        self.assertEqual(capture.port, "/dev/ttyACM1")
        self.assertGreaterEqual(capture.valid_packets, 5)
