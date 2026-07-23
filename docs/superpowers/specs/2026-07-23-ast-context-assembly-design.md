---
title: AST-aware context assembly for fix generation
source: brainstorming session, 2026-07-23
updated: 2026-07-23
---

# AST-aware context assembly for fix generation

Maps to the deferred PRD tasks B6/B7 ("Context Assembly — AST-aware RAG") in
`sentriq_md/Sentriq AI/Tasks ....md`. In that PRD's own diagram, "RAG" for the
fix-generation stage means the AST-aware retriever, not a vector store — so
this single change satisfies both terms as the user meant them.

## Problem

`ci-utils/sentriq/deepseek.py:_window()` slices ±60 raw lines around a
finding's line number when the file is too large to send whole. That can:
- cut a function definition in half
- omit the file's imports entirely
- include unrelated code from a neighboring function

The LLM then proposes `old_str`/`new_str` against a context that may not even
show the complete function it's editing.

## Scope (explicitly decided)

- **Python only**, using stdlib `ast` — zero new dependencies. Non-Python
  files keep today's `_window()` behavior unchanged; no regression there.
- **Single-file, structural context only** — the enclosing function/class
  plus the file's imports. No cross-file caller search, no test-file lookup
  (those stay deferred).
- A small **frontend badge** on the fix diff view showing which context
  strategy produced the fix (function scope / class scope / file window /
  none), so the distinction is visible without a new screen.

## Design

### Backend: `ci-utils/sentriq/context.py` (new module)

```python
def assemble_context(file_text: str, line: Optional[int]) -> Optional[ContextResult]
```

- Parses `file_text` with `ast.parse`. Returns `None` on `SyntaxError`.
- Returns `None` if `line` is falsy (nothing to anchor scope-finding on).
- Walks the module body to find the smallest enclosing
  `FunctionDef`/`AsyncFunctionDef` node whose `lineno..end_lineno` range
  contains `line`. If none contains it but a `ClassDef` does (line is in
  class body but not inside any method), use the class node instead.
- If no enclosing def/class contains the line at all (pure module-level
  code), returns `None` — caller falls back to `_window()`.
- Collects all module-level `Import`/`ImportFrom` nodes (source text of each,
  in file order) regardless of where the enclosing node is.
- Slices the enclosing node's source text directly from `file_text` via
  `lineno`/`end_lineno` (1-based, `end_lineno` inclusive).
- If the enclosing node's own text exceeds `_MAX_FILE_CHARS`, falls back to
  `_window()` scoped to that node's own line range (so an oversized function
  still gets *some* context) rather than failing.
- Returns a small dataclass:
  ```python
  @dataclass
  class ContextResult:
      text: str              # formatted block for the prompt
      strategy: str           # "function_scope" | "class_scope"
  ```

### Backend wiring: `deepseek.py`

- `_fix_prompt` tries `context.assemble_context(file_text, line)` first (only
  when `path.endswith(".py")`). On `None`, falls back to the existing
  `_window()` path exactly as today, with `strategy="file_window"` (or
  `"none"` when the file fit whole and no windowing/context happened at all).
- `FixResult` gains a `context_strategy: str` field so the strategy travels
  back to the caller.
- The anchor-uniqueness check (`old_str` must appear exactly once) keeps
  running against the **full** `file_text`, never the assembled context —
  that safety property is unrelated to what the LLM was shown and does not
  change.

### Backend: model + API

- `FixSuggestion` gains `context_strategy = models.CharField(max_length=20,
  blank=True, default="")` (new migration).
- `tasks.py`'s fix-generation paths (`_triage_and_fix`,
  `generate_fix_for_finding`) store `fx.context_strategy` on the created
  `FixSuggestion` row.
- `FixSuggestionSerializer` adds `"context_strategy"` to `fields`.

### Frontend: small badge

- `FindingDetail.jsx`, next to the "Suggested Fix" heading (around line 167):
  a small uppercase tag reading the strategy, e.g. `FUNCTION SCOPE` /
  `CLASS SCOPE` / `FILE WINDOW`, styled consistently with the existing
  status/severity tags already in this file. Hidden when `context_strategy`
  is empty (secret-remediation fixes, or fixes generated before this field
  existed).

## Testing

- `ci-utils/tests/test_context.py` — plain assert-based tests (no Django
  TestCase, this module has no ORM/DB dependency):
  - line inside a top-level function → `function_scope`, function text
    present, imports present
  - line inside a method → `function_scope`, enclosing method only (not the
    whole class)
  - line in class body outside any method → `class_scope`
  - line at module level (no enclosing def) → `None` (fallback signal)
  - invalid Python source → `None`
  - oversized enclosing function → falls back to windowed text within that
    function's range, not a crash
- `sentriq-frontend/src/components/FindingDetail.test.jsx` (or extend
  existing test file if one covers this component) — badge renders for each
  strategy value and is absent when empty.

## Out of scope (explicitly deferred, unchanged from PRD)

Cross-file caller search, existing-test lookup, non-Python languages, the
triage-stage vector corpus (A7/B4), IAST, fuzzing, GitLab MR automation, and
the SaaS layer. These remain tracked in `docs/concerns.md` /
`sentriq_md/Sentriq AI/Tasks ....md`.
