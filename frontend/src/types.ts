/** Shapes the Python API hands back. Mirrors flakeguard/app/api.py. */

export type Via = "ast" | "jedi" | "-" | "";

/** One recorded navigation step. Mirrors navigator/trace.py TraceEvent. */
export interface TraceEvent {
  seq: number;
  phase: string;
  op: string;
  label: string;
  depth: number;
  via: Via;
  detail: string;
  path: string;
  line: number;
  end_line: number;
  weight: number;
  results: number;
  kept: number;
  duration_ms: number;
  ok: boolean;
  /** Chunk keys this step added to the result, so a replay can grow the tree
   *  in step with the trace. "<path>:<line>", or "smell:<name>". */
  produced: string[];
}

export interface TraceSummary {
  test_id: string;
  events: number;
  max_depth: number;
  ast_names: number;
  jedi_goto_calls: number;
  jedi_infer_calls: number;
  jedi_calls: number;
  jedi_hits: number;
  jedi_hit_rate: number;
  expand_rounds: number;
  events_by_phase: Record<string, number>;
  ms_by_phase: Record<string, number>;
  total_ms: number;
}

/** A flat node row, as knowledge_tree.rows() produces it. */
export interface TreeRow {
  id: string;
  parent: string;
  label: string;
  kind: string;
  edge: string;
  via: Via;
  depth: number;
  score: number;
  path: string;
  start_line: number;
  end_line: number;
  lines: number;
  detail: string;
}

export interface TreeNode {
  node_id: string;
  kind: string;
  label: string;
  edge: string;
  via: Via;
  path: string;
  start_line: number;
  end_line: number;
  depth: number;
  score: number;
  detail: string;
  text?: string;
  children: TreeNode[];
}

export interface TreeStats {
  test_id: string;
  nodes: number;
  edges: number;
  max_depth: number;
  files_touched: number;
  branching_factor: number;
  nodes_by_depth: Record<string, number>;
  nodes_by_edge: Record<string, number>;
  nodes_by_kind: Record<string, number>;
}

export interface Explain {
  test_id: string;
  tree: { test_id: string; repo: string; sha: string; stats: TreeStats; root: TreeNode };
  trace: { test_id: string; summary: TraceSummary; by_depth: Record<string, number>; events: TraceEvent[] };
  test_source: { path: string; start_line: number; end_line: number; text: string } | null;
  result: {
    code_under_test: { path: string; start_line: number; end_line: number; kind: string; score: number }[];
    fixtures: string[];
    shared_state: string[];
    smells: string[];
  };
  rendered?: string;
  rows?: TreeRow[];
  label?: string;
  root_cause?: string;
  source?: "live" | "export";
  elapsed_ms?: number;
  resolved?: boolean;
  repo?: { path: string; name: string };
}

export interface NavSummary {
  repo: string;
  sha: string;
  gold: string;
  cases: number;
  resolved: number;
  resolution_rate: number;
  unresolved_cases: string[];
  mean_tree_nodes: number;
  mean_tree_depth: number;
  max_tree_depth: number;
  trees_with_depth_2plus: number;
  mean_ast_names: number;
  total_jedi_calls: number;
  jedi_hit_rate: number;
  median_ms: number;
  max_ms: number;
}

export interface CaseRef {
  test_id: string;
  file: string;
  label: string;
  root_cause: string;
  nodes: number;
  max_depth: number;
  jedi_calls: number;
  steps: number;
}

export interface TreeSet {
  name: string;
  summary: NavSummary;
  cases: CaseRef[];
  trace_rows: Record<string, number | string | null>[];
}

export interface GateCheck {
  name: string;
  stage: string;
  status: "pass" | "warn" | "fail" | "skip";
  detail: string;
  why: string;
  measured: number | null;
  threshold: number | null;
  source: string;
}

export interface PipelineStatus {
  generated_at: string;
  commit: string;
  branch: string;
  workflow: string;
  python: string;
  strict: boolean;
  promote: boolean;
  verdict: string;
  counts: { pass: number; fail: number; warn: number; skip: number };
  checks: GateCheck[];
}

export interface MetricRow {
  [key: string]: number | string | null;
}

export interface ResultsPayload {
  llm: MetricRow[];
  baselines: MetricRow[];
  navigation: MetricRow[];
  nav_summary: NavSummary | null;
  external_summary: NavSummary | null;
  failures: MetricRow[];
  labels: { id: string; label: string; root_cause: string; file_path?: string }[];
  label_counts: Record<string, number>;
  root_cause_counts: Record<string, number>;
}

export interface Suggestion {
  repo: string;
  repo_name: string;
  test_id: string;
  note: string;
}

export interface RepoInfo {
  path: string;
  kind: "local" | "clone";
  url: string;
  sha: string;
  name: string;
  cached: boolean;
}

export interface DiscoveredTest {
  test_id: string;
  file: string;
  name: string;
  cls: string;
  line: number;
}

export interface Discovery {
  repo: RepoInfo;
  tests: DiscoveredTest[];
  files: { file: string; tests: number }[];
  count: number;
  truncated: boolean;
  cache_mb: number;
}

/* -------------------------------------------------- Triage & Pipeline contracts ---- */

export interface Finding {
  test_id: string;
  verdict: "flaky" | "real" | "stable" | "abstain";
  root_cause: string;
  plain_sentence: string;
  observed?: string;
  reproduced?: string;
  confirmed_by_intervention?: string;
  evidence_tier?: "observed" | "reproduced" | "confirmed_by_intervention" | string;
  evidence_summary?: string[];
  polluter_test_id?: string;
  polluter_file?: string;
  polluter_line?: number;
  polluter_snippet?: string;
  tags?: string[];
  can_quarantine?: boolean;
  has_fix?: boolean;
  fail_rate?: number;
}

export interface StageItem {
  name: string;
  status: "done" | "running" | "waiting" | "error";
  duration_s?: number;
}

export interface HumanStep {
  step: string;
  completed: boolean;
}

export interface RunItem {
  id: string;
  run_id?: string;
  target: string;
  git_sha?: string;
  status: "Running" | "Done" | "Could not build" | "error" | string;
  trigger: string;
  created_at?: string;
  stages?: StageItem[];
  human_steps?: HumanStep[];
  latest_events?: string[];
  findings?: Finding[];
  github_url?: string;
}

export interface Eval3Provenance {
  command: string;
  git_sha: string;
  time: string;
  data_label: "planted" | "injected" | "natural";
}

export interface Eval3Row {
  method: string;
  f1: string;
  root_cause_accuracy: string;
  false_quarantine: string;
  under_review?: boolean;
  source: string;
  provenance: Eval3Provenance;
}

export interface Eval3Payload {
  planted: Eval3Row[];
  injected: Eval3Row[];
  natural: Eval3Row[];
  git_sha: string;
}

export interface AskResponse {
  answer: string;
  citations: string[];
  refusal?: boolean;
  provenance?: Record<string, string>;
}

export interface FixResponse {
  patch?: string;
  polluter_test_id?: string;
  fixed?: boolean;
  message?: string;
}

