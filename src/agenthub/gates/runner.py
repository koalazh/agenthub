import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agenthub.harness.schema import GateCheck


@dataclass(frozen=True)
class CheckResult:
    name: str
    command: str
    returncode: int
    output: str


@dataclass(frozen=True)
class GateResult:
    passed: bool
    checks: tuple[CheckResult, ...]

    def log(self) -> bytes:
        sections = []
        for check in self.checks:
            sections.append(
                f"$ {check.command}\nreturncode: {check.returncode}\n{check.output}".rstrip()
            )
        return ("\n\n".join(sections) + "\n").encode()


class GateRunner:
    def run(self, checks: tuple[GateCheck, ...], *, workspace: Path) -> GateResult:
        results: list[CheckResult] = []
        for check in checks:
            try:
                completed = subprocess.run(
                    shlex.split(check.command),
                    cwd=workspace,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=check.timeout_seconds,
                )
                result = CheckResult(
                    name=check.name,
                    command=check.command,
                    returncode=completed.returncode,
                    output=completed.stdout + completed.stderr,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                result = CheckResult(
                    name=check.name,
                    command=check.command,
                    returncode=124 if isinstance(exc, subprocess.TimeoutExpired) else 127,
                    output=str(exc),
                )
            results.append(result)
            if result.returncode != 0:
                break
        return GateResult(
            passed=len(results) == len(checks) and all(item.returncode == 0 for item in results),
            checks=tuple(results),
        )
