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

## Hermes Kanban Adapter increment

Commit: `feat(hermes): add kanban task kernel adapter`

Completed: Feature-detected thin Adapter over the real Hermes public Kanban
API, stable per-project Board naming, idempotent Task creation, lifecycle
claim/heartbeat/complete/block calls, expected Run protection, task/event
snapshots, and the machine-readable AgentHub Task header.

Tests: Real Hermes `0.14.0` temporary Board lifecycle, idempotent Task key,
heartbeat, stale Run completion rejection, completion events, body header, Board
slug bounds, and incompatible API rejection.

Known limits: No AgentHub Step mapping or Worker execution is part of this
increment.

Next: Persist Task mappings and materialize executable steps, then execute them
through FakeWorker and reconcile results.

## Worker contract and Artifact increment

Commit: `feat(runtime): add fake worker and artifact store`

Completed: Runtime-neutral Worker request/handle/event/result contracts, the
full normalized MVP event vocabulary, deterministic success/failure/cancel
FakeAdapter behavior, and an atomic local Artifact Store with mandatory
Goal/Task/Run/Agent provenance, SHA256, size, media type, and database metadata.

Tests: Adapter success/failure/cancel event sequences, normalized result and
output artifacts, Artifact content/hash persistence, and missing-provenance
rejection.

Known limits: The FakeAdapter result is not yet committed into Hermes lifecycle
state; only Runtime will perform that commit in the next increment.

Next: HarnessRun/StepExecution/TaskMapping persistence and the reconciled Fake
vertical slice with deterministic Runtime Gate.

## Hermes Fake vertical slice increment

Commit: `feat(runtime): execute fake harness on hermes kanban`

Completed: Recoverable HarnessRun/StepExecution/TaskMapping state, idempotent
Physical Plan materialization into Hermes Kanban, isolated Git Worktrees for
write tasks, projected local TaskEnvelope, Runtime-owned Worker result commit,
deterministic Gate execution, independent fake Review, Completion Policy,
Artifact API, restart reconciliation, and Goal cancellation.

Tests: Full Goal-to-completed path on real Hermes Kanban, five Task mappings,
candidate/Test/Review Artifact requirements, independent Reviewer, Worktree
branch isolation and idempotency, restart without duplicate Tasks, Gate failure,
Worker failure, cancellation/archival, and Artifact retrieval. CI checks out the
pinned Hermes commit so these tests do not silently skip there.

Known limits: The Fake slice rejects `parallel` and `loop` execution; bounded
repair-loop execution arrives with Review hardening. Candidate Commit content is
a Fake Artifact until the real Worker/Worktree delivery increments.

Next: Hermes Hub Profile, Orchestrator Skill/MCP tools, TaskEnvelope/Handoff
schema, and real Hermes Profile Worker lane.

## Context projection and Hermes Profiles increment

Commit: `feat(context): add task envelopes and hermes profiles`

Completed: Strict TaskEnvelope v1 and Handoff v1 models/schemas, 8 KB Handoff
bound, least-context projection without global Harness state, installable
`agenthub-hub` and `hermes-reviewer` Hermes Profile distributions, and the Hub
Orchestrator Skill with Proposal/Runtime boundaries.

Tests: Local projection permissions and Artifact authorization, absence of
global Harness fields, Handoff size rejection, committed-schema consistency,
pinned Hermes manifest parsing, MCP declaration, and credential/Memory exclusion.

Known limits: The declared `agenthub mcp-server` command and Hermes Profile
Worker Adapter are implemented in the following increments.

Next: AgentHub Control MCP proposal tools, followed by the Hermes Profile Lane.

## AgentHub Control MCP increment

Commit: `feat(mcp): expose agenthub control proposals`

Completed: Pinned official MCP SDK, stdio `agenthub mcp-server`, and Hub tools
for Goal creation, Harness submission/Patch, Goal query/list, Runtime launch,
and cancellation. Tools call Backend proposal endpoints and surface validation
rejections; they never write authoritative state directly.

Tests: MCP tool discovery allowlist, proposal endpoint routing, and Runtime
validation-error propagation.

Known limits: Approval and merge tools arrive with their persisted domain
flows. Live Hermes Profile model execution requires user provider credentials
and remains optional in the core suite.

Next: Hermes Profile Worker Adapter and reconciliation with native Dispatcher
lifecycle.

## Hermes Profile Lane increment

Commit: `feat(adapter): add hermes profile worker lane`

Completed: Unified Hermes Profile Worker Adapter backed by the native Hermes
Dispatcher, explicit Agent ID-to-Profile binding, normalized Kanban lifecycle
events, comment input, cancellation through archive, terminal result collection,
and duplicate-event cursoring. AgentHub does not spawn a parallel Hermes loop or
write Hermes tables.

Tests: Native Dispatcher spawn callback, claim/completion normalization,
idempotent event streaming, Profile binding, comment input, cancel/archive, and
terminal WorkerResult mapping on a temporary real Hermes Board.

Known limits: A live model-backed Profile run is credential-dependent and is
not part of the paid-model-free core suite.

Next: Agent Registry/Resolver and External Lane Supervisor with Codex and Claude
Adapters.
