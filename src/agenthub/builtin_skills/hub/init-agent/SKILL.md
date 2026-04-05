---
name: init-agent
description: Initialize a new agent with bootstrap files using a three-phase framework (ORIENT/GENERATE/FINALIZE). Use when init_agent(agent_id, config) is called to create a new agent's identity and base configuration.
---

# Init Agent Skill

Create a new agent with properly structured bootstrap files using a three-phase framework. The agent's identity lives in these files and evolves through use.

## Three-Phase Framework

### Phase 1: ORIENT — Understand Context

```
┌─────────────────────────────────────────────────────────────┐
│  ORIENT: Understand Context                                 │
│                                                             │
│  1. Read context (name, identity, traits, agent_id,        │
│     personality, pokemon_data)                               │
│  2. If personality is null, generate based on              │
│     Pokemon type/abilities                                  │
│  3. Use glob to check if agent_id directory already exists │
│  4. Plan bootstrap file structure                           │
│  5. Apply Pre-Flight Check                                 │
└─────────────────────────────────────────────────────────────┘
```

**Responsibilities**: API layer passes context and agent_id, and pre-copies builtin skills. API layer has already written Pokemon companion data to companion.json. Skill layer is responsible for generating personality and writing bootstrap files (soul.md, identity.md, BOOTSTRAP.md).

**Pokemon Companion**:
- Pokemon companion data is stored in companion.json (written by API layer)
- If `context.personality` is null, LLM should generate personality based on `context.pokemon_data` type/abilities
- Pokemon type influences personality (e.g., electric type → energetic, quick-tempered)
- Do NOT write Pokemon data to soul.md - soul.md should only contain agent identity and personality

### Phase 2: GENERATE — Generate Bootstrap Files

**IMPORTANT**: You MUST use the `write_file` tool to actually create the bootstrap files. Do not assume files exist - you must create them.

**NOTE**: Builtin skills (evolution, self-evolution) are copied by the API layer before Skill execution. You only need to write the bootstrap files.

```
┌─────────────────────────────────────────────────────────────┐
│  GENERATE: Generate Bootstrap Files                         │
│                                                             │
│  1. Use write_file tool to write soul.md (based on identity│
│     and traits)                                             │
│  2. Use write_file tool to write identity.md (role def.)    │
│  3. Use write_file tool to write BOOTSTRAP.md (memory arch)│
└─────────────────────────────────────────────────────────────┘
```

### Phase 3: FINALIZE — Finalize

```
┌─────────────────────────────────────────────────────────────┐
│  FINALIZE: Finalize                                         │
│                                                             │
│  1. Git init (if not initialized)                           │
│  2. Git add -A                                              │
│  3. Git commit (using name)                                │
│  4. Return InitAgentResult                                  │
└─────────────────────────────────────────────────────────────┘
```

## Tools Specification

```yaml
tools:
  allowed:
    - read_file
    - glob
    - write_file
    - bash  # git init, git add, git commit, mkdir
  read_only:
    - bash  # ls, stat only
context: inline
```

## Pre-Flight Check

**Use tools to check; do not assume paths exist.**

Validate before writing files:

```python
# 1. Check if agent_id directory already exists
# Note: agent_id directory is provided in context, use glob tool to check
existing = glob(f"{context.agent_id}/*")
if existing:
    return {"error": "AGENT_EXISTS", "agent_id": context.agent_id}

# 2. Validate context parameters
if not context.get("name"):
    return {"error": "MISSING_NAME"}
```

**Important**:
- Do not assume paths like `/agenthub` or `~/.agenthub` exist
- Use `glob` tool to verify files actually exist
- `files_written` array must contain files actually created via `write_file`

## Output Schema

**IMPORTANT**: Only return the JSON object below. Do NOT include any additional text, explanations, or fields outside this JSON structure.

```json
{
  "phase": "FINALIZE",
  "hasChanges": true,
  "inspirationSeed": 123456789,
  "agent_name": "Midnight",
  "personality": "A curious helper who loves debugging",
  "files_written": ["soul.md", "identity.md", "BOOTSTRAP.md"],
  "git_commit": "abc1234"
}
```

### InitAgentResult Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `phase` | string | Yes | Current phase: ORIENT / GENERATE / FINALIZE |
| `hasChanges` | bool | Yes | Whether files were changed |
| `inspirationSeed` | int/null | No | LLM-generated random seed (can be null) |
| `agent_name` | string | Yes | LLM-generated agent name |
| `personality` | string | Yes | LLM-generated personality description |
| `files_written` | array | Yes | **Must** be the list of filenames actually created via `write_file` tool (filename only, no path, e.g., `["soul.md", "identity.md"]`) |
| `git_commit` | string/null | No | Git commit hash |

## Bootstrap File Frontmatter

### soul.md frontmatter

**Note**: Pokemon companion data is stored in companion.json (written by API layer). Skill layer writes soul.md without Pokemon frontmatter.

```yaml
---
name: {agent_name}-soul
type: core
updated: {timestamp}
---
```

**Skill layer update**: Write soul.md with agent identity, personality, and traits only. Do NOT include pokemon data in soul.md.

### identity.md frontmatter

```yaml
---
name: {name}-identity
type: core
updated: {timestamp}
---
```

### BOOTSTRAP.md frontmatter

```yaml
---
name: {name}-bootstrap
type: core
updated: {timestamp}
---
```

## Bootstrap File Principles

### 1. soul.md — The Agent's Essence

**What it is**: Core identity that persists across all tasks.

**Design principles**:
- Keep it personal and distinctive — this is what makes the agent "them"
- Focus on **how** it thinks, not **what** it knows
- Behavioral guidelines > knowledge statements
- Communication style reveals personality

**Anti-patterns**:
- Don't include task-specific knowledge
- Don't make it generic ("I am a helpful AI assistant")

### 2. identity.md — The Agent's Role

**What it is**: Clear statement of purpose and boundaries.

**Design principles**:
- Specific about what problems it solves
- Explicit about constraints and boundaries
- Defines approach to problem-solving

### 3. BOOTSTRAP.md — Memory Architecture

**What it is**: Instructions for how the agent retrieves memories and discovers skills.

**Design principles**:
- Minimal — just the recall mechanism
- Point to where memories live, not the memories themselves
- Memory is runtime data, not bootstrap data

## Git Operations

```bash
# Initialize (if needed)
git init

# Add all files
git add -A

# Initial commit
git commit -m "InitAgent: create {name}"
```

## File Creation Order

1. **First**: soul.md — establish identity
2. **Second**: identity.md — define role
3. **Third**: BOOTSTRAP.md — set up recall

## Context Fields

| Field | Source | Description |
|-------|--------|-------------|
| `name` | API layer computed | Agent name (may come from Pokemon name or user input) |
| `personality` | User input or LLM generated | Agent personality (null means LLM should generate based on Pokemon) |
| `identity` | User input | Agent role description |
| `traits` | User input | List of personality traits |
| `agent_id` | API layer generated | Unique identifier; Skill uses this ID to create directories and files |
| `pokemon_data` | API layer generated | Pokemon Companion data (type, abilities, etc.) |

## Error Handling

When an error is detected, **must** return the JSON format below; **do not** return natural language explanations:

```json
{
  "error": "AGENT_EXISTS",
  "agent_id": "the-agent-id"
}
```

| Error Code | Description | Handling |
|------------|-------------|----------|
| `AGENT_EXISTS` | Agent already exists | Return error JSON, do not overwrite |
| `MISSING_NAME` | Missing name parameter | Return error JSON |
| `SKILL_EXECUTION_ERROR` | Skill execution failed | Return error JSON |
| `GIT_INIT_ERROR` | Git initialization failed | Return `git_commit: null`, continue |

## Anti-Patterns

| Pattern | Problem | Solution |
|---------|---------|----------|
| Generic soul.md | "I am a helpful AI" - not distinctive | Include specific traits and communication style |
| Overly long files | Cognitive overhead, not readable | Keep soul.md < 50 lines, identity.md < 20 lines |
| No Pre-Flight Check | Risk of overwriting existing agent | Always verify agent_id doesn't exist |
| No git init | No audit trail | Always initialize git on first creation |
| Hardcoded paths | Not portable | Use context variables for all paths |
| Skipping skill copy | Agent can't self-evolve | (API Layer handles this automatically) |
| Inconsistent voice | Confusing identity | Keep tone consistent across bootstrap files |

## Quality Checklist

Before finalizing:
- [ ] soul.md is under 50 lines, distinctive, personality shows
- [ ] identity.md is under 20 lines, clear role and boundaries
- [ ] BOOTSTRAP.md is under 30 lines, just recall mechanism
- [ ] No contradictions between files
- [ ] Voice/style is consistent across files
- [ ] Git commit message uses agent name
- [ ] At least 5 anti-patterns avoided
