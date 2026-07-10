# AgentHub MVP acceptance map

`agenthub_design_spec.md` remains the product and architecture source of truth.
This file maps its MVP completion criteria to executable evidence.

| Criterion | Implementation evidence | Automated evidence |
| --- | --- | --- |
| Durable Goal and Contract | Goal/Event tables and API | `tests/api/test_goals.py` |
| Typed, immutable Harness versions and Patch audit | Harness schema, validator, compiler, version repository | `tests/harness/test_validator.py`, `tests/api/test_goals.py` |
| Hermes Kanban Task Kernel | Public Kanban Adapter and Task mappings | `tests/hermes/test_kanban_adapter.py` |
| Unified heterogeneous Workers | Fake, Hermes Profile, Codex, and Claude Adapters | `tests/workers`, configured-lane Runtime tests |
| Isolated code writes | Git Worktree provisioning and candidate inspection | `tests/workspace/test_manager.py`, Runtime vertical slice |
| Artifact provenance and Handoff context firewall | Artifact Store, Handoff records, TaskEnvelope projection | `tests/artifacts`, `tests/context`, Runtime vertical slice |
| Deterministic tests and Runtime Gate | Shell-free Gate Runner and required test-log Artifact | `tests/gates`, Gate failure Runtime test |
| Independent semantic Review | Agent exclusion, strict ReviewResult, read-only integrity check | Harness and Runtime Review tests |
| Bounded repair | Typed Loop physical expansion with repair/gate/review rounds | Review repair pass/exhaustion Runtime tests |
| Candidate Commit and explicit merge | Verified Commit metadata, durable Approval, fast-forward-only merge | candidate approval Runtime tests |
| Cancellation and waiting | Kanban archive, persisted WaitApproval, Hermes unblock | cancellation and Approval Runtime tests |
| Restart recovery | Idempotent materialization and explicit lost-supervision reconciliation | restart Runtime tests |
| API, Web, SSE, and Channel link | Goal APIs, resumable events, Hermes Runs proxy, session links | API tests and frontend build |
| Runtime limits and usage | Static and execution-time run, loop, wall-time, and cost bounds | validator and Runtime budget tests |

## Final local verification

```bash
uv run agenthub db-upgrade
uv run agenthub doctor
uv run ruff check .
uv run pytest
cd web && npm run build
```

The paid-model-free acceptance path exercises real temporary Hermes Boards,
native Dispatcher mechanics, real Git repositories and Worktrees, Runtime Gate
commands, Review decisions, and candidate Commits. Provider-backed smoke tests
remain optional because they require user credentials and can incur cost.
