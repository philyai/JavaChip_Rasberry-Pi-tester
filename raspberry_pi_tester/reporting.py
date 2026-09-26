from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .diagnostics import DiagnosticSuite
from .models import TestResult, overall_health


def make_report(results: list[TestResult], suite: DiagnosticSuite) -> dict:
    return {
        "report_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "application": "Raspberry Pi 4B Hardware Tester",
        "overall_health": overall_health(results).value,
        "device_information": suite.device_information(),
        "results": [result.to_dict() for result in results],
        "important_note": "PASS means this specific safe diagnostic observed the stated condition. It does not prove that all hardware is fault-free. MANUAL TEST REQUIRED and NOT AVAILABLE are not passes.",
    }


def report_text(report: dict) -> str:
    lines = [
        "Raspberry Pi 4B Hardware Tester report",
        "=" * 44,
        f"Generated: {report['generated_at']}",
        f"Overall health: {report['overall_health']}",
        "",
        "Device information",
    ]
    lines.extend(
        f"{key}: {value}" for key, value in report["device_information"].items()
    )
    lines.extend(["", "Diagnostic results"])
    for item in report["results"]:
        lines.extend(
            (
                f"[{item['status']}] {item['name']}: {item['summary']}",
                f"Details: {item['details']}" if item["details"] else "",
                f"Recommendation: {item['recommendation']}"
                if item["recommendation"]
                else "",
                "Evidence:",
                *(f"  - {entry}" for entry in item["evidence"] if entry),
                "",
            )
        )
    lines.append(report["important_note"])
    return "\n".join(line for line in lines if line is not None)


def save_report(
    destination: Path, results: list[TestResult], suite: DiagnosticSuite
) -> tuple[Path, Path]:
    report = make_report(results, suite)
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    json_path = destination / f"pi4b-hardware-report-{timestamp}.json"
    text_path = destination / f"pi4b-hardware-report-{timestamp}.txt"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    text_path.write_text(report_text(report), encoding="utf-8")
    return json_path, text_path
