from __future__ import annotations

from flakeguard.evidence.template import EvidenceSnippet, build_evidence_bundle

PLANTED_BUNDLES: dict[str, str] = {}

# 1. Order Dep
PLANTED_BUNDLES["order_dep"] = build_evidence_bundle(
    test_id="synthetic/tests/test_order_dep.py::test_b_needs_registered",
    run_stats={
        "total_runs": 20,
        "pass_rate": "50%",
        "fail_rate": "50%",
        "failing_seeds": "Seeds 1, 3, 5, 8, 12 (fails whenever test_b_needs_registered runs before test_a_register)",
    },
    log_excerpt="""
FAILED synthetic/tests/test_order_dep.py::test_b_needs_registered - AssertionError: assert 'apple' in []
 + where [] = registry()
E AssertionError: assert 'apple' in []
E  + where [] = <function registry at 0x0000019E62D28A40>()
    """.strip(),
    test_body="""
def test_b_needs_registered():
    assert "apple" in shop.registry()
    """.strip(),
    snippets=[
        EvidenceSnippet(
            evidence_id="E1",
            title="register & registry functions",
            kind="code_under_test",
            content="""
def register(name): _registry.append(name)
def registry(): return list(_registry)
            """.strip(),
        ),
        EvidenceSnippet(
            evidence_id="E2",
            title="module global _registry",
            kind="shared_state",
            content="_registry = []",
        ),
        EvidenceSnippet(
            evidence_id="E3",
            title="prerequisite test_a_register",
            kind="fixture",
            content="""
def test_a_register():
    shop.register("apple")
            """.strip(),
        ),
    ],
)

# 2. Shared State
PLANTED_BUNDLES["shared_state"] = build_evidence_bundle(
    test_id="synthetic/tests/test_shared_state.py::test_expects_cache",
    run_stats={
        "total_runs": 20,
        "pass_rate": "50%",
        "fail_rate": "50%",
        "failing_seeds": "Seeds 2, 4, 6, 9, 14 (fails whenever test_pollutes_cache runs first)",
    },
    log_excerpt="""
FAILED synthetic/tests/test_shared_state.py::test_expects_cache - KeyError: 'rate'
E KeyError: 'rate'
E   File "synthetic/src/shop.py", line 18, in apply_rate
E     return x * _cache["rate"]
    """.strip(),
    test_body="""
def test_expects_cache():
    assert shop.apply_rate(10) == 10
    """.strip(),
    snippets=[
        EvidenceSnippet(
            evidence_id="E1",
            title="apply_rate function",
            kind="code_under_test",
            content="""
def apply_rate(x): return x * _cache["rate"]
            """.strip(),
        ),
        EvidenceSnippet(
            evidence_id="E2",
            title="module level cache",
            kind="shared_state",
            content='_cache = {"rate": 1.0}',
        ),
        EvidenceSnippet(
            evidence_id="E3",
            title="polluting test test_pollutes_cache",
            kind="fixture",
            content="""
def test_pollutes_cache():
    shop._cache.clear()
            """.strip(),
        ),
    ],
)

# 3. Timing
PLANTED_BUNDLES["timing"] = build_evidence_bundle(
    test_id="synthetic/tests/test_timing.py::test_job_finishes",
    run_stats={
        "total_runs": 20,
        "pass_rate": "65%",
        "fail_rate": "35%",
        "failing_seeds": "Seeds 3, 7, 11, 15 (fails when background thread duration exceeds 0.05s sleep)",
    },
    log_excerpt="""
FAILED synthetic/tests/test_timing.py::test_job_finishes - AssertionError: assert False
E AssertionError: assert False
E  + where False = shop.JOB_DONE
    """.strip(),
    test_body="""
def test_job_finishes():
    shop.JOB_DONE = False
    threading.Thread(target=shop.slow_job).start()
    time.sleep(0.05)
    assert shop.JOB_DONE
    """.strip(),
    snippets=[
        EvidenceSnippet(
            evidence_id="E1",
            title="slow_job function",
            kind="code_under_test",
            content="""
def slow_job():
    global JOB_DONE
    time.sleep(random.uniform(0.01, 0.08))
    JOB_DONE = True
            """.strip(),
        ),
        EvidenceSnippet(
            evidence_id="E2",
            title="JOB_DONE global flag",
            kind="shared_state",
            content="JOB_DONE = False",
        ),
    ],
)

# 4. Randomness
PLANTED_BUNDLES["randomness"] = build_evidence_bundle(
    test_id="synthetic/tests/test_randomness.py::test_discount_is_small",
    run_stats={
        "total_runs": 20,
        "pass_rate": "95%",
        "fail_rate": "5%",
        "failing_seeds": "Seed 18 (fails when random.random() >= 0.9)",
    },
    log_excerpt="""
FAILED synthetic/tests/test_randomness.py::test_discount_is_small - AssertionError: assert 0.94123 > 0.9
E AssertionError: assert 0.94123 < 0.9
E  + where 0.94123 = pick_discount()
    """.strip(),
    test_body="""
def test_discount_is_small():
    assert shop.pick_discount() < 0.9
    """.strip(),
    snippets=[
        EvidenceSnippet(
            evidence_id="E1",
            title="pick_discount function",
            kind="code_under_test",
            content="""
def pick_discount(): return random.random()
            """.strip(),
        ),
    ],
)

# 5. Time / TimeZone
PLANTED_BUNDLES["time_tz"] = build_evidence_bundle(
    test_id="synthetic/tests/test_time_tz.py::test_greeting_is_day",
    run_stats={
        "total_runs": 20,
        "pass_rate": "100% (Daytime)",
        "fail_rate": "0% (Daytime), 100% (Nighttime 22:00-05:00)",
        "failing_seeds": "Clock-dependent: fails when local time is nighttime",
    },
    log_excerpt="""
FAILED synthetic/tests/test_time_tz.py::test_greeting_is_day
AssertionError: assert 'Good night' == 'Good day'
 + where 'Good night' = greeting(datetime.datetime(2026, 10, 3, 23, 0, 0))
    """.strip(),
    test_body="""
def test_greeting_is_day():
    assert shop.greeting(datetime.now()) == "Good day"
    """.strip(),
    snippets=[
        EvidenceSnippet(
            evidence_id="E1",
            title="greeting function",
            kind="code_under_test",
            content="""
def greeting(now): return "Good night" if now.hour >= 22 or now.hour < 5 else "Good day"
            """.strip(),
        ),
    ],
)

# 6. Real Failure
PLANTED_BUNDLES["real_fail"] = build_evidence_bundle(
    test_id="synthetic/tests/test_real_failures.py::test_rounding",
    run_stats={
        "total_runs": 20,
        "pass_rate": "0%",
        "fail_rate": "100%",
        "failing_seeds": "All seeds (always fails)",
    },
    log_excerpt="""
FAILED synthetic/tests/test_real_failures.py::test_rounding - assert 10 == 11
E AssertionError: assert 10 == 11
E  + where 10 = total_rounded([10.6])
    """.strip(),
    test_body="""
def test_rounding():
    assert shop.total_rounded([10.6]) == 11
    """.strip(),
    snippets=[
        EvidenceSnippet(
            evidence_id="E1",
            title="total_rounded function",
            kind="code_under_test",
            content="""
def total_rounded(prices): return int(total(prices))
            """.strip(),
        ),
    ],
)
