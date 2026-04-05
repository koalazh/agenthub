---
name: self-evolution
description: Review past archives to find gaps in recorded knowledge. Use when self_evolution(agent_id) is called for periodic review. Checks what should have been recorded as skill/experience but was missed.
tools:
  allowed:
    - read_file
    - glob
    - write_file
    - edit_file
    - bash  # git commit, ls, stat
  read_only:
    - bash  # ls, stat only
context: inline
---

# Self Evolution Skill

Review past archives to find **gaps** - things that should have been recorded but weren't. Then prune redundant or outdated knowledge.

## Core Philosophy

> **Self-evolution is about gap-filling AND cleanup. Evolution captures immediate insights; self-evolution catches what was missed and removes what no longer matters.**
> **Favor Skill over API: API only triggers, all operations executed directly by LLM.**

Where evolution asks "what worked here?", self-evolution asks:
- "What skill should we have created but didn't?"
- "What experience contains knowledge that should be solidified into a skill?"
- "What important pattern only became clear in hindsight?"
- "What is now redundant or outdated and should be pruned?"

## Four-Stage Framework

```
┌─────────────────────────────────────────────────────────────┐
│  ORIENT: Understand the context                              │
│                                                             │
│  1. Read agent identity (soul.md, identity.md)               │
│  2. Scan existing skills and experiences                    │
│     - glob {skills_dir}/**/SKILL.md                        │
│     - glob {skills_dir}/../builtin_skills/**/SKILL.md      │
│     - glob {memory_dir}/**/*.experience.md                 │
│  3. List archives (glob {archives_dir}/*.json)              │
│  4. Read MEMORY.md to understand current state              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  GATHER: Review archives and find gaps                      │
│                                                             │
│  1. Read archives/*.json (sample if >10)                    │
│  2. Identify MISSED opportunities:                           │
│     - Topics discussed but not recorded                     │
│     - Experience content that should be a skill             │
│     - Patterns evolution missed                             │
│  3. Identify OUTDATED content:                              │
│     - Skills that contradict recent archives                │
│     - Experiences no longer relevant                        │
│     - Redundant skills with overlap                         │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  CONSOLIDATE: Plan changes to add/update                     │
│                                                             │
│  1. For each gap identified:                                │
│     - Decide: add_skill | update_skill | add_experience     │
│     - Determine path and content                             │
│  2. Check Pre-Flight (same as Evolution)                    │
│  3. Execute changes directly (LLM writes files)             │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  PRUNE: Remove redundant/outdated content                    │
│                                                             │
│  1. Apply protection rules (see below)                      │
│  2. For each item to prune:                                 │
│     - delete: Remove redundant skill/experience            │
│     - merge: Combine overlapping skills                     │
│     - demote: Convert skill to reference (deprecated)       │
│     - archive: Soft delete (move to .archive/)              │
│  3. Update MEMORY.md                                        │
│  4. Git commit all changes                                  │
└─────────────────────────────────────────────────────────────┘
```

## Gap Types (Gather Phase)

### Type 1: Missed Recording
Something important happened but evolution didn't record it.

```
Archive: "User asked about Python decorators. I explained them."
Existing: No skill or experience about decorators
Gap: → Create "python-decorators" skill
```

### Type 2: Experience → Skill
An experience contains knowledge worth solidifying.

```
Experience: "Remember to always close database connections in finally block"
Gap: → Create "resource-management" skill with this pattern
```

### Type 3: Project → Universal
A project-specific skill applies to other projects.

```
project-A skill: "handle-xml-parsing" exists
Archive in project-B: struggles with XML parsing
Gap: → Make "xml-parsing" universal or create shared pattern
```

### Type 4: Outdated Content (Prune)
Content that is now redundant, contradicted, or no longer relevant.

```
Skill: "always-use-var-instead-of-let"
Archive: User corrected agent - "in modern JS, const is preferred"
Gap: → Update or prune the outdated skill
```

## Prune Protection Rules

**The following content is protected; LLM must not delete or modify:**

| Rule | Condition | Check Method |
|------|-----------|--------------|
| **builtin_skills** | Path starts with `builtin_skills/` | Always skip |
| **#KEEP marker** | File contains `# KEEP` or `#KEEP` | Regex match at line start |
| **7-day protection** | File created < 7 days ago | `stat -r {path}` + date comparison |
| **Core identity** | Filename is `soul.md`, `identity.md`, `BOOTSTRAP.md` | Exact match |
| **Path traversal** | Path resolves outside agent_dir | Security check |

```
┌─────────────────────────────────────────────────────────────┐
│  PRUNE DECISION TREE                                        │
│                                                             │
│  Is path protected by any rule?                             │
│  ├─ Yes → SKIP, return error "protected: {reason}"         │
│  └─ No → Continue                                           │
│                                                             │
│  Is this content truly redundant/outdated?                  │
│  ├─ No → SKIP, return "not_prune_candidate"                │
│  └─ Yes → Proceed with prune action                         │
└─────────────────────────────────────────────────────────────┘
```

**7-Day Check Example (Cross-platform, Python-style)**:
```python
import time
from pathlib import Path

path = Path("skills/universal/my-skill/SKILL.md")
mtime = path.stat().st_mtime
if time.time() - mtime < 7 * 24 * 3600:
    print("PROTECTED: file is less than 7 days old")
```

## Prune Actions

### Delete
Remove file completely (irreversible).

```python
# Only for truly redundant files
delete_file(path)

# Example: duplicate skill that overlaps with another
# Path: skills/universal/old-duplicate-skill/SKILL.md
```

### Merge
Combine multiple similar files into one.

```python
# 1. Read all files to merge
# 2. write_file combined content to primary path
# 3. delete_file secondary paths
# 4. Update MEMORY.md

# Example: two skills about error handling → one "error-handling" skill
```

### Demote
Mark as deprecated, convert to reference.

```python
# 1. Add frontmatter: status: deprecated
# 2. Add deprecation notice at top
# 3. Update MEMORY.md to mark as reference

# Example: skill that is now outdated but might be useful for reference
```

### Archive
Soft delete - move to `.archive/` directory.

```python
# 1. Create .archive/ directory if not exists
# 2. Move file to .archive/{filename}.{timestamp}
# 3. Update MEMORY.md to remove entry
# 4. Archive can be recovered within 30 days

# Example: experience no longer relevant to current projects
```

## LLM Direct Execution

**All file operations are executed directly by LLM; API layer performs no operations.**

### Adding a Skill

```python
# 1. Create directory
mkdir skills/universal/{skill_name}/

# 2. Write SKILL.md with standardized frontmatter
write_file(
  path="skills/universal/{skill_name}/SKILL.md",
  content=f"""---
name: {skill_name}
description: {description}
type: agent|hub|utility|reference
scope: universal|project_specific
version: 1.0.0
author: agentcore
tags: []
updated: {timestamp}
---

# {skill_name}

## When to Use

{trigger_context}

## How to Use

{steps}

## Example

{example}
"""
)

# 3. Update MEMORY.md (add new skill entry)
#    See MEMORY.md constraints below before updating

# 4. Git commit
git add -A && git commit -m "SelfEvolution: +skill {skill_name}"
```

### Adding an Experience (4-type)

```python
# 1. Determine experience type using 4-type classification:
#    user → user preferences/communication style
#    feedback → corrections, confirmations, rejections
#    project → project-specific context
#    reference → external references

# 2. Create experience file with standardized frontmatter
write_file(
  path="memory/projects/{scope}/{experience_type}.experience.md",
  content=f"""---
name: {topic}
description: {one_line_description}
type: experience
experience_type: {experience_type}
projects: [{project_ids}]
version: 1.0.0
author: agentcore
tags: []
updated: {timestamp}
---

# Experience: {topic}

## What Happened

{what_happened}

## Key Insight

{key_insight}

## Lesson

{lesson}
"""
)

# 3. Update MEMORY.md (add new experience entry)
#    See MEMORY.md constraints below before updating

# 4. Git commit
git add -A && git commit -m "SelfEvolution: +experience {topic}"
```

### MEMORY.md Constraints

**Before updating MEMORY.md index, verify constraints**:

| Constraint | Limit | Action if Exceeded |
|------------|-------|-------------------|
| Max lines | ≤200 | Skip write, log warning |
| Max size | ≤25KB (25600 bytes) | Skip write, log warning |
| Max line length | <150 chars | Truncate long lines |

```python
# Check before write
line_count = len(read_file("MEMORY.md").splitlines())
file_size = len(read_file("MEMORY.md").encode())
longest_line = max(len(line) for line in read_file("MEMORY.md").splitlines())

if line_count >= 200:
    log("MEMORY.md exceeds 200 lines, skipping index update")
    skip MEMORY.md update
elif file_size > 25600:
    log("MEMORY.md exceeds 25KB, skipping index update")
    skip MEMORY.md update
elif longest_line >= 150:
    log("MEMORY.md has lines >=150 chars, truncating")
    truncate long lines before write
```

### Pruning

```python
# Example: Delete redundant skill
if action == "delete":
    delete_file(path)
    # Update MEMORY.md - remove the index line for deleted file
    # Check MEMORY.md constraints before writing

# Example: Archive outdated experience
if action == "archive":
    archive_path = f".archive/{filename}.{timestamp}"
    move_file(path, archive_path)
    # Update MEMORY.md - remove the index line for archived file
    # Check MEMORY.md constraints before writing

# Example: Merge overlapping skills
if action == "merge":
    content1 = read_file(path1)
    content2 = read_file(path2)
    merged = merge_content(content1, content2)
    write_file(path1, merged)
    delete_file(path2)
    # Update MEMORY.md - remove merged file's index, update primary file's index
    # Check MEMORY.md constraints before writing

# Example: Demote outdated skill
if action == "demote":
    content = read_file(path)
    updated = "---\nstatus: deprecated\n---\n" + content
    write_file(path, updated)
    # Update MEMORY.md - update the index line to reflect demotion
    # Check MEMORY.md constraints before writing
```

**MEMORY.md Index Sync for Prune**:
- When deleting/archive a file: remove its index line from MEMORY.md
- When merging: update primary file's index, remove merged file's index
- When demoting: update index to reflect new status (reference type)
- Always check MEMORY.md constraints (≤200 lines, ≤25KB, <150 chars/line) before writing

### Git Commit Pattern

```bash
git add -A && git commit -m "SelfEvolution: prune {action} {path}"
git add -A && git commit -m "SelfEvolution: +skill {name}"
```

## Output Format

```json
{
  "hasChanges": true|false,
  "changes": [
    {
      "type": "add_skill|update_skill|add_experience|prune",
      "action": "create|merge|delete|demote|archive|null",
      "path": "skills/universal/{name}/SKILL.md",
      "skillName": "optional-name",
      "scope": "universal|project_specific",
      "experienceType": "user|feedback|project|reference",
      "projects": ["project_id"],
      "reason": "Why this change is needed",
      "confidence": "high|medium|low"
    }
  ],
  "pruneErrors": [
    {
      "path": "skills/universal/old-skill/SKILL.md",
      "code": "PRUNE_PROTECTED",
      "reason": "File has #KEEP marker"
    }
  ],
  "commitHash": "git commit hash"
}
```

## Quality Bar

Self-evolution has a **higher bar** than evolution:

| Factor | Evolution | Self-Evolution |
|--------|-----------|----------------|
| Trigger | 1 clear case | 1 case + significance |
| Evidence | This task worked | Archives confirm pattern |
| Value | Useful | Significantly better than existing |

**Key difference**: Evolution trusts the agent's judgment. Self-evolution cross-checks against archives.

## Anti-Patterns

| Pattern | Problem | Solution |
|---------|---------|----------|
| Duplicate skill | Already exists | Check first |
| Incremental update | Already covered elsewhere | Verify no gap |
| Vague pattern | Can't create actionable guidance | Skip |
| Low-value addition | Complexity > benefit | Skip |
| Prune protected | Protected content | Skip |
| Premature prune | Still useful content | Don't prune |

## Context Variables

The task provides:
- `archives_dir`: Path to archives directory (for glob scanning)
- `skills_dir`: Path to skills directory (for glob scanning)
- `memory_dir`: Path to memory directory (for glob scanning)

**API layer only passes directory paths; scanning is done autonomously by LLM via glob. LLM reads/writes/deletes files directly and commits via git.**
