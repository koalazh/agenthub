import sys
from pathlib import Path

from agenthub.gates.runner import GateRunner
from agenthub.harness.schema import GateCheck


def test_gate_runner_records_passing_command(tmp_path: Path) -> None:
    result = GateRunner().run(
        (
            GateCheck(
                name="tests",
                command=f'{sys.executable} -c "print(\'passed\')"',
            ),
        ),
        workspace=tmp_path,
    )

    assert result.passed
    assert result.checks[0].returncode == 0
    assert b"passed" in result.log()


def test_gate_runner_stops_after_failure(tmp_path: Path) -> None:
    result = GateRunner().run(
        (
            GateCheck(name="fail", command=f'{sys.executable} -c "raise SystemExit(2)"'),
            GateCheck(name="never", command=f'{sys.executable} -c "print(1)"'),
        ),
        workspace=tmp_path,
    )

    assert not result.passed
    assert len(result.checks) == 1
    assert result.checks[0].returncode == 2
