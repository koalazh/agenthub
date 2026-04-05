# AgentHub

**Python 3.13+** · **MIT License**

🌐 选择语言 / Select Language:
[简体中文](README.md) | [English](README.en.md)

---

Think **GitHub for agents**. AgentHub manages agent configurations and evolution history.

Each Agent is a directory of config files (`soul.md`, `identity.md`, `skills/`, `memory/`) that evolves automatically with task execution, with Git tracking the complete evolution history.

## Core Concepts

### Agent as Configuration

```
GitHub:        repo/ → git log → code evolution history
AgentHub:      {agent}/ → git log → behavior evolution history
```

Agent directory structure:

> **Path Note**: Built-in skill templates in the source code are located in `builtin_skills/`. When an Agent is initialized, they are copied to the runtime location `skills/builtin/`.

```
{agent_id}/
├── .git/                        # Git repository, tracks evolution
├── soul.md                       # Identity definition
├── identity.md                   # Role definition
├── BOOTSTRAP.md               # Recall instructions
├── skills/                       # Skill definitions (runtime)
│   ├── builtin/                # Built-in skills (copied from builtin_skills/)
│   ├── universal/              # Universal skills (from evolution)
│   │   └── {skill_name}/
│   │       └── SKILL.md
│   └── projects/               # Project-specific skills
│       └── {project}/
│           └── {skill_name}/
│               └── SKILL.md
├── memory/                       # Experience accumulation
│   └── projects/
│       ├── universal/
│       │   └── experience.md
│       └── {project}/
│           └── experience.md
└── archives/                    # Task archives (not in git)
    └── {archive_id}.json
```

### Evolution as Commit

```
Git commit:
file changes → git add → git commit -m "fix: bug"

Evolution commit:
task completes → analyze transcript → decide what to record →
  → skill: create/update skills/{name}.md
  → experience: append to memory/projects/*/experience.md
  → git add + commit
```

`evolution()` — Analyze a single task, like a single commit
`self_evolution()` — Review past archives, find gaps, ensure important knowledge isn't missed

### Evolution Control

- **Revertible** — Any historical commit can be manually reverted
- **Traceable** — `git log` is the Agent's growth timeline
- **Append-only** — Evolution outputs are always appended, never overwritten
- **Ship of Theseus** — Agent evolves continuously, core identity remains stable

## Tech Stack

AgentHub is built on the following core technologies:

- **[deepagents](https://github.com/deepagents/deepagents)** — Agent infrastructure
- **[LangGraph](https://langchain-ai.github.io/langgraph/)** — Agent workflow orchestration
- **[LangChain](https://python.langchain.com/)** — LLM integration and tool ecosystem
- **FastAPI** — HTTP API service
- **GitPython** — Git version control integration

## Installation

```bash
git clone https://github.com/your-org/agenthub.git
cd agenthub

uv pip install -e .  # recommended
pip install .
```

## Quick Start

### Configuration

```bash
cp .env.example .env
# Add your API key
```

### Create an Agent

```python
from agenthub import init_agent
from agenthub.core.types import InitAgentConfig

agent = await init_agent(InitAgentConfig(
    name="my-agent",
    identity="A helpful coding assistant",
    traits=["helpful", "python-expert"],
))

print(agent.path)  # Agent directory, Git initialized
```

### Analyze After Task Completion

```python
from agenthub import evolution
from agenthub.core.types import RawTranscriptInput

result = await evolution(agent.id, RawTranscriptInput(
    id="session-001",
    content="User asked me to fix a race condition...",
    project_id="project-1",
))

if result.should_record:
    # Created skills/xxx/SKILL.md
    # Git commit made
    print(f"Recorded: {result.skill_name}")
```

### View Evolution History

```bash
cd ~/.agenthub/{agent_id}
git log --oneline
```

## API Reference

### Python API

| Function | Description |
|----------|-------------|
| `init_agent(config)` | Create a new Agent (initializes Git repo) |
| `get_agent(agent_id)` | Get Agent info |
| `list_agents()` | List all Agents |
| `delete_agent(agent_id)` | Delete an Agent |
| `evolution(agent_id, transcript)` | Analyze task, create commit |
| `self_evolution(agent_id)` | Review archives, find gaps, create or update skills |
| `rollback_agent(request)` | Rollback Agent to specified commit (HEAD~N or hash) |
| `get_evolution_history(agent_id, limit, offset)` | Get Agent evolution history (paginated) |
| `export_agent_config(agent_id, project_id)` | Export Claude Code CLI configuration |

Streaming versions available with `_stream` suffix.

### HTTP API

FastAPI HTTP endpoints for external callers (e.g., agentcenter):

```bash
uvicorn agenthub.api.routes:app --host 0.0.0.0 --port 8000
```

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/agents` | Create a new Agent |
| `GET` | `/agents` | List all Agents |
| `GET` | `/agents/{agent_id}` | Get Agent details |
| `DELETE` | `/agents/{agent_id}` | Delete an Agent |
| `POST` | `/evolution/start` | Trigger Evolution analysis |
| `POST` | `/self-evolution/start` | Trigger Self-Evolution |
| `GET` | `/export/claude-code` | Export Claude Code CLI configuration |
| `POST` | `/evolution/rollback` | Rollback to specified version |
| `GET` | `/evolution/history` | Get evolution history |
| `GET` | `/health` | Health check |

Full documentation: `/docs` (Swagger UI)

## Configuration

| Environment Variable | Default |
|---------------------|---------|
| `AGENTHUB_DIR` | `~/.agenthub` |
| `MODEL_NAME` | `anthropic:claude-sonnet-4-6` |

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest tests/ -v
uv run mypy src/
uv run ruff check src/
uv build
```

## Changelog

### v0.1.0 (2026-03-27)

- Initial release
- Agent lifecycle management
- Git-managed evolution system
- Evolution and Self-Evolution
- Built-in Skills
- Rollback history reversion
- Evolution history query
- Claude Code CLI configuration export
- FastAPI HTTP API

## License

MIT License - see LICENSE file for details
