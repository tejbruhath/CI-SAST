"""
AST-aware context assembly for fix generation (PRD tasks B6/B7).

Replaces the raw ±N-line window with the actual enclosing function/class
plus the file's imports, so the LLM sees a syntactically complete unit
instead of an arbitrary slice. Python only (stdlib `ast`); every other
language, and every failure mode here, returns None so the caller falls back
to the existing line-window behavior — no regression for non-Python files.
"""
from __future__ import annotations

import ast  # stdlib Python parser — no new dependency
from dataclasses import dataclass
from typing import Optional

FUNCTION_SCOPE = "function_scope"
CLASS_SCOPE = "class_scope"

_MAX_NODE_CHARS = 12000  # keep in sync with deepseek._MAX_FILE_CHARS


@dataclass
class ContextResult:
    text: str       # formatted block for the fix prompt
    strategy: str   # FUNCTION_SCOPE | CLASS_SCOPE


def _node_source(lines: list[str], node: ast.AST) -> str:
    """1-based, end_lineno-inclusive slice of the original text for `node`."""
    return "".join(lines[node.lineno - 1:node.end_lineno])


def _imports_source(lines: list[str], tree: ast.Module) -> str:
    chunks = []
    for node in tree.body:  # module-level only, in file order
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            chunks.append(_node_source(lines, node))
    return "".join(chunks)


def _enclosing_scope(tree: ast.Module, line: int):
    """Smallest FunctionDef/AsyncFunctionDef containing `line`, else the
    smallest ClassDef containing it (line in class body, outside any method),
    else None."""
    best_func, best_class = None, None
    for node in ast.walk(tree):
        if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
            continue
        if not (node.lineno <= line <= node.end_lineno):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if best_func is None or (node.end_lineno - node.lineno) < (
                best_func.end_lineno - best_func.lineno
            ):
                best_func = node
        elif isinstance(node, ast.ClassDef):
            if best_class is None or (node.end_lineno - node.lineno) < (
                best_class.end_lineno - best_class.lineno
            ):
                best_class = node
    return best_func, best_class


def assemble_context(file_text: str, line: Optional[int]) -> Optional[ContextResult]:
    """Enclosing function/class + module imports for a Python file, or None
    to signal the caller should fall back to the raw line-window."""
    if not line:
        return None
    try:
        tree = ast.parse(file_text)
    except SyntaxError:
        return None

    func, cls = _enclosing_scope(tree, line)
    node, strategy = (func, FUNCTION_SCOPE) if func is not None else (cls, CLASS_SCOPE)
    if node is None:
        return None  # module-level code, no enclosing def/class

    lines = file_text.splitlines(keepends=True)
    imports = _imports_source(lines, tree)
    body = _node_source(lines, node)

    if len(imports) + len(body) > _MAX_NODE_CHARS:
        # Oversized enclosing scope: window within its own range rather than
        # failing outright — still bounded, still on-topic.
        from .deepseek import _window  # local import: avoid a circular import at module load

        body = _window(file_text, line, radius=60)
        lo, hi = max(1, line - 60), line + 60
        header = f"Excerpt of the enclosing {strategy.split('_')[0]} (lines {lo}-{hi}, truncated):"
    else:
        label = "function" if strategy == FUNCTION_SCOPE else "class"
        header = f"Enclosing {label} (lines {node.lineno}-{node.end_lineno}):"

    text = f"Imports:\n{imports}\n{header}\n{body}" if imports else f"{header}\n{body}"
    return ContextResult(text=text, strategy=strategy)


if __name__ == "__main__":  # offline self-check
    src = (
        "import os\n"
        "from typing import Any\n"
        "\n"
        "class Foo:\n"
        "    attr = 1\n"
        "\n"
        "    def bar(self):\n"
        "        x = 1\n"
        "        return x\n"
        "\n"
        "def baz():\n"
        "    y = 2\n"
        "    return y\n"
    )
    r = assemble_context(src, 8)  # inside Foo.bar
    assert r.strategy == FUNCTION_SCOPE, r
    assert "def bar" in r.text and "import os" in r.text and "def baz" not in r.text, r.text

    r = assemble_context(src, 12)  # inside baz
    assert r.strategy == FUNCTION_SCOPE and "def baz" in r.text and "def bar" not in r.text, r.text

    r = assemble_context(src, 5)  # class body, outside any method
    assert r.strategy == CLASS_SCOPE and "class Foo" in r.text, r.text

    assert assemble_context(src, 2) is None  # module-level import line
    assert assemble_context("def(:", 1) is None  # syntax error
    assert assemble_context(src, None) is None  # no line given
    print("context self-check passed")
