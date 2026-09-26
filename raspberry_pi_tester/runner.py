from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    available: bool
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.available and not self.timed_out and self.returncode == 0


class CommandRunner:
    """Small, shell-free wrapper for read-only diagnostic commands."""

    def __init__(self, default_timeout: float = 8.0) -> None:
        self.default_timeout = default_timeout

    def exists(self, executable: str) -> bool:
        return shutil.which(executable) is not None

    def run(
        self, command: Sequence[str], timeout: float | None = None
    ) -> CommandResult:
        args = tuple(str(part) for part in command)
        if not args or not self.exists(args[0]):
            return CommandResult(
                args,
                False,
                None,
                "",
                f"Command not found: {args[0] if args else '(empty)'}",
            )
        try:
            completed = subprocess.run(
                args,
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout if timeout is not None else self.default_timeout,
                check=False,
            )
            return CommandResult(
                args,
                True,
                completed.returncode,
                completed.stdout.strip(),
                completed.stderr.strip(),
            )
        except subprocess.TimeoutExpired as error:
            LOG.warning("Timed out: %s", args)
            return CommandResult(
                args,
                True,
                None,
                (error.stdout or "").strip(),
                (error.stderr or "").strip(),
                True,
            )
        except OSError as error:
            LOG.exception("Could not run %s", args)
            return CommandResult(args, True, None, "", str(error))
