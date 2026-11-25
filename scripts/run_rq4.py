"""RQ4: does more code context help a small model name the cause of a flaky test?

    python scripts/run_rq4.py planted  --prompt v1      # tuning set: writes results/planted/rq4_tuning_v1.json
    python scripts/run_rq4.py injected                  # the result: writes results/injected/rq4.json

Definitions (what "matches", the four settings, the fix metric) are in docs/EVAL.md, section RQ4, written before this was run.
Model: llama3.2:3b through a local Ollama. Temperature 0, seed 42. A reply that cannot be read is a failure, never a skip.
Replies are cached under .eval_cache/rq4_calls (keyed by the full request), so an interrupted run resumes and a repeat run
gives the same file; --no-cache asks the model again.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
_spec = importlib.util.spec_from_file_location("run_eval", REPO / "scripts" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)

from flakeguard.console.analysis import analyse_repo, shared_links  # noqa: E402
from flakeguard.console.fixer import plan_fix  # noqa: E402
from flakeguard.injector.dataset import OPERATORS  # noqa: E402
from flakeguard.injector.operators import find_function  # noqa: E402
from flakeguard.navigator.ast_nav import AstNavigator  # noqa: E402

MODEL = "llama3.2:3b"
HOST = "http://localhost:11434"
SEED = 42
NUM_CTX = 16384
SETTINGS = ("none", "file", "ast", "ast_jedi")

# --mask (the rq4_masked run): the seven identifiers only the injection operators write (flakeguard/injector/operators.py) are
# replaced in the code part of the prompt, one neutral name each. Natural cues (sleep, random, datetime, now, Thread, global ...) stay.
MASK_MAP = {"_FLAKEGUARD_ORDER_READY": "_x1", "_FLAKEGUARD_SHARED_CACHE": "_x2", "_bg_job": "_x3", "_fg_random": "_x4",
            "_hour": "_x5", "_race_flag": "_x6", "_th": "_x7"}
_MASK_RE = re.compile(r"\b(" + "|".join(map(re.escape, MASK_MAP)) + r")\b")


def mask_code(text: str) -> str:
    out = _MASK_RE.sub(lambda m: MASK_MAP[m.group(1)], text)
    left = _MASK_RE.findall(out)
    if left:  # never send a prompt that still holds a name that was meant to be masked
        raise RuntimeError(f"masking left {sorted(set(left))} in the text")
    return out


CAUSE_WORD = {"order_dep": "order_dependence", "shared_state": "shared_state", "timing": "timing",
              "randomness": "randomness", "time_tz": "time_or_timezone"}
VOCAB = [*CAUSE_WORD.values(), "other"]
FIX_SEEDS = list(range(1, 11))
CALLS = REPO / ".eval_cache" / "rq4_calls"
INJECTED = REPO / ".eval_cache" / "injected"
VIEW = REPO / ".eval_cache" / "injected_view"
PRISTINE = REPO / ".eval_cache" / "dl" / "cachetools-8.0.2"

CAUSES_TEXT = """\
- order_dependence: the test only passes when some other test ran before it, or it fails because of what an earlier test left behind, so its result depends on the order the tests run in
- shared_state: several tests read and change the same module-level or global state and nothing resets it between them
- timing: a thread, a sleep or a fixed wait: the result depends on how quickly something else finishes
- randomness: the test uses a random value that is not seeded
- time_or_timezone: the result depends on the current time, date or timezone
- other: none of the above"""

PROMPTS = {
    "v1": """\
You are diagnosing a flaky test. A flaky test sometimes passes and sometimes fails although nobody changed the code.

Test: {test_id}
This test was flagged flaky.
{summary}

{code}

Choose the single most likely cause from this list:
{causes}

Reply with JSON only, in this form: {{"cause": "<one word from the list>", "reason": "<one sentence>"}}
""",
}
PROMPTS["v2"] = """\
You are diagnosing a flaky test. A flaky test sometimes passes and sometimes fails although nobody changed the code.

Test: {test_id}
This test was flagged flaky.
{summary}

{code}

Choose the single most likely cause from this list, using the clues given for each:
- order_dependence: the test only passes if some other test ran before it and left something set up (a flag, a value, a file), so it fails when it runs first or alone. Clue: it asserts on something that this test never creates itself.
- shared_state: this test changes a module-level or global variable, cache, counter or class attribute and nothing puts it back, so later tests or later runs see the changed value. Clue: the test itself assigns to a global or class attribute, or increments a global counter.
- timing: a thread, sleep, wait or timeout: the result depends on how fast something finishes. Clue: sleep, Thread, join, wait, timeout.
- randomness: a random value that is not seeded decides the result. Clue: random, uuid, secrets, a value drawn from a range or compared with a threshold.
- time_or_timezone: the result depends on the current clock, date, hour, weekday or timezone. Clue: datetime.now, time.time, utcnow, freeze_time, hour, timezone.
- other: none of the above.
Do not choose shared_state only because the code uses a global name. Pick the clue that matches what the test does.

Reply with JSON only, in this form: {{"cause": "<one word from the list>", "reason": "<one sentence>"}}
"""
FIX_PROMPT = """\
You are fixing a flaky test.

Test: {test_id}
This test was flagged flaky and the cause is order dependence: it only passes when another test ran before it.
{summary}

{code}

Rewrite the test function so that it no longer depends on another test having run first. Keep every other line of the test as it is.

Reply with JSON only, in this form: {{"fixed_test": "<the complete source of the test function, def line included>"}}
"""
DEFAULT_PROMPT = "v2"


# ------------------------------------------------------------------------------------- what the model is shown


def _assert_messages() -> dict[str, str]:
    """The injected assert lines, and the same lines without their message (the message names the cause)."""
    out = {}
    for op in OPERATORS.values():
        lines = op.block() + (op.setup_block() if hasattr(op, "setup_block") else [])
        for line in lines:
            m = re.match(r"^(assert .*?),\s*f?'[^']*'$", line.strip())
            if m:
                out[line.strip()] = m.group(1)
    return out


def scrub(text: str, messages: dict[str, str]) -> str:
    """Drop the comment lines the operators insert and the messages of their asserts. Nothing else changes."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# Injected ") and "by FlakeGuard" in stripped:
            continue
        if stripped in messages:
            line = line[: len(line) - len(line.lstrip())] + messages[stripped]
        out.append(line)
    return "\n".join(out) + "\n"


def make_view() -> Path:
    """A copy of the injected suite as the model sees it. The suite that was run is left alone."""
    if VIEW.exists():
        shutil.rmtree(VIEW)
    shutil.copytree(INJECTED, VIEW, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    messages = _assert_messages()
    for path in (VIEW / "tests").glob("*.py"):
        path.write_text(scrub(path.read_text(encoding="utf-8"), messages), encoding="utf-8")
    return VIEW


def run_summary(label: str, test_id: str) -> str:
    out = Path(REPO / "results" / label)
    shuffled = json.loads((out / "perturbation.json").read_text(encoding="utf-8"))["runs"]
    fixed = json.loads((out / "b1_fixed_order.json").read_text(encoding="utf-8"))["runs"]
    a = sum(r["outcomes"].get(test_id) == "FAIL" for r in shuffled)
    b = sum(r["outcomes"].get(test_id) == "FAIL" for r in fixed)
    return f"In {len(shuffled)} shuffled-order runs it failed {a} times; in {len(fixed)} fixed-order runs it failed {b} times."


def _fence(text: str) -> str:
    return "```python\n" + text.rstrip("\n") + "\n```"


def context(setting: str, label: str, test_id: str, nav: AstNavigator, root: Path) -> str:
    """The code part of the prompt for one setting (empty message for ``none``)."""
    if setting == "none":
        return "No code is available for this test."
    rel = test_id.split("::")[0]
    if setting == "file":
        return f"The file that holds the test, {rel}:\n" + _fence((root / rel).read_text(encoding="utf-8"))
    explained = nav.explain(test_id)
    parts = ["The test:\n" + _fence(explained.test_source.text if explained.test_source else "(source not found)")]
    seen = {explained.tree.root.node_id}
    for node in explained.tree.root.walk():
        if node.node_id in seen or node.depth == 0:
            continue
        seen.add(node.node_id)
        if setting == "ast" and node.via != "ast":
            continue
        where = f"{node.path}:{node.start_line}" if node.path else ""
        head = f"Related code ({node.kind}, reached by '{node.edge}'): {node.label} {where}".rstrip()
        parts.append(head + ("\n" + _fence(node.text) if node.text.strip() else ""))
    return "\n\n".join(parts)


# ------------------------------------------------------------------------------------- the model


def ollama(path: str, body: dict | None = None, timeout: float = 3600) -> dict:
    req = urllib.request.Request(HOST + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def ask(prompt: str, num_predict: int, use_cache: bool) -> dict:
    body = {"model": MODEL, "prompt": prompt, "stream": False, "format": "json",
            "options": {"temperature": 0, "seed": SEED, "num_ctx": NUM_CTX, "num_predict": num_predict}}
    key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    cached = CALLS / f"{key}.json"
    if use_cache and cached.is_file():
        return json.loads(cached.read_text(encoding="utf-8"))
    start = time.perf_counter()
    try:
        r = ollama("/api/generate", body)
        rec = {"response": r.get("response", ""), "prompt_tokens": r.get("prompt_eval_count"), "generated_tokens": r.get("eval_count"),
               "seconds": round(time.perf_counter() - start, 1), "error": None}
    except Exception as exc:  # a timeout or a refused connection is a failed call, recorded as one
        rec = {"response": "", "prompt_tokens": None, "generated_tokens": None,
               "seconds": round(time.perf_counter() - start, 1), "error": f"{type(exc).__name__}: {exc}"}
    rec["truncated"] = bool(rec["prompt_tokens"] and rec["prompt_tokens"] >= NUM_CTX)
    if rec["error"] is None:
        CALLS.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(rec), encoding="utf-8")
    return rec


def read_cause(response: str) -> tuple[str | None, bool]:
    """(cause, readable). Readable means valid JSON with a ``cause`` that is one of the six words."""
    try:
        obj = json.loads(response)
        cause = str(obj.get("cause", "")).strip().lower() if isinstance(obj, dict) else ""
    except (ValueError, AttributeError):
        return None, False
    return (cause, True) if cause in VOCAB else (cause or None, False)


# ------------------------------------------------------------------------------------- the fix


def _victim_parts(test_id: str) -> tuple[str, str | None, str]:
    p = test_id.split("::")
    return p[0], (p[1] if len(p) == 3 else None), p[-1]


def _pytest(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(root),
                           "-c", str(root / "pyproject.toml"), *args], cwd=root, env=env, capture_output=True, text=True)


def _victim_failed(xml: Path, cls: str | None, name: str) -> bool | None:
    import xml.etree.ElementTree as ET

    hit = None
    for case in ET.parse(xml).getroot().iter("testcase"):
        if case.get("name") == name and (cls is None or case.get("classname", "").endswith("." + cls)):
            failed = case.find("failure") is not None or case.find("error") is not None
            hit = failed or bool(hit)
    return hit


def validate_fix(victim_id: str, fixed_text: str, labels: list[dict], perturbation: list[dict]) -> dict:
    """The five checks of docs/EVAL.md on a copy of the injected suite. Returns which held, and why not."""
    file, cls, name = _victim_parts(victim_id)
    rec = {"checks": {}, "validated": False, "reason": ""}

    def fail(why: str) -> dict:
        rec["reason"] = why
        return rec

    text = textwrap.dedent(fixed_text or "").strip("\n")
    try:
        new_tree = ast.parse(text)
    except SyntaxError as exc:
        return fail(f"the fix is not valid python: {exc.msg}")
    funcs = [n for n in new_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(new_tree.body) != 1 or not funcs or funcs[0].name != name:
        return fail("the reply is not one function with the same name")
    original = (INJECTED / file).read_text(encoding="utf-8")
    func = find_function(ast.parse(original), name, cls)
    pristine_func = find_function(ast.parse((PRISTINE / file).read_text(encoding="utf-8")), name, cls)
    body_lines = [ln.strip() for ln in "\n".join((PRISTINE / file).read_text(encoding="utf-8").splitlines()[pristine_func.body[0].lineno - 1: pristine_func.end_lineno]).splitlines() if ln.strip()]
    new_lines = {ln.strip() for ln in text.splitlines()}
    missing = [ln for ln in body_lines if ln not in new_lines]
    rec["checks"]["parses_and_same_function"] = True
    rec["checks"]["keeps_original_body"] = not missing
    if missing:
        return fail(f"{len(missing)} line(s) of the original test body are gone, e.g. {missing[0]!r}")
    first = min([func.lineno, *(d.lineno for d in func.decorator_list)])
    lines = original.splitlines()
    indent = " " * func.col_offset
    replacement = [indent + ln if ln.strip() else ln for ln in text.splitlines()]
    new_src = "\n".join(lines[: first - 1] + replacement + lines[func.end_lineno:]) + "\n"
    with tempfile.TemporaryDirectory(prefix="flakeguard-rq4-") as tmp:
        work = Path(tmp) / "suite"
        shutil.copytree(INJECTED, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        before = _pytest(work, "-p", "no:randomly", victim_id)
        rec["alone_without_fix_exit"] = before.returncode
        (work / file).write_text(new_src, encoding="utf-8")
        try:
            ast.parse(new_src)
        except SyntaxError as exc:
            return fail(f"the file no longer parses: {exc.msg}")
        collected = _pytest(work, "--collect-only", "-p", "no:randomly", "tests")
        ids = [ln.strip() for ln in collected.stdout.splitlines() if "::" in ln and ln.startswith("tests/")]
        rec["checks"]["collects_same_tests"] = ids == [x["id"] for x in labels]
        if not rec["checks"]["collects_same_tests"]:
            return fail("the suite no longer collects the same tests")
        alone = _pytest(work, "-p", "no:randomly", victim_id)
        rec["checks"]["passes_alone"] = alone.returncode == 0
        if alone.returncode != 0:
            return fail("the test still fails when run alone")
        failed_seeds = []
        for seed in FIX_SEEDS:
            xml = Path(tmp) / f"s{seed}.xml"
            _pytest(work, "-p", "randomly", f"--randomly-seed={seed}", "-o", "junit_family=xunit1", f"--junitxml={xml}", "tests")
            if _victim_failed(xml, cls, name):
                failed_seeds.append(seed)
        rec["checks"]["passes_in_10_shuffled_runs"] = not failed_seeds
        rec["victim_failed_seeds_with_fix"] = failed_seeds
    rec["victim_failed_seeds_without_fix"] = [i + 1 for i, r in enumerate(perturbation[: len(FIX_SEEDS)]) if r["outcomes"].get(victim_id) == "FAIL"]
    if failed_seeds:
        return fail(f"the test still failed in shuffled runs with seeds {failed_seeds}")
    rec["validated"] = True
    return rec


def proposer_applies(victim_id: str) -> bool:
    """Would the existing fix proposer (fixtures for module-level dict, list, set state) offer a fix for this test?"""
    analysis = analyse_repo(INJECTED)
    for link in shared_links(analysis):
        if victim_id in {*link.writers, *link.readers} and plan_fix(INJECTED, link.state) is not None:
            return True
    return False


# ------------------------------------------------------------------------------------- running


def _stats(values: list[float]) -> dict:
    values = [v for v in values if v is not None]
    return {"n": len(values), "mean": round(statistics.mean(values), 1), "median": statistics.median(values), "max": max(values),
            "total": sum(values)} if values else {"n": 0, "mean": None, "median": None, "max": None, "total": None}


def run(label: str, prompt_version: str, settings: tuple[str, ...], use_cache: bool, limit: int | None, fix: bool, mask: bool = False) -> dict:
    labels = run_eval.prepare(label)
    flaky = [x for x in labels if x["label"] == "flaky"][:limit]
    template = PROMPTS[prompt_version]
    root = make_view() if label == "injected" else REPO
    nav = AstNavigator(root)
    perturbation = json.loads((REPO / "results" / label / "perturbation.json").read_text(encoding="utf-8"))["runs"]
    per_test: list[dict] = []
    print(f"{label}: {len(flaky)} flaky tests x {len(settings)} settings, prompt {prompt_version}", flush=True)
    for setting in settings:
        for x in flaky:
            tid = x["id"]
            code = context(setting, label, tid, nav, root)
            if mask:
                code = mask_code(code)
            prompt = template.format(test_id=tid, summary=run_summary(label, tid), code=code, causes=CAUSES_TEXT)
            rec = ask(prompt, 200, use_cache)
            cause, readable = read_cause(rec["response"])
            expected = CAUSE_WORD[x["root_cause"]]
            row = {"id": tid, "setting": setting, "known_cause": expected, "model_cause": cause, "readable": readable,
                   "match": bool(readable and cause == expected), "code_chars": 0 if setting == "none" else len(code),
                   "prompt_tokens": rec["prompt_tokens"], "generated_tokens": rec["generated_tokens"], "seconds": rec["seconds"],
                   "truncated": rec["truncated"], "error": rec["error"], "reply": rec["response"]}
            if fix and label == "injected" and x["root_cause"] == "order_dep":
                frec = ask(FIX_PROMPT.format(test_id=tid, summary=run_summary(label, tid), code=code), 800, use_cache)
                try:
                    fixed = json.loads(frec["response"]).get("fixed_test", "")
                    fixed = fixed if isinstance(fixed, str) else ""
                except (ValueError, AttributeError):
                    fixed = ""
                verdict = validate_fix(tid, fixed, labels, perturbation) if fixed else {"validated": False, "reason": "no usable fix in the reply", "checks": {}}
                row["fix"] = {**verdict, "prompt_tokens": frec["prompt_tokens"], "generated_tokens": frec["generated_tokens"],
                              "seconds": frec["seconds"], "error": frec["error"], "reply": frec["response"],
                              "fix_proposer_applies": proposer_applies(tid)}
            per_test.append(row)
            print(f"  {setting:9} {tid.split('/')[-1][:60]:60} -> {cause} ({'match' if row['match'] else 'no'}) {rec['seconds']}s", flush=True)
    results = {}
    for setting in settings:
        rows = [r for r in per_test if r["setting"] == setting]
        k = sum(r["match"] for r in rows)
        fixes = [r["fix"] for r in rows if "fix" in r]
        results[setting] = {
            "diagnosis_matches": run_eval.rate(k, len(rows)),
            "unreadable_replies_counted_as_failures": sum(not r["readable"] for r in rows),
            "sensitivity_if_random_were_accepted_as_randomness": {
                "note": "NOT the result. The model sometimes wrote 'random' instead of the listed word 'randomness'. The registered rule counts that as a failure and the figure above does. This is what the count would be if it were accepted.",
                "replies_saying_random": sum(r["model_cause"] == "random" for r in rows),
                **run_eval.rate(k + sum(r["model_cause"] == "random" and r["known_cause"] == "randomness" for r in rows), len(rows))},
            "answers": {w: sum(r["model_cause"] == w for r in rows) for w in VOCAB},
            "by_known_cause": {c: {"k": sum(r["match"] for r in rows if r["known_cause"] == c), "n": sum(r["known_cause"] == c for r in rows)}
                               for c in CAUSE_WORD.values()},
            "code_chars_sent": _stats([r["code_chars"] for r in rows]),
            "prompt_tokens": _stats([r["prompt_tokens"] for r in rows]),
            "generated_tokens": _stats([r["generated_tokens"] for r in rows]),
            "seconds": _stats([r["seconds"] for r in rows]),
            "prompts_that_filled_the_context": sum(r["truncated"] for r in rows),
            **({"fix": {"n": len(fixes), "validated": sum(f["validated"] for f in fixes),
                        "fix_proposer_applies": sum(f["fix_proposer_applies"] for f in fixes),
                        "note": "N=5 order-dependent tests; counts, not rates"}} if fixes else {}),
        }
    return {"results": results, "per_test": per_test}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("label", choices=["planted", "injected"])
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, choices=sorted(PROMPTS))
    ap.add_argument("--settings", default=",".join(SETTINGS))
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-fix", action="store_true")
    ap.add_argument("--mask", action="store_true", help="the rq4_masked run: mask the seven injector-only identifiers (docs/EVAL.md)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    settings = tuple(args.settings.split(","))
    labels = run_eval.prepare(args.label)
    command = "python " + " ".join(["scripts/run_rq4.py", *(argv if argv is not None else sys.argv[1:])])
    prov = run_eval.provenance(args.label, labels, command)
    tags = ollama("/api/tags")
    digest = next((m["digest"] for m in tags["models"] if m["name"] == MODEL), None)
    body = run(args.label, args.prompt, settings, not args.no_cache, args.limit, not args.no_fix, args.mask)
    prov.update({
        "model": {"name": MODEL, "digest": digest, "ollama_version": ollama("/api/version").get("version"), "host": "local, CPU"},
        "decoding": {"temperature": 0, "seed": SEED, "num_ctx": NUM_CTX, "format": "json", "retries": 0},
        "prompt": {"version": args.prompt, "sha256": hashlib.sha256(PROMPTS[args.prompt].encode()).hexdigest(),
                   "fix_prompt_sha256": hashlib.sha256(FIX_PROMPT.encode()).hexdigest()},
        "tolerances": {"diagnosis": "temperature 0 and a fixed seed: the same machine and Ollama version should repeat each reply; a repeat check of the none setting is stored",
                       "tokens_and_chars": "exact for the same code and prompt text"},
        "what_the_model_sees": "test id, run summary, and per setting the code described in docs/EVAL.md. Failure messages are never shown. "
                               "Comment lines inserted by the injection operators and the message part of their asserts are removed (injected only).",
        "limitations": [
            *run_eval.LIMITATIONS[args.label],
            "Identifiers chosen by the injection operators (for example _FLAKEGUARD_ORDER_READY, _race_flag) stay in the code the model sees, so the code settings are easier than real code." if args.label == "injected" else
            "Planted tests are small hand-written files whose names and helper functions often state their purpose; nothing was removed from them.",
            "One model (3B parameters, 4-bit), one prompt, one decoding setting. A different prompt could move every number.",
            "26 injected flaky tests: a difference of a few tests between settings is inside the intervals.",
            "Fix metric: N=5. No figure there is a rate.",
        ],
    })
    if args.mask:
        prov["mask"] = {"map": MASK_MAP, "applies_to": "the code part of the prompt, settings " + ", ".join(settings),
                        "natural_cues_untouched": True, "note": "a separate run; results/injected/rq4.json is not changed"}
        prov["limitations"] = [x if not x.startswith("Identifiers chosen by the injection operators") else
                               "The seven identifiers only the injection operators write are replaced by _x1 to _x7 (map in provenance.mask). Natural cues stay, and so do the structures around the names (for example globals().get(...)), so the code is still easier than real code."
                               for x in prov["limitations"]]
    name = args.out or (f"rq4_tuning_{args.prompt}.json" if args.label == "planted" else "rq4.json")
    run_eval.write(REPO / "results" / args.label / name, {"provenance": prov, **body})
    for s, r in body["results"].items():
        m = r["diagnosis_matches"]
        print(f"{s:9} matches {m['k']}/{m['n']}  unreadable {r['unreadable_replies_counted_as_failures']}  chars mean {r['code_chars_sent']['mean']}  tokens mean {r['prompt_tokens']['mean']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
