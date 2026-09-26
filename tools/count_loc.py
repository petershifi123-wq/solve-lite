#!/usr/bin/env python3
"""Reproducible Python LOC and control-flow inventory."""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "solve-lite"


def logical_lines(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    doc = set()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if body and isinstance(body, list) and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                doc.update(range(body[0].lineno, getattr(body[0], "end_lineno", body[0].lineno) + 1))
    lines = set()
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in {tokenize.ENDMARKER, tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.NL, tokenize.COMMENT}:
            continue
        if token.start[0] not in doc and token.string.strip():
            lines.add(token.start[0])
    return len(lines)


def inventory(paths: list[Path]) -> dict[str, int]:
    result = {"files": 0, "logical_loc": 0, "functions": 0, "if_nodes": 0, "elif_lines": 0}
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
        result["files"] += 1
        result["logical_loc"] += logical_lines(path)
        result["functions"] += sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))
        result["if_nodes"] += sum(isinstance(node, ast.If) for node in ast.walk(tree))
        result["elif_lines"] += sum(bool(re.match(r"^\s*elif\b", line)) for line in text.splitlines())
    return result


def main() -> int:
    all_python = sorted(PLUGIN.rglob("*.py"))
    tests = [path for path in all_python if path.name.startswith("test_")]
    runtime = [path for path in all_python if path not in tests]
    hooks = [path for path in runtime if "hooks" in path.parts]
    adapter = [path for path in runtime if path.name == "codex_desktop_adapter.py"]
    public_loader = [path for path in runtime if path.name == "solve_lite_abi.py"]
    agent_adapter = [path for path in runtime if path.name == "agent_auto.py"]
    output = {
        "schema_version": "solve-lite.loc-report.v1",
        "method": "distinct token-bearing Python lines excluding blanks, comments and AST docstrings",
        "runtime": inventory(runtime),
        "tests": inventory(tests),
        "hooks": inventory(hooks),
        "adapter": inventory(adapter),
        "public_loader": inventory(public_loader),
        "agent_adapter": inventory(agent_adapter),
        "private_runtime_package_present": int(
            (PLUGIN / "skills" / "solve-lite" / "scripts" / "solve_lite").exists()
        ),
        "closed_core_artifacts_in_public_tree": len(list(ROOT.rglob("*.so"))),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
