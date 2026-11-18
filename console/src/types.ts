/**
 * API CONTRACT. The backend must return exactly these shapes.
 * If the engine produces something different, adapt it in the backend, not here.
 * Rule: nothing in these shapes may be invented. Missing data is null, never a placeholder.
 */

export type Verdict = 'flaky' | 'real' | 'unknown';
export type NodeStatus = Verdict | 'polluter' | 'clean';
export type EvidenceTier = 'observed' | 'reproduced' | 'intervention-confirmed';
export type Severity = 'blocking' | 'suggestion' | 'needs-evidence';
export type StageState = 'done' | 'running' | 'pending' | 'failed';
export type RunCell = 'pass' | 'fail' | 'none';
export type RunMode = 'actions' | 'local' | 'recorded';
export type LabelType = 'injected' | 'natural' | 'planted';

export type ScreenState =
  | 'first-run'
  | 'actions-unavailable'
  | 'docker-not-running'
  | 'scan-incomplete'
  | 'recorded-run'
  | 'no-findings'
  | 'quarantine-refused'
  | 'post-merge'
  | 'ask-nothing';

export interface Stage {
  id: string;
  name: string;
  detail: string;
  tool: string;
  time: string | null; // "6 s", "running", "waiting" are rendered by the UI from state
  state: StageState;
}

export interface MatrixRow {
  label: string; // Baseline | Shuffled | Isolated
  summary: string;
  cells: RunCell[];
}

export interface PrInfo {
  number: number;
  title: string;
  state: 'open' | 'merged' | 'closed';
  checkState: string; // "in progress" | "complete" | ...
  postMergeState: string; // "waiting for merge" | "no evidence in 10 runs" | ...
  prUrl: string | null;
  runUrl: string | null;
}

export interface RunStatus {
  id: string;
  target: string;
  mode: RunMode;
  status: 'idle' | 'running' | 'complete' | 'failed';
  pr: PrInfo | null;
  stages: Stage[];
  current: { test: string; condition: string } | null;
  counters: { runsDone: number; runsTotal: number; failures: number; flagged: number };
  matrix: MatrixRow[];
  notice: { kind: ScreenState; detail?: string } | null; // drives the banners
}

export interface CodeLine {
  n: number;
  t: string;
  note?: string;
  hot?: boolean;
}
export interface CodeSnippet {
  file: string;
  role: 'the polluter' | 'the victim';
  lines: CodeLine[];
}
export interface LivesChip {
  text: string;
  tone: 'plain' | 'read' | 'write';
}

export interface FixPreview {
  summary: string;
  file: string;
  diff: string[]; // lines starting with "+" / "-" / " "
  checked: string; // "20 shuffled runs, 0 failures"
  doesNotProve: string;
}

export interface Finding {
  id: string;
  test: string;
  file: string;
  line: number;
  verdict: Verdict;
  subtype: string | null; // "order-dependent"
  severity: Severity;
  evidenceTier: EvidenceTier;
  summaryLine: string;
  why: string;
  evidence: string[];
  lives: LivesChip[];
  did: string;
  limits: string;
  writer: CodeSnippet | null;
  reader: CodeSnippet | null;
  repro: string | null;
  fix: FixPreview | null;
  quarantine: { allowed: boolean; reason: string | null };
}

export interface TreeNode {
  id: string;
  kind: 'repo' | 'file' | 'test';
  name: string;
  path: string | null; // "tests/test_report.py:39"
  status: NodeStatus;
  label: string; // "Flaky · order-dependent", "Passes in every run"
  faults: number; // roll-up for repo and file nodes
  findingId: string | null;
  children: TreeNode[];
}
export interface SharedState {
  id: string;
  name: string; // CACHE
  path: string; // src/inventory/cache.py:4
  note: string;
  writers: string[]; // test node ids
  readers: string[]; // test node ids
}
export interface TreeData {
  root: TreeNode;
  sharedState: SharedState[];
}

export interface ResultsTable {
  columns: string[];
  rows: (string | null)[][]; // null renders as a dash
}
export interface Provenance {
  dataset: string | null;
  labelType: LabelType;
  n: number | null;
  command: string | null;
  date: string | null;
  commit: string | null;
}
export interface ResultsData {
  ablation: { table: ResultsTable; provenance: Provenance };
  baselines: { table: ResultsTable; provenance: Provenance };
  runsToDecision: { fixed: string | null; adaptive: string | null };
  triage: { redPrsCleared: string | null; realQuarantined: string | null };
}

export interface RiskySpot {
  where: string;
  what: string;
  why: string;
  test: string | null;
}
export interface NoTestsPlan {
  repo: string;
  steps: { name: string; state: StageState }[];
  spots: RiskySpot[];
  example: { risky: CodeSnippet; test: CodeSnippet } | null;
  checks: { label: string; ok: boolean | null }[];
}

export interface StartRunRequest {
  target: string; // "owner/repo#7" or repo URL
  source: 'pull-request' | 'repo' | 'sample';
  runs: number;
  docker: boolean;
}
export interface AskAnswer {
  text: string;
  citations: { label: string; file: string; line: number }[];
  chunks: number;
}
