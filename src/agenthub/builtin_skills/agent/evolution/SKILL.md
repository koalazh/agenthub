---
name: evolution
description: Analyze transcripts and decide if experiences should be solidified into Skills or Experiences. Use when evolution(agent_id, transcript) is called.
tools:
  allowed:
    - read_file
    - glob
    - write_file
    - edit_file
  read_only:
    - bash  # git commit only
context: inline
---

# Evolution Skill

Analyze what happened in a task and decide what (if anything) is worth preserving.

## Core Philosophy

> **Be restrained. Most experiences are not worth recording.**
> **Favor Skill over API: API only triggers, all operations executed directly by LLM.**

The goal is not to remember everything - it's to preserve what enables future excellence. A single insight that will change behavior is worth more than a detailed log of what happened.

## Three-Stage Framework

```
┌─────────────────────────────────────────────────────────────┐
│  ORIENT: Understand the context                              │
│                                                             │
│  1. Read the transcript (archive_path)                       │
│  2. Read agent identity (soul.md, identity.md)               │
│  3. Scan existing skills to avoid duplicates                │
│  4. Scan existing experiences                              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  GATHER: Identify patterns and insights                      │
│                                                             │
│  1. Analyze transcript for:                                 │
│     - Patterns that worked well                              │
│     - Mistakes to avoid in future                           │
│     - Solutions worth preserving                             │
│  2. Apply Pre-Flight Check (see below)                       │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  CONSOLIDATE: Make recording decision                        │
│                                                             │
│  1. Apply decision tree                                      │
│  2. If recording: write file + git commit                    │
│  3. Return EvolutionResult                                  │
└─────────────────────────────────────────────────────────────┘
```

### ORIENT Execution Steps

**Execute these steps to build context:**

1. **Read the transcript:**
   ```
   read_file({archive_path})
   ```

2. **Read agent identity files:**
   ```
   read_file({agent_dir}/soul.md)
   read_file({agent_dir}/identity.md)
   ```

3. **Scan existing skills (use glob tool):**
   ```
   glob {skills_dir}/**/SKILL.md
   glob {skills_dir}/../builtin_skills/**/SKILL.md
   ```
   Then read each skill file to understand existing patterns.

4. **Scan existing experiences (use glob tool):**
   ```
   glob {memory_dir}/**/*.experience.md
   ```
   Then read each experience file to avoid duplicates.

**Build lists of existing skills and experiences for deduplication.**

## Pre-Flight Check

**Must execute before recording any skill or experience**

```
Is this "derivable information" (code patterns, architecture, file paths)?
│
├─ Yes → SKIP, return shouldRecord: false, skipReason: "derivable-info"
│
└─ No → Continue
```

```
Is there an "authoritative source" already covering this?
│
├─ Yes → SKIP (git log/blame/CLAUDE.md already covers it)
│   └─ skipReason: "authoritative-source"
└─ No → Continue
```

```
Is this "ephemeral information" (in-progress work, temp state)?
│
├─ Yes → SKIP, return shouldRecord: false, skipReason: "ephemeral-info"
│
└─ No → Continue
```

```
Does this describe a specific fix (code change description)?
│
├─ Yes → SKIP (fix descriptions belong in code, not memory)
│   └─ skipReason: "fix-in-code"
└─ No → Continue to decision tree
```

**All 4 checks pass → Proceed to Skill vs Experience Decision Tree**

## Skill vs Experience Decision Tree

```
Was there a pattern that worked well or revealed something important?
│
├─ No → Return shouldRecord: false
│
└─ Yes → Is it repeatable across different contexts?
         │
         ├─ Yes → SKILL (universal)
         │
         └─ No → Is it specific to this project?
                  │
                  ├─ Yes → EXPERIENCE (project_specific)
                  │
                  └─ No → EXPERIENCE (universal)
```

## Experience 4-type Classification (Phase 3)

When deciding an Experience type, apply this decision tree:

```
Is it about the user's preferences or communication style?
├─ Yes → experience_type: "user"
└─ No → Continue

Is it about a correction, confirmation, or rejected approach?
├─ Yes → experience_type: "feedback"
└─ No → Continue

Is it about project-specific context (deadline, stakeholder, scope)?
├─ Yes → experience_type: "project"
└─ No → experience_type: "reference"
```

**Experience 4-type Storage Structure**:
```
memory/projects/{scope}/
├── user.experience.md        # User preferences/communication style
├── feedback.experience.md    # Corrections, confirmations, rejections
├── project.experience.md     # Project-specific context
└── reference.experience.md   # External references
```

**Priority**: When multiple types apply, use the first matching in order: user > feedback > project > reference

## Quality Standards

### For Skill Creation

**Good skill**:
- Has a clear name that describes what it does
- Explains WHEN to use this skill (trigger context)
- Provides specific steps or patterns
- Includes an example of when it worked

**Poor skill**:
- Just describes what happened (not a pattern)
- Too vague to act on
- Duplicates existing skills
- Includes things better learned through experience

### For Experience Recording

**Good experience**:
- Notes what happened and why it mattered
- Identifies the key insight or lesson
- Is honest about what went wrong
- Can be referenced when similar situations arise

**Poor experience**:
- Is just a log of actions
- Doesn't extract any insight
- Is so specific it's never applicable again

## LLM Direct Execution

**All file operations are executed directly by LLM; API layer performs no operations.**

### Creating a Skill

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
git add -A && git commit -m "Evolution: +skill {skill_name}"
```

### Creating an Experience

```python
# 1. Determine experience type using 4-type classification tree above
#    experience_type: "user" | "feedback" | "project" | "reference"

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
git add -A && git commit -m "Evolution: +experience {topic}"
```

### MEMORY.md Constraints (Phase 4)

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

## Output Format

```json
{
  "shouldRecord": true|false,
  "form": "skill|experience|none",
  "confidence": "high|medium|low",
  "skillName": "optional-kebab-case-name",
  "scope": "universal|project_specific",
  "experienceType": "user|feedback|project|reference",
  "projects": ["project_id"],
  "skipReason": "derivable-info|authoritative-source|ephemeral-info|fix-in-code|null",
  "content": "The content to record",
  "commitHash": "git commit hash after recording"
}
```

## Anti-Patterns

| Pattern | Problem | Solution |
|---------|---------|----------|
| Recording everything | Noise overwhelms signal | Only record clear patterns |
| Generic skill | Could apply to any task | Specific trigger + specific action |
| Detailed log | Not actionable | Extract the insight |
| Duplicate existing | Redundancy | Check before creating |
| Sensitive info | Security risk | Skip sensitive operations |

## Context Variables

The task provides:
- `archive_path`: Where to find the transcript
- `transcript_id`: Identifier for this transcript
- `project_id`: The project context (or "universal")
- `skills_dir`: Path to agent's skills directory (for glob scanning)
- `memory_dir`: Path to agent's memory directory (for glob scanning)

**API layer only passes directory paths; scanning is done autonomously by LLM via glob.**
