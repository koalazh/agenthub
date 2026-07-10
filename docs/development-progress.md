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
