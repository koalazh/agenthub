import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

from agenthub.workers.base import (
    AgentRuntimeDescriptor,
    ProducedArtifact,
    WorkerEvent,
    WorkerEventType,
    WorkerFailure,
    WorkerHandle,
    WorkerResult,
    WorkerResultStatus,
    WorkerStartRequest,
)


@dataclass
class _FakeRun:
    request: WorkerStartRequest
    result: WorkerResult
    canceled: bool = False


class FakeWorkerAdapter:
    def __init__(
        self,
        *,
        fail: bool = False,
        review_decisions: tuple[str, ...] = ("pass",),
        usage: dict[str, object] | None = None,
    ) -> None:
        self._fail = fail
        self._review_decisions = deque(review_decisions)
        self._usage = usage or {}
        self._runs: dict[str, _FakeRun] = {}

    async def describe(self) -> AgentRuntimeDescriptor:
        return AgentRuntimeDescriptor(
            id="fake://default",
            runtime="fake",
            capabilities=("code-analysis", "code-implementation", "code-review"),
            max_parallel_runs=1,
        )

    async def start(self, request: WorkerStartRequest) -> WorkerHandle:
        handle = WorkerHandle(id=f"fake_{uuid4().hex}", adapter_id="fake://default")
        if self._fail:
            result = WorkerResult(
                status=WorkerResultStatus.FAILED,
                summary="Fake worker failed",
                failure=WorkerFailure(type="PERMANENT_FAILURE", message="configured failure"),
            )
        else:
            outputs = request.task_envelope.get("output_contract", {}).get("artifacts", [])
            artifacts: list[ProducedArtifact] = []
            for kind in outputs:
                if kind == "review_report":
                    decision = (
                        self._review_decisions.popleft()
                        if self._review_decisions
                        else "pass"
                    )
                    artifacts.append(
                        ProducedArtifact(
                            kind="review_report",
                            filename="review_report.json",
                            media_type="application/json",
                            content=json.dumps(
                                {"decision": decision, "findings": []}
                            ).encode(),
                        )
                    )
                else:
                    artifacts.append(
                        ProducedArtifact(
                            kind=str(kind),
                            filename=f"{kind}.txt",
                            content=f"Fake artifact for {request.task_id}: {kind}\n".encode(),
                        )
                    )
            result = WorkerResult(
                status=WorkerResultStatus.COMPLETED,
                summary=f"Fake worker completed {request.task_id}",
                artifacts=tuple(artifacts),
                usage=self._usage,
            )
        self._runs[handle.id] = _FakeRun(request=request, result=result)
        return handle

    async def stream_events(self, handle: WorkerHandle) -> AsyncIterator[WorkerEvent]:
        run = self._get_run(handle)
        yield WorkerEvent(type=WorkerEventType.ACCEPTED)
        yield WorkerEvent(type=WorkerEventType.STARTED)
        if run.canceled:
            yield WorkerEvent(type=WorkerEventType.CANCELED)
            return
        yield WorkerEvent(type=WorkerEventType.PROGRESS, payload={"percent": 100})
        for artifact in run.result.artifacts:
            yield WorkerEvent(
                type=WorkerEventType.ARTIFACT_CREATED,
                payload={"kind": artifact.kind, "filename": artifact.filename},
            )
        terminal = (
            WorkerEventType.COMPLETED
            if run.result.status is WorkerResultStatus.COMPLETED
            else WorkerEventType.FAILED
        )
        yield WorkerEvent(type=terminal)

    async def send_input(self, handle: WorkerHandle, payload: dict[str, object]) -> None:
        self._get_run(handle)

    async def cancel(self, handle: WorkerHandle) -> None:
        run = self._get_run(handle)
        run.canceled = True
        run.result = WorkerResult(
            status=WorkerResultStatus.CANCELED,
            summary=f"Fake worker canceled {run.request.task_id}",
        )

    async def collect_result(self, handle: WorkerHandle) -> WorkerResult:
        return self._get_run(handle).result

    def _get_run(self, handle: WorkerHandle) -> _FakeRun:
        try:
            return self._runs[handle.id]
        except KeyError as exc:
            raise LookupError(f"unknown fake worker handle {handle.id}") from exc
