from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from agenthub.harness.schema import HarnessStep, ProgressiveHarness, StrictModel


class AddStepOperation(StrictModel):
    op: Literal["add_step"]
    after: str | None = None
    step: HarnessStep


class ReplaceStepOperation(StrictModel):
    op: Literal["replace_step"]
    step_id: str
    step: HarnessStep

    @model_validator(mode="after")
    def preserve_step_identity(self) -> "ReplaceStepOperation":
        if self.step.id != self.step_id:
            raise ValueError("replacement step id must equal step_id")
        return self


class RemoveStepOperation(StrictModel):
    op: Literal["remove_step"]
    step_id: str


PatchOperation = Annotated[
    AddStepOperation | ReplaceStepOperation | RemoveStepOperation,
    Field(discriminator="op"),
]


class PatchHarnessProposal(StrictModel):
    base_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    operations: tuple[PatchOperation, ...] = Field(min_length=1)
    generated_by: str = Field(default="hermes://agenthub-hub", min_length=1)


class HarnessPatchError(ValueError):
    pass


def parse_patch(payload: dict[str, object]) -> PatchHarnessProposal:
    try:
        return PatchHarnessProposal.model_validate(payload)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        raise HarnessPatchError("; ".join(errors)) from exc


def apply_patch(
    harness: ProgressiveHarness, proposal: PatchHarnessProposal
) -> ProgressiveHarness:
    steps = list(harness.steps)
    for operation in proposal.operations:
        ids = [step.id for step in steps]
        if isinstance(operation, AddStepOperation):
            if operation.step.id in ids:
                raise HarnessPatchError(f"step {operation.step.id} already exists")
            if operation.after is None:
                steps.append(operation.step)
            else:
                if operation.after not in ids:
                    raise HarnessPatchError(f"after step {operation.after} does not exist")
                steps.insert(ids.index(operation.after) + 1, operation.step)
        elif isinstance(operation, ReplaceStepOperation):
            if operation.step_id not in ids:
                raise HarnessPatchError(f"step {operation.step_id} does not exist")
            steps[ids.index(operation.step_id)] = operation.step
        else:
            if operation.step_id not in ids:
                raise HarnessPatchError(f"step {operation.step_id} does not exist")
            steps.pop(ids.index(operation.step_id))
    return harness.model_copy(update={"steps": tuple(steps)})
