/**
 * Mock backend. Everything here is DEMO DATA and the UI shows a "Demo data" badge whenever
 * VITE_USE_MOCK=1. The shapes are identical to the real API (see ../types.ts).
 */
import type {
  AskAnswer, Finding, NoTestsPlan, ResultsData, RunCell, RunStatus, Stage, StartRunRequest, TreeData,
} from '../types';

const T0_KEY = 'fg-mock-start';

const STAGE_DEFS: Omit<Stage, 'state' | 'time'>[] = [
  { id: 'checkout', name: 'Checkout', detail: 'demo/inventory at the PR head commit', tool: 'GitHub Actions' },
  { id: 'install', name: 'Install', detail: 'Dependencies restored from cache', tool: 'pip' },
  { id: 'baseline', name: 'Baseline', detail: '3 runs in default order, 0 failed', tool: 'pytest' },
  { id: 'shuffled', name: 'Shuffled runs', detail: 'Shuffled order, ten seeds', tool: 'pytest, shuffled' },
  { id: 'isolated', name: 'Isolated runs', detail: 'Each flagged test run alone', tool: 'pytest' },
  { id: 'bisect', name: 'Bisection', detail: 'Find the test that pollutes shared state', tool: 'FlakeGuard evidence engine' },
  { id: 'retrieval', name: 'Retrieval', detail: 'Pull the code around the flagged test', tool: 'AST + Jedi, LangChain' },
  { id: 'verdict', name: 'Verdict', detail: 'Flaky, real or unknown, with evidence', tool: 'LLM' },
  { id: 'comment', name: 'PR comment', detail: 'Post or update one comment on the PR', tool: 'GitHub API' },
];

const SHUFFLED_CODE = 'pfpffpppfp'; // 4 failures in 10 runs, matches the Findings example

export function mockStart(_req: StartRunRequest): { id: string } {
  sessionStorage.setItem(T0_KEY, String(Date.now()));
  return { id: 'mock-run-1' };
}

export function mockRun(): RunStatus {
  const t0 = Number(sessionStorage.getItem(T0_KEY) ?? 0);
  if (!t0) {
    return {
      id: 'none', target: '', mode: 'recorded', status: 'idle', pr: null, stages: [], current: null,
      counters: { runsDone: 0, runsTotal: 10, failures: 0, flagged: 0 }, matrix: [],
      notice: { kind: 'first-run' },
    };
  }
  const step = Math.floor((Date.now() - t0) / 2000); // one stage per 2 s, shuffled takes 5 ticks
  // stage index at time step: 0..2 early stages, shuffled spans ticks 3..7, then rest
  const idx = step <= 2 ? step : step <= 7 ? 3 : step - 4;
  const shuffledDone = step < 3 ? 0 : Math.min(10, step - 2) * 2; // up to 10
  const stages: Stage[] = STAGE_DEFS.map((d, i) => {
    const state = i < idx ? 'done' : i === idx ? 'running' : 'pending';
    return { ...d, state: step >= 13 ? 'done' : state, time: state === 'done' ? `${6 + i * 3} s` : null };
  });
  const toCells = (code: string, upto: number): RunCell[] =>
    code.split('').map((c, i) => (i < upto ? (c === 'p' ? 'pass' : 'fail') : 'none'));
  const sh = toCells(SHUFFLED_CODE, shuffledDone);
  const done = step >= 13;
  return {
    id: 'mock-run-1',
    target: 'demo/inventory#7',
    mode: 'recorded',
    status: done ? 'complete' : 'running',
    pr: {
      number: 7, title: 'Add stock cache', state: 'open',
      checkState: done ? 'complete' : 'in progress', postMergeState: 'waiting for merge',
      prUrl: null, runUrl: null,
    },
    stages,
    current: done ? null : { test: 'tests/test_report.py::test_report_total', condition: 'Shuffled order · seed 1042' },
    counters: {
      runsDone: Math.min(10, shuffledDone), runsTotal: 10,
      failures: sh.filter((c) => c === 'fail').length, flagged: idx >= 3 ? 1 : 0,
    },
    matrix: [
      { label: 'Baseline', summary: '3 runs, all passed', cells: toCells('ppp', idx >= 2 ? 3 : 0) },
      { label: 'Shuffled', summary: `${Math.min(10, shuffledDone)} of 10 run`, cells: sh },
      { label: 'Isolated', summary: idx >= 4 ? '3 runs, all passed' : 'not run yet', cells: toCells('ppp', idx >= 5 ? 3 : 0) },
    ],
    notice: { kind: 'recorded-run' },
  };
}

const writer = {
  file: 'tests/test_cache.py', role: 'the polluter' as const,
  lines: [
    { n: 21, t: 'def test_cache_warm():' },
    { n: 22, t: '    stock = StockService()' },
    { n: 23, t: '    CACHE["sku-1"] = 40', hot: true, note: 'Writes shared state and never clears it.' },
    { n: 24, t: '    assert stock.available("sku-1") == 40' },
    { n: 25, t: '' },
  ],
};
const reader = {
  file: 'tests/test_report.py', role: 'the victim' as const,
  lines: [
    { n: 39, t: 'def test_report_total():' },
    { n: 40, t: '    report = Report()' },
    { n: 41, t: '    total = report.total("sku-1")', hot: true, note: 'Reads CACHE. Fails if test_cache_warm ran first.' },
    { n: 42, t: '    assert total == 0' },
    { n: 43, t: '' },
  ],
};

export const MOCK_FINDINGS: Finding[] = [
  {
    id: 'f-real', test: 'test_reserve_negative', file: 'tests/test_stock.py', line: 12, verdict: 'real',
    subtype: null, severity: 'blocking', evidenceTier: 'observed',
    summaryLine: 'Real failure · failed in 10 of 10 runs. Quarantine refused.',
    why: 'This test fails in every run, in every order. That points to a bug, not flakiness.',
    evidence: ['Failed in 10 of 10 shuffled runs.', 'Failed 3 of 3 when run alone.'],
    lives: [{ text: 'tests/', tone: 'plain' }, { text: 'test_stock.py', tone: 'plain' }, { text: 'test_reserve_negative', tone: 'plain' }],
    did: 'Posted this finding on PR #7. Nothing else has been changed.',
    limits: 'The cause is not diagnosed here. The test fails consistently.',
    writer: null, reader: null, repro: null, fix: null,
    quarantine: { allowed: false, reason: 'Fails in 10 of 10 runs, so it looks like a real bug.' },
  },
  {
    id: 'f-flaky', test: 'test_report_total', file: 'tests/test_report.py', line: 39, verdict: 'flaky',
    subtype: 'order-dependent', severity: 'suggestion', evidenceTier: 'reproduced',
    summaryLine: 'Order-dependent · evidence: reproduced',
    why: 'This test reads the shared CACHE at test_report.py:41. Another test writes it at test_cache.py:23 and never clears it. If the writer runs first, this test fails.',
    evidence: [
      'Failed in 4 of 10 shuffled runs; passed 3 of 3 in default order and 3 of 3 alone.',
      'Bisection names test_cache_warm as the polluter (narrowed from 38 tests in 5 steps).',
      'The failing code path is outside the lines this PR changed.',
    ],
    lives: [
      { text: 'tests/', tone: 'plain' }, { text: 'test_report.py', tone: 'plain' },
      { text: 'test_report_total', tone: 'plain' }, { text: 'reads CACHE', tone: 'read' },
      { text: 'written by test_cache_warm', tone: 'write' },
    ],
    did: 'Posted this finding on PR #7. Nothing else has been changed.',
    limits: 'The order-dependence is shown for these two tests. Other causes of flakiness in this test are not ruled out.',
    writer, reader,
    repro: 'pytest tests/test_cache.py::test_cache_warm tests/test_report.py::test_report_total',
    fix: {
      summary: 'Clears the shared cache after every test so no test can leave state behind.',
      file: 'tests/conftest.py',
      diff: ['+ @pytest.fixture(autouse=True)', '+ def reset_cache():', '+     yield', '+     CACHE.clear()'],
      checked: '20 shuffled runs, 0 failures.',
      doesNotProve: 'the code is correct in orders that were not run.',
    },
    quarantine: { allowed: true, reason: null },
  },
  {
    id: 'f-unknown', test: 'test_sync_timeout', file: 'tests/test_sync.py', line: 8, verdict: 'unknown',
    subtype: null, severity: 'needs-evidence', evidenceTier: 'observed',
    summaryLine: '1 failure in 10 runs. Too few to call it flaky.',
    why: 'One failure in ten runs is too little to separate flakiness from noise.',
    evidence: ['Failed in 1 of 10 shuffled runs.', 'Rule of three: the failure rate could be up to about 30%.'],
    lives: [{ text: 'tests/', tone: 'plain' }, { text: 'test_sync.py', tone: 'plain' }, { text: 'test_sync_timeout', tone: 'plain' }],
    did: 'Posted this finding on PR #7. Nothing else has been changed.',
    limits: 'No cause found. More runs are needed.',
    writer: null, reader: null, repro: null, fix: null,
    quarantine: { allowed: true, reason: null },
  },
];

const leaf = (id: string, name: string, line: number, status: 'flaky' | 'real' | 'unknown' | 'polluter' | 'clean', label: string, findingId: string | null, file: string) => ({
  id, kind: 'test' as const, name, path: `tests/${file}:${line}`, status, label, faults: status === 'clean' ? 0 : 1, findingId, children: [],
});

export const MOCK_TREE: TreeData = {
  root: {
    id: 'repo', kind: 'repo', name: 'demo/inventory', path: null, status: 'clean', label: '7 tests · 3 faults', faults: 3, findingId: null,
    children: [
      { id: 'f1', kind: 'file', name: 'test_cache.py', path: 'tests/test_cache.py', status: 'polluter', label: '1 polluter', faults: 1, findingId: null,
        children: [leaf('t-warm', 'test_cache_warm', 21, 'polluter', 'Polluter · writes CACHE', null, 'test_cache.py')] },
      { id: 'f2', kind: 'file', name: 'test_report.py', path: 'tests/test_report.py', status: 'flaky', label: '1 flaky', faults: 1, findingId: null,
        children: [
          leaf('t-total', 'test_report_total', 39, 'flaky', 'Flaky · order-dependent', 'f-flaky', 'test_report.py'),
          leaf('t-empty', 'test_report_empty', 50, 'clean', 'Passes in every run', null, 'test_report.py'),
        ] },
      { id: 'f3', kind: 'file', name: 'test_stock.py', path: 'tests/test_stock.py', status: 'real', label: '1 real failure', faults: 1, findingId: null,
        children: [
          leaf('t-neg', 'test_reserve_negative', 12, 'real', 'Real failure · 10 of 10', 'f-real', 'test_stock.py'),
          leaf('t-ok', 'test_reserve_ok', 30, 'clean', 'Passes in every run', null, 'test_stock.py'),
        ] },
      { id: 'f4', kind: 'file', name: 'test_sync.py', path: 'tests/test_sync.py', status: 'unknown', label: '1 unknown', faults: 1, findingId: null,
        children: [
          leaf('t-sync', 'test_sync_timeout', 8, 'unknown', 'Unknown · 1 of 10 failed', 'f-unknown', 'test_sync.py'),
          leaf('t-syncok', 'test_sync_ok', 25, 'clean', 'Passes in every run', null, 'test_sync.py'),
        ] },
    ],
  },
  sharedState: [{ id: 's-cache', name: 'CACHE', path: 'src/inventory/cache.py:4', note: 'A dict shared by both tests', writers: ['t-warm'], readers: ['t-total'] }],
};

export const MOCK_RESULTS: ResultsData = {
  ablation: {
    table: { columns: ['Context given to the model', 'Diagnosis matches the known cause', 'Fix passes validation under shuffle', 'Code sent to the model'], rows: [] },
    provenance: { dataset: null, labelType: 'injected', n: null, command: null, date: null, commit: null },
  },
  baselines: {
    table: { columns: ['Method', 'Flaky tests found', 'Wrongly flagged', 'CI minutes used'], rows: [] },
    provenance: { dataset: null, labelType: 'injected', n: null, command: null, date: null, commit: null },
  },
  runsToDecision: { fixed: null, adaptive: null },
  triage: { redPrsCleared: null, realQuarantined: null },
  triageTable: null,
  notes: [],
  status: 'not run',
};

export const MOCK_NOTESTS: NoTestsPlan = {
  repo: 'demo/legacy-scripts',
  steps: [
    { name: 'Find risky spots', state: 'done' }, { name: 'Write tests', state: 'done' },
    { name: 'Check them', state: 'running' }, { name: 'Open PR on your fork', state: 'pending' },
  ],
  spots: [
    { where: 'src/reports/daily.py:14', what: 'Reads the current date', why: 'The result changes every day', test: 'test_daily_header' },
    { where: 'src/reports/daily.py:31', what: 'Picks a random sample', why: 'The result changes every run', test: 'test_daily_sample' },
  ],
  example: {
    risky: { file: 'src/reports/daily.py', role: 'the polluter', lines: [
      { n: 13, t: 'def header():' }, { n: 14, t: '    return f"Report {date.today()}"', hot: true, note: 'Depends on the clock.' } ] },
    test: { file: 'tests/test_daily.py', role: 'the victim', lines: [
      { n: 5, t: '@freeze_time("2026-01-05")', hot: true }, { n: 6, t: 'def test_daily_header():', hot: true }, { n: 7, t: '    assert header() == "Report 2026-01-05"' } ] },
  },
  checks: [
    { label: 'Runs without errors', ok: true },
    { label: 'Passes on the current commit', ok: true },
    { label: 'Same result in 10 shuffled runs', ok: true },
  ],
};

export function mockAsk(q: string): AskAnswer {
  if (q.trim().length < 3) return { text: '', citations: [], chunks: 0 };
  return {
    text: 'test_report_total reads CACHE. test_cache_warm sets CACHE["sku-1"] and nothing clears it, so the result depends on which test runs first.',
    citations: [
      { label: 'tests/test_report.py:41', file: 'tests/test_report.py', line: 41 },
      { label: 'tests/test_cache.py:23', file: 'tests/test_cache.py', line: 23 },
    ],
    chunks: 2,
  };
}
