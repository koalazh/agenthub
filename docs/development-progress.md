# Development progress

This file records verified implementation increments without changing the
approved design specification.

## Design-to-module map

| Design responsibility | AgentHub module |
| --- | --- |
| Backend/BFF and health | `src/agenthub/api` |
| AgentHub SQLite | `src/agenthub/db`, `alembic` |
| Hermes compatibility/integration | `src/agenthub/hermes` |
| Typed Harness and compiler | `src/agenthub/harness` (Milestone 1) |
| Worker lanes | `src/agenthub/workers` (Milestones 2-4) |
| Workspace and artifacts | `src/agenthub/workspace`, `src/agenthub/artifacts` (Milestones 2/5) |
| Goal-centric UI | `web` (Milestone 6) |

## Hermes baseline

- Checkout: `/Users/koala/work/hermes-agent`
- Commit: `2a8d2174173ab8d05d0b48a44580a8c0b2c8c19b`
- Describe: `v2026.5.16-1097-g2a8d21741`
- Package version: `0.14.0`
- Public lifecycle API verified: `create_board`, `create_task`, `claim_task`,
  `heartbeat_claim`, `complete_task`, `block_task`
- Gateway API verified: `/health`, `/health/detailed`, `/v1/runs`, run events,
  approval, and stop endpoints

## Milestone 0

Commit: `chore: initialize agenthub project`

Completed: Python and frontend projects, configuration, SQLite/Alembic baseline,
health API, CI, and truthful Hermes installation/API/Gateway/Kanban diagnostics.

Tests: Ruff, Pytest, frontend production build, migration from an empty data
directory, live `agenthub serve` health requests.

Known limits: Hermes API/Gateway is not running on this machine; the health
response reports it unavailable. No Kanban board is initialized yet.

Next: Goal domain, typed Harness IR, validation, immutable versions/patches,
event store, and REST API.

## Goal domain increment

Commit: `feat(domain): add goal contract and lifecycle`

Completed: Immutable GoalContract and delivery policy, typed Goal states, legal
transition enforcement, terminal-state protection, and Completion Controller
authority for the completed state.

Tests: Domain validation, contract immutability, legal/illegal transitions,
automatic-merge rejection, and completion authority.

Known limits: Persistence and HTTP creation are part of the following
Milestone 1 increments.

Next: Typed Harness IR and static validation.

## Typed Harness increment

Commit: `feat(harness): add typed harness IR`

Completed: Strict Harness IR v1 models for all seven MVP node kinds, generated
JSON Schema, dependency and cycle checks, Runtime policy bounds, static Agent
run estimates, mandatory Runtime Gate/finalize checks, independent Reviewer
constraints, and bounded repair-loop inheritance.

Tests: Valid IR, unknown node rejection, untyped field rejection, mandatory
gates, dependency references/cycles, bounds, independent Review, Agent run cap,
loop inheritance, and committed-schema consistency.

Known limits: Harness versions and patches are not persisted yet.

Next: AgentHub database models, immutable Harness versions/patch validation,
event store, compilation summary, and REST API.

## Goal and Harness persistence increment

Commit: `feat(api): persist goals and harness versions`

Completed: Goal/Harness/Event SQLite models and migration, atomic Goal and
Harness events, immutable Logical IR history, optimistic Patch base-version
checks, semantic-contract hash protection, bounded Patch count, typed Patch
operations, deterministic Physical Plan summaries, and Goal/Harness/Event REST
endpoints.

Tests: API creation and restart recovery, initial compilation, version lineage,
immutable prior IR, semantic hash preservation, audit events, stale/invalid
Patch rejection, patch-count bounds, Goal identity validation, and finalize
reachability.

Known limits: Physical Plans are not materialized into Hermes Kanban until
Milestone 2. Event delivery is JSON polling; SSE arrives in Milestone 6.

Next: Hermes Kanban Adapter, task mapping, FakeWorker, Artifact Store, Runtime
Gate, reconciliation, and restart recovery.
