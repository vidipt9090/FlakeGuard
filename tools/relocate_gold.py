"""Recompute gold-set line numbers from a pinned checkout, by symbol name.

    python tools/relocate_gold.py docs/eval1/<gold>.json --repo ../<checkout>

A gold entry names a definition ("Serializer.dumps", "signer"). Which LINE
that sits on is not a judgment call, it is a lookup, and doing it by hand
against the wrong revision is how a gold set ends up measuring the revision
instead of the navigator. That is exactly what happened to the itsdangerous
set: its test-file lines were read before the repo was pinned to 2.2.0, so
every fixture was off by one and scored as a miss.

Rules, so this stays a correction and does not become a way to nudge results:

* only `start_line` is ever rewritten, never a name, never which entries exist
* a name matching several definitions is left alone and reported AMBIGUOUS,
  because picking one of them is a judgment the gold set already made
  (`cache_info` appears four times in cachetools/_cached.py, once per wrapper
  builder, and only one of them runs)
* fixtures resolve to the decorator line and everything else to the `def`
  line, because that is how the navigator builds each kind of chunk
* every change is printed, and --write is required to apply anything
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

# (def line, decorator-inclusive line, how many definitions share the name)
Entry = tuple[int, int, int]


def _is_stub(node: ast.AST) -> bool:
    """``def unsign(...) -> bytes: ...`` is an @overload signature.

    Three of these precede the real TimestampSigner.unsign, so a first-match
    lookup would point the gold set at a declaration with no body.
    """
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    body = [
        n
        for n in node.body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]
    if not body:
        return True
    return all(
        isinstance(n, ast.Pass)
        or (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and n.value.value is Ellipsis
        )
        for n in body
    )


def qualified_lines(path: Path) -> dict[str, Entry]:
    """Map "name" and "Owner.name" to where that definition starts."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return {}

    found: dict[str, Entry] = {}
    stubbed: dict[str, bool] = {}

    def put(key: str, def_line: int, deco_line: int, stub: bool) -> None:
        if key not in found:
            found[key] = (def_line, deco_line, 1)
            stubbed[key] = stub
            return
        d, k, count = found[key]
        # A real definition replaces a stub without counting as a clash:
        # @overload signatures are not a genuine ambiguity.
        if stubbed[key] and not stub:
            found[key] = (def_line, deco_line, count)
            stubbed[key] = False
        elif not stub:
            found[key] = (d, k, count + 1)

    def walk(node: ast.AST, prefix: str) -> None:
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                decorators = getattr(child, "decorator_list", [])
                deco_line = min([child.lineno] + [d.lineno for d in decorators])
                stub = _is_stub(child)
                put(child.name, child.lineno, deco_line, stub)
                if prefix:
                    put(f"{prefix}.{child.name}", child.lineno, deco_line, stub)
                # Descend into functions too: cache_info and cache_clear are
                # closures defined inside the wrapper builders.
                walk(child, child.name)
            else:
                targets: list[str] = []
                if isinstance(child, ast.Assign):
                    targets = [t.id for t in child.targets if isinstance(t, ast.Name)]
                elif isinstance(child, ast.AnnAssign) and isinstance(
                    child.target, ast.Name
                ):
                    targets = [child.target.id]
                for name in targets:
                    put(name, child.lineno, child.lineno, False)
                    if prefix:
                        put(f"{prefix}.{name}", child.lineno, child.lineno, False)

    walk(tree, "")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python tools/relocate_gold.py")
    parser.add_argument("gold")
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--write", action="store_true", help="apply; otherwise just report"
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    gold_path = Path(args.gold)
    spec = json.loads(gold_path.read_text(encoding="utf-8"))

    cache: dict[str, dict[str, Entry]] = {}
    changed = unchanged = ambiguous = unresolved = 0

    for case in spec["tests"]:
        for section in ("code_under_test", "fixtures", "shared_state"):
            for item in case.get(section, []):
                rel = item["path"]
                if rel not in cache:
                    cache[rel] = qualified_lines(repo / rel)
                name = item["name"]
                entry = cache[rel].get(name)
                if entry is None and "." in name:
                    entry = cache[rel].get(name.rsplit(".", 1)[1])
                if entry is None:
                    print(f"  UNRESOLVED {rel}:{name} (left at {item['start_line']})")
                    unresolved += 1
                    continue
                def_line, deco_line, count = entry
                if count > 1:
                    print(
                        f"  AMBIGUOUS  {rel}:{name} matches {count} definitions, "
                        f"left at {item['start_line']}"
                    )
                    ambiguous += 1
                    continue
                want = deco_line if section == "fixtures" else def_line
                if want != item["start_line"]:
                    print(f"  moved      {rel}:{name} {item['start_line']} -> {want}")
                    item["start_line"] = want
                    changed += 1
                else:
                    unchanged += 1

    print(
        f"\n{changed} moved, {unchanged} already correct, "
        f"{ambiguous} ambiguous (left alone), {unresolved} unresolved"
    )
    if args.write and changed:
        gold_path.write_text(
            json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {gold_path}")
    elif changed:
        print("(dry run; pass --write to apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
