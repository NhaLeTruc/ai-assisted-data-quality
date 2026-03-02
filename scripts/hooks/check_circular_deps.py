#!/usr/bin/env python3
"""Pre-commit hook: detect circular imports among Python modules in src/.

Algorithm:
  1. Collect every .py file under src/ and map it to a dotted module name.
  2. Parse each file's AST to extract internal imports (absolute and relative).
  3. Build a directed dependency graph (module → set of modules it imports).
  4. DFS with three-colour marking to find back edges (= cycles).
  5. Report each unique cycle and exit non-zero if any are found.

Usage (called automatically by pre-commit — no file args needed):
    python check_circular_deps.py
"""

import ast
import sys
from collections import defaultdict
from pathlib import Path

# Root directory that contains the application source packages.
SRC_ROOT = Path("src")


# ---------------------------------------------------------------------------
# Module discovery
# ---------------------------------------------------------------------------


def collect_modules(src_root: Path) -> dict[Path, str]:
    """Return {file_path: dotted.module.name} for every .py file under src_root."""
    mapping: dict[Path, str] = {}
    for py_file in sorted(src_root.rglob("*.py")):
        rel = py_file.relative_to(src_root.parent)  # e.g. src/agents/workflow.py
        parts = list(rel.with_suffix("").parts)  # ['src', 'agents', 'workflow']
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mapping[py_file] = ".".join(parts)
    return mapping


# ---------------------------------------------------------------------------
# Import parsing
# ---------------------------------------------------------------------------


def _resolve_relative(level: int, module: str | None, current_pkg: str) -> str | None:
    """Resolve a relative import to an absolute dotted module name."""
    pkg_parts = current_pkg.split(".")
    # 'level' dots mean go up that many levels from the current package.
    if level > len(pkg_parts):
        return None
    base_parts = pkg_parts[: len(pkg_parts) - level + 1]
    if module:
        return ".".join(base_parts + module.split("."))
    return ".".join(base_parts)


def parse_imports(
    py_file: Path,
    current_module: str,
    known_modules: set[str],
    internal_prefixes: tuple[str, ...],
) -> set[str]:
    """Return internal module names imported by py_file."""
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, OSError):
        return set()

    # Current package = everything before the last dot-segment.
    current_pkg = (
        ".".join(current_module.split(".")[:-1]) if "." in current_module else current_module
    )

    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name in known_modules or name.startswith(internal_prefixes):
                    imports.add(name)

        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import
                resolved = _resolve_relative(node.level, node.module, current_pkg)
                if resolved and (
                    resolved in known_modules or resolved.startswith(internal_prefixes)
                ):
                    imports.add(resolved)
            elif node.module:
                # Absolute import
                name = node.module
                if name in known_modules or name.startswith(internal_prefixes):
                    imports.add(name)

    # Remove self-imports
    imports.discard(current_module)
    return imports


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

WHITE, GRAY, BLACK = 0, 1, 2


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """DFS three-colour cycle detection. Returns a deduplicated list of cycles."""
    color: dict[str, int] = {n: WHITE for n in graph}
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbour in sorted(graph.get(node, set())):
            if neighbour not in color:
                continue  # external module — skip
            if color[neighbour] == GRAY:
                # Back edge: neighbour is already on the current DFS path.
                idx = path.index(neighbour)
                cycles.append(path[idx:] + [neighbour])
            elif color[neighbour] == WHITE:
                dfs(neighbour, path)
        path.pop()
        color[node] = BLACK

    for node in sorted(graph):
        if color[node] == WHITE:
            dfs(node, [])

    # Deduplicate: two cycle reports that cover the same set of nodes are the same cycle.
    seen: set[frozenset[str]] = set()
    unique: list[list[str]] = []
    for cycle in cycles:
        key = frozenset(cycle)
        if key not in seen:
            seen.add(key)
            unique.append(cycle)
    return unique


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if not SRC_ROOT.exists():
        # src/ not yet created — nothing to check.
        return 0

    file_to_module = collect_modules(SRC_ROOT)
    if not file_to_module:
        return 0

    known_modules: set[str] = set(file_to_module.values())

    # Top-level package names for prefix matching (e.g. "src", "agents").
    top_level = {m.split(".")[0] for m in known_modules}
    internal_prefixes = tuple(sorted(top_level))

    # Build dependency graph.
    graph: dict[str, set[str]] = defaultdict(set)
    for py_file, module_name in file_to_module.items():
        graph[module_name]  # ensure node exists even with no imports
        deps = parse_imports(py_file, module_name, known_modules, internal_prefixes)
        for dep in deps:
            # Normalise: if dep is a sub-module, map to its closest known ancestor.
            resolved = dep
            if dep not in known_modules:
                # Try progressively shorter prefixes.
                parts = dep.split(".")
                for length in range(len(parts), 0, -1):
                    candidate = ".".join(parts[:length])
                    if candidate in known_modules:
                        resolved = candidate
                        break
                else:
                    continue  # Not an internal module at all.
            if resolved != module_name:
                graph[module_name].add(resolved)

    cycles = find_cycles(dict(graph))

    if not cycles:
        return 0

    print(f"\n[circular-deps] ERROR — {len(cycles)} circular import(s) detected:", file=sys.stderr)
    for i, cycle in enumerate(cycles, 1):
        print(f"  Cycle {i}: {' → '.join(cycle)}", file=sys.stderr)
    print(
        "\nRefactor to break the cycle (extract shared code to a new module, "
        "use dependency injection, or defer the import).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
