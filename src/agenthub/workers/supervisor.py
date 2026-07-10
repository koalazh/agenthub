from dataclasses import dataclass

from agenthub.workers.base import (
    WorkerAdapter,
    WorkerEvent,
    WorkerHandle,
    WorkerResult,
    WorkerStartRequest,
)


@dataclass(frozen=True)
class SupervisedResult:
    handle: WorkerHandle
    events: tuple[WorkerEvent, ...]
    result: WorkerResult


class ExternalLaneSupervisor:
    def __init__(self, adapters: dict[str, WorkerAdapter]) -> None:
        self._adapters = adapters

    async def run(self, request: WorkerStartRequest) -> SupervisedResult:
        try:
            adapter = self._adapters[request.agent_id]
        except KeyError as exc:
            raise LookupError(f"no Worker Adapter registered for {request.agent_id}") from exc
        handle = await adapter.start(request)
        events = tuple([event async for event in adapter.stream_events(handle)])
        result = await adapter.collect_result(handle)
        return SupervisedResult(handle=handle, events=events, result=result)

    async def cancel(self, agent_id: str, handle: WorkerHandle) -> None:
        try:
            adapter = self._adapters[agent_id]
        except KeyError as exc:
            raise LookupError(f"no Worker Adapter registered for {agent_id}") from exc
        await adapter.cancel(handle)
