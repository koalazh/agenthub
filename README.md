# AgentHub

AgentHub is a local, Goal-centric control plane that compiles typed progressive
harnesses into Hermes Kanban tasks and routes them to heterogeneous workers.

## Requirements

- Python 3.12+
- Node.js 22+
- Git
- A compatible Hermes Agent checkout or installation

## Local setup

```bash
uv sync --extra dev
cp .env.example .env
uv run agenthub db-upgrade
uv run agenthub doctor
uv run agenthub serve
```

The API listens on `http://127.0.0.1:8787`. Use `/health` for AgentHub liveness
and `/health/detailed` for database, Hermes API/Gateway, and Kanban diagnostics.
Hermes being unavailable is reported as a dependency status; it does not make
the AgentHub health endpoint claim that Hermes is running.

The `agenthub-hub` Hermes Profile connects to the control plane through its
declared stdio MCP command:

```bash
uv run agenthub mcp-server
```

Set `AGENTHUB_API_BASE_URL` if the Backend is not at
`http://127.0.0.1:8787`.

Run the Hermes API Server with `agenthub-hub` as its active Profile before
using `/api/chat` or the Web Hub Chat. AgentHub forwards chat turns to Hermes
`/v1/runs`; it does not embed another Agent loop. If the Hermes server requires
authentication, set the same key in `AGENTHUB_HERMES_API_KEY`. The Backend then
forwards the stable `X-Hermes-Session-Key` for Profile Memory scoping.

Worker routing defaults to the paid-model-free Fake lane. Set
`AGENTHUB_DEFAULT_WORKER_LANE` to `hermes`, `claude`, or `codex` to opt into a
configured real Worker. Codex uses its documented `exec --json` CLI fallback
inside the Adapter; Claude uses non-interactive `stream-json`. Both run only in
the Runtime-provisioned workspace and remain behind the same Worker contract.

For the frontend:

```bash
cd web
npm install
npm run dev
```

Keep `agenthub serve` running in another terminal. The development UI at
`http://127.0.0.1:5173` lists and creates Goals, shows task/Artifact/Approval
state, and refreshes from the resumable Goal event stream. The JSON event list
remains available by requesting `/api/goals/{goal_id}/events` without the
`text/event-stream` Accept header.

## Hermes compatibility baseline

Milestone 0 was verified against Hermes Agent source commit
`2a8d2174173ab8d05d0b48a44580a8c0b2c8c19b` (`v2026.5.16-1097-g2a8d21741`),
package version `0.14.0`. Set `AGENTHUB_HERMES_SOURCE_PATH` when Hermes is not
installed on `PATH`. Runtime integration uses Hermes public Kanban functions and
does not modify its database schema.

## Development checks

```bash
uv run ruff check .
uv run pytest
cd web && npm run build
```
