---
name: agenthub-orchestrator
description: Create and evolve AgentHub Goals through typed Progressive Harness proposals while leaving all authoritative state changes to Runtime.
version: 1.0.0
---

# AgentHub Orchestrator

Use this workflow for any Harness-mode request:

1. Clarify the objective, acceptance criteria, constraints, prohibited actions,
   required evidence, delivery mode, and independent Review requirement.
2. Call `agenthub_create_goal`. Do not weaken missing evidence into a prompt-only
   suggestion.
3. Generate `agenthub.io/harness/v1` IR with explicit finite bounds. Include a
   deterministic Runtime Gate, independent Review excluding the implementer,
   and exactly one finalize node.
4. Call `agenthub_submit_harness`. Fix validation errors as a new proposal; do
   not write state directly.
5. Use `agenthub_get_goal` for progress. Large outputs belong in Artifacts.
6. On semantic failure, submit a versioned Patch against the active version.
   Never turn test or Review failure into unbounded technical retry.
7. Ask for input or approval when Runtime reports waiting. Do not poll with
   model turns.

Workers receive local TaskEnvelope projections, never the complete Harness.
Worker-created internal subagents remain inside that Worker Run. A new top-level
Task requires a typed spawn proposal and Runtime approval.
