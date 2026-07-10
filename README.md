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

For the frontend:

```bash
cd web
npm install
npm run dev
```

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
