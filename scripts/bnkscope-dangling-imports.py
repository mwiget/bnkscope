#!/usr/bin/env python3
"""Find imports of backend modules that no longer exist.

`ruff F821` only sees module-level names; the pipeline deletion left plenty of
*function-local* `from services.foo import Bar` statements that fail at request
time. This walks every AST import node and checks the target still resolves.
"""
import ast
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
TOP = {"core", "models", "routes", "schemas", "services", "tasks", "utils", "modules",
       "database", "main", "celery_app", "startup_steps"}


def resolves(mod: str) -> bool:
    path = os.path.join(ROOT, *mod.split("."))
    return os.path.isfile(path + ".py") or os.path.isdir(path)


def main() -> int:
    bad = []
    for dp, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "alembic")]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            try:
                tree = ast.parse(open(p, errors="ignore").read())
            except SyntaxError as e:
                bad.append((p, e.lineno or 0, f"SYNTAX ERROR: {e.msg}"))
                continue
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                elif isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                for mod in mods:
                    if mod.split(".")[0] in TOP and not resolves(mod):
                        bad.append((os.path.relpath(p, ROOT), node.lineno, mod))

    for path, line, mod in sorted(bad):
        print(f"{path}:{line}: imports missing module `{mod}`")
    print(f"{len(bad)} dangling import(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
