# Sentriq docs — shared style guide (read before writing any doc)

Every component doc under `docs/` MUST follow this exact structure so the set
reads as one manual. Be ACCURATE to the real source — read the actual file(s)
you are assigned before writing, and quote real code, never invented code.

## Required structure
```
---
title: <Component Name>
source: <repo-relative path(s) of the file(s) this doc covers>
---

# <Component Name>

> One-sentence purpose.

## Role in the pipeline
Where this sits in the Sentriq flow and what depends on it (2–4 sentences).

## How it works
Prose walkthrough of the behaviour.

## Code walkthrough
Quote REAL snippets copied verbatim from the source file(s) in ```python (or
```jsx / ```yaml) fences, each followed by a short explanation. Cover the key
functions/classes. Do not paste the entire file — pick the meaningful parts.

## Diagram
One or more ```mermaid blocks illustrating this component (flowchart,
sequenceDiagram, classDiagram, or erDiagram as fits). Keep node labels short.

## Key decisions & gotchas
Bullet the non-obvious design choices and pitfalls.

## Related docs
Markdown links to the other docs/ files this connects to.
```

## Rules
- GitHub-flavoured markdown. Mermaid in ```mermaid fences.
- Read the source first; quotes must match the real code.
- Write ONLY your assigned `docs/<name>.md`. Do not edit any other file.
- Do NOT run git.
- The doc set (for cross-links):
  00-overview, 01-schema, 02-adapters, 03-executor, 04-aggregator,
  05-deepseek, 06-data-model, 07-orchestration, 08-api, 09-frontend,
  10-deployment.
