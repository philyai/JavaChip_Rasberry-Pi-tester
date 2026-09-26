from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ResultStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    MANUAL = "MANUAL TEST REQUIRED"
    NOT_AVAILABLE = "NOT AVAILABLE"
    NOT_TESTED = "NOT TESTED"


class Health(str, Enum):
    UNKNOWN = "UNKNOWN"
    GOOD = "GOOD"
    WARNING = "WARNING"
    PROBLEM = "PROBLEM DETECTED"


@dataclass(slots=True)
class TestResult:
    key: str
    name: str
    status: ResultStatus = ResultStatus.NOT_TESTED
    summary: str = "Not tested yet."
    details: str = ""
    evidence: list[str] = field(default_factory=list)
    recommendation: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: str = ""

    def finish(self) -> TestResult:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def overall_health(results: list[TestResult]) -> Health:
    """Calculate health without treating untested/unknown checks as a pass."""
    statuses = {result.status for result in results}
    if ResultStatus.FAIL in statuses:
        return Health.PROBLEM
    if ResultStatus.WARNING in statuses:
        return Health.WARNING
    if ResultStatus.PASS in statuses:
        return Health.GOOD
    return Health.UNKNOWN
