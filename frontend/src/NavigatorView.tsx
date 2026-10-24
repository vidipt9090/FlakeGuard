import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api, useAsync } from "./api";
import type { Discovery, Explain, Suggestion, TreeSet } from "./types";
import { DepthKey, TreeCanvas } from "./TreeCanvas";
import { SourcePane } from "./SourcePane";
import { TracePlayer } from "./TracePlayer";
import { headline, type PlacedNode } from "./tree";
import {
  Badge,
  Button,
  Card,
  EDGE_HELP,
  ErrorBox,
  Empty,
  Field,
  ResolverLegend,
  SectionTitle,
  Segmented,
  Spinner,
  Stat,
  fmt,
  ms,
  pct,
  shortId,
} from "./ui";
import "./NavigatorView.css";

/* The centrepiece.
 *
 * Left: the test's source, highlighted as the AST walk reads it.
 * Right: the knowledge tree, growing one node per step.
 * Below: the transport, the phase raster, and what the current step did.
 *
 * Two sources of data, and the difference is stated on screen rather than
 * hidden: an exported run (fast, works with no checkout) or a LIVE run that
 * navigates a repository on this machine when you press the button.
 */

type Mode = "export" | "live";

export function NavigatorView() {
  const [mode, setMode] = useState<Mode>("export");
  const sets = useAsync(() => api.sets(), []);
  const hints = useAsync(() => api.suggestions(), []);

  const [setName, setSetName] = useState<string>("");
  const [testId, setTestId] = useState<string>("");
  const [explain, setExplain] = useState<Explain | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  // replay state
  const [step, setStep] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const [selected, setSelected] = useState<PlacedNode | null>(null);
  const [depthLimit, setDepthLimit] = useState<number>(99);

  const activeSet: TreeSet | undefined = useMemo(
    () => sets.data?.sets.find((s) => s.name === setName) ?? sets.data?.sets[0],
    [sets.data, setName],
  );

  // Default to the most interesting case in the set: deepest tree, then most
  // nodes. A demo should not open on the dullest example in the list.
  useEffect(() => {
    if (!activeSet || testId) return;
    const best = [...activeSet.cases].sort(
      (a, b) => b.max_depth - a.max_depth || b.nodes - a.nodes,
    )[0];
    if (best) {
      setSetName(activeSet.name);
      setTestId(best.test_id);
    }
  }, [activeSet, testId]);

  const loadExport = useCallback(
    async (set: string, id: string) => {
      setLoading(true);
      setError(null);
      setPlaying(false);
      try {
        const payload = await api.tree(set, id);
        setExplain(payload);
        setStep(payload.trace.events.length);
        setSelected(null);
        setDepthLimit(99);
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(String(err), 0));
        setExplain(null);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (mode === "export" && activeSet && testId) {
      void loadExport(activeSet.name, testId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, activeSet?.name, testId]);

  const runLive = useCallback(async (repo: string, repoName: string, id: string) => {
    setLoading(true);
    setError(null);
    setPlaying(false);
    try {
      const payload = await api.navigate({ repo, repo_name: repoName, test_id: id });
      setExplain(payload);
      setStep(1);
      setSelected(null);
      setDepthLimit(99);
      // Start the replay from the top: a live run is worth watching.
      setPlaying(true);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(String(err), 0));
      setExplain(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const events = explain?.trace.events ?? [];
  const rows = explain?.rows ?? [];
  const head = explain ? headline(explain) : null;

  return (
    <div className="nav-view">
      <SectionTitle
        hint={
          <>
            The navigator turns a failing test id into the code that test actually
            exercises. Two machines run in sequence: the <b>AST walk</b> reads the test
            body as plain syntax and writes down every name it sees, then <b>jedi</b>{" "}
            resolves each one — <code>goto</code> for a name, <code>infer</code> for an
            expression whose <i>type</i> is the real target. Press play and watch the
            tree get built.
          </>
        }
        right={
          <Segmented<Mode>
            value={mode}
            onChange={(m) => {
              setMode(m);
              setExplain(null);
              setError(null);
            }}
            options={[
              { value: "export", label: "Exported runs", title: "What the pipeline produced" },
              { value: "live", label: "Live run", title: "Navigate a repo on this machine now" },
            ]}
          />
        }
      >
        Knowledge tree
      </SectionTitle>

      {mode === "export" ? (
        <ExportPicker
          sets={sets.data?.sets ?? []}
          loading={sets.loading}
          error={sets.error}
          setName={activeSet?.name ?? ""}
          testId={testId}
          onSet={(n) => {
            setSetName(n);
            setTestId("");
            setExplain(null);
          }}
          onCase={setTestId}
        />
      ) : (
        <LivePanel
          suggestions={hints.data?.suggestions ?? []}
          busy={loading}
          onRun={runLive}
        />
      )}

      {error ? <ErrorBox message={error.message} hint={error.hint} /> : null}
      {loading ? <Spinner label={mode === "live" ? "Navigating…" : "Loading…"} /> : null}

      {explain && head ? (
        <>
          <div className="nav-stats stat-row">
            <Stat value={head.nodes} label="nodes in tree" />
            <Stat value={head.depth} label="max hop depth" />
            <Stat value={head.astNames} label="names the AST found" tone="ast" />
            <Stat value={head.gotoCalls} label="jedi.goto calls" tone="jedi" />
            <Stat value={head.inferCalls} label="jedi.infer calls" tone="jedi" />
            <Stat value={pct(head.hitRate)} label="jedi hit rate" />
            <Stat value={ms(head.ms)} label="time taken" tone="plain" />
          </div>

          <div className="nav-meta">
            <Badge tone={explain.source === "live" ? "good" : "plain"} dot>
              {explain.source === "live" ? "live run" : "exported run"}
            </Badge>
            <span className="nav-testid mono">{explain.test_id}</span>
            {explain.label ? <Badge>label: {explain.label}</Badge> : null}
            {explain.root_cause ? <Badge>cause: {explain.root_cause}</Badge> : null}
            {explain.resolved === false ? (
              <Badge tone="warn">resolved to nothing — the trace still shows where it stopped</Badge>
            ) : null}
          </div>

          <div className="nav-panes">
            <SourcePane source={explain.test_source} events={events} step={step} />

            <Card pad={false} className="tree-card">
              <div className="tree-card-head">
                <ResolverLegend
                  note={
                    <>
                      shape = edge type · size = score · left→right = hops from the test
                    </>
                  }
                />
                <div className="tree-card-tools">
                  <DepthKey maxDepth={head.depth} />
                  {head.depth > 0 ? (
                    <div className="depth-filter">
                      <span>show hops ≤</span>
                      <input
                        type="range"
                        min={0}
                        max={head.depth}
                        value={Math.min(depthLimit, head.depth)}
                        onChange={(e) => setDepthLimit(Number(e.target.value))}
                        aria-label="Maximum hop depth to show"
                      />
                      <b>{Math.min(depthLimit, head.depth)}</b>
                    </div>
                  ) : null}
                </div>
              </div>
              <TreeCanvas
                rows={rows}
                events={events}
                step={step}
                selectedId={selected?.id ?? null}
                onSelect={setSelected}
                maxDepthShown={Math.min(depthLimit, head.depth)}
              />
            </Card>
          </div>

          <TracePlayer
            events={events}
            step={step}
            playing={playing}
            speed={speed}
            onStep={(s) => {
              setStep(s);
              if (s >= events.length) setPlaying(false);
            }}
            onPlayPause={() => {
              if (step >= events.length) setStep(1);
              setPlaying((p) => !p);
            }}
            onSpeed={setSpeed}
          />

          {selected ? <NodeDetail node={selected} /> : null}

          <div className="nav-lower">
            <Card>
              <SectionTitle hint="The same tree as text, exactly as the navigator renders it.">
                Tree
              </SectionTitle>
              <pre className="tree-text">{explain.rendered ?? "(not exported)"}</pre>
            </Card>
            <Card pad={false}>
              <div className="card-pad">
                <SectionTitle hint="Every node, with the edge that reached it and what that edge means.">
                  Nodes
                </SectionTitle>
              </div>
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th className="num">hop</th>
                      <th>edge</th>
                      <th>found by</th>
                      <th>name</th>
                      <th className="num">score</th>
                      <th>location</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows
                      .filter((r) => r.depth > 0)
                      .map((r) => (
                        <tr
                          key={r.id}
                          onClick={() => setSelected(selected?.id === r.id ? null : (r as PlacedNode))}
                          className={selected?.id === r.id ? "is-selected" : ""}
                        >
                          <td className="num">{r.depth}</td>
                          <td>
                            <Badge tone={r.via === "jedi" ? "jedi" : "ast"}>{r.edge}</Badge>
                          </td>
                          <td>{r.via}</td>
                          <td className="mono">{r.label}</td>
                          <td className="num">{fmt(r.score)}</td>
                          <td className="mono dim">
                            {r.path ? `${r.path}:${r.start_line}` : "—"}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>
        </>
      ) : null}

      {!explain && !loading && !error && mode === "live" ? (
        <Empty
          title="Pick a test and press Navigate"
          body="The navigator will resolve it against a real checkout on this machine and the replay below will show every step it took."
        />
      ) : null}
    </div>
  );
}

function ExportPicker({
  sets,
  loading,
  error,
  setName,
  testId,
  onSet,
  onCase,
}: {
  sets: TreeSet[];
  loading: boolean;
  error: ApiError | null;
  setName: string;
  testId: string;
  onSet: (n: string) => void;
  onCase: (id: string) => void;
}) {
  if (loading) return <Spinner label="Loading exported runs…" />;
  if (error) return <ErrorBox message={error.message} hint={error.hint} />;
  if (!sets.length) {
    return (
      <Empty
        title="No exported runs yet"
        body={
          <>
            Run <code>python scripts/export_knowledge_trees.py --with-text</code>. The
            pipeline's <code>navigate</code> stage does this on every push.
          </>
        }
      />
    );
  }

  const active = sets.find((s) => s.name === setName) ?? sets[0];
  const cases = [...active.cases].sort(
    (a, b) => b.max_depth - a.max_depth || b.nodes - a.nodes,
  );

  return (
    <Card className="picker">
      <div className="picker-row">
        <Field label="Repository" hint={`${active.summary?.cases ?? active.cases.length} cases exported`}>
          <select className="select" value={active.name} onChange={(e) => onSet(e.target.value)}>
            {sets.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="Test case"
          hint="Sorted by tree depth, then size — the most interesting first."
        >
          <select className="select" value={testId} onChange={(e) => onCase(e.target.value)}>
            {cases.map((c) => (
              <option key={c.test_id} value={c.test_id}>
                {shortId(c.test_id)} — {c.nodes} nodes, depth {c.max_depth}
                {c.label ? ` · ${c.label}` : ""}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {active.summary ? (
        <div className="picker-summary">
          <span>
            <b>{pct(active.summary.resolution_rate)}</b> resolved
          </span>
          <span>
            <b>{fmt(active.summary.mean_tree_nodes)}</b> mean nodes
          </span>
          <span>
            <b>{active.summary.trees_with_depth_2plus}</b> of {active.summary.cases} reach hop 2
          </span>
          <span>
            <b>{pct(active.summary.jedi_hit_rate)}</b> jedi hit rate
          </span>
          <span className="dim">
            {active.summary.repo}@{active.summary.sha}
          </span>
        </div>
      ) : null}
    </Card>
  );
}

function isUrl(spec: string): boolean {
  return /^(https?:\/\/|git@)/.test(spec.trim());
}

function LivePanel({
  suggestions,
  busy,
  onRun,
}: {
  suggestions: Suggestion[];
  busy: boolean;
  onRun: (repo: string, repoName: string, testId: string) => void;
}) {
  const [repo, setRepo] = useState(".");
  const [repoName, setRepoName] = useState("synthetic");
  const [testId, setTestId] = useState("synthetic/tests/test_suite_02.py::test_case_13");

  const [finding, setFinding] = useState(false);
  const [found, setFound] = useState<Discovery | null>(null);
  const [findError, setFindError] = useState<ApiError | null>(null);
  const [query, setQuery] = useState("");

  const url = isUrl(repo);

  const find = useCallback(async () => {
    setFinding(true);
    setFindError(null);
    setFound(null);
    try {
      const payload = await api.discover({ repo });
      setFound(payload);
      if (payload.repo.kind === "clone") setRepoName(payload.repo.name);
      if (payload.tests.length) setTestId(payload.tests[0].test_id);
    } catch (err) {
      setFindError(err instanceof ApiError ? err : new ApiError(String(err), 0));
    } finally {
      setFinding(false);
    }
  }, [repo]);

  const matches = useMemo(() => {
    if (!found) return [];
    const q = query.trim().toLowerCase();
    const list = q
      ? found.tests.filter(
          (t) => t.test_id.toLowerCase().includes(q) || t.file.toLowerCase().includes(q),
        )
      : found.tests;
    return list.slice(0, 300);
  }, [found, query]);

  return (
    <Card className="live-panel">
      <div className="live-note">
        Nothing below is read from <code>results/</code>. Pressing Navigate imports the
        navigator and resolves this test id against real source, right now — the tree and
        every step of the trace are produced by the request.
      </div>

      <div className="live-row">
        <Field
          label="Repository"
          hint={
            url
              ? "A URL — it will be cloned (shallow) into .cache/repos and parsed, never run."
              : "A path on this machine. '.' is FlakeGuard itself. You can also paste a repo URL."
          }
        >
          <input
            className="input"
            value={repo}
            onChange={(e) => {
              setRepo(e.target.value);
              setFound(null);
              setFindError(null);
            }}
            placeholder="path, or https://github.com/owner/repo"
            spellCheck={false}
          />
        </Field>
        <Field label="Label">
          <input className="input" value={repoName} onChange={(e) => setRepoName(e.target.value)} />
        </Field>
        <Field label="Test id" hint="path::Class::test_name">
          <input
            className="input"
            value={testId}
            onChange={(e) => setTestId(e.target.value)}
            spellCheck={false}
          />
        </Field>
        <div className="live-go">
          <Button onClick={find} disabled={finding || busy || !repo.trim()}>
            {finding ? (url ? "Cloning…" : "Scanning…") : "Find tests"}
          </Button>
          <Button
            variant="primary"
            onClick={() => onRun(repo, repoName, testId)}
            disabled={busy || finding || !testId.trim()}
          >
            {busy ? "Navigating…" : "Navigate"}
          </Button>
        </div>
      </div>

      {finding && url ? (
        <div className="live-progress">
          Cloning <code>{repo}</code> — shallow, single branch. First time only; it is
          cached afterwards.
        </div>
      ) : null}

      {findError ? <ErrorBox message={findError.message} hint={findError.hint} /> : null}

      {found ? (
        <div className="discovery">
          <div className="discovery-head">
            <Badge tone={found.repo.kind === "clone" ? "good" : "plain"} dot>
              {found.repo.kind === "clone"
                ? `${found.repo.cached ? "cached clone" : "cloned"} @ ${found.repo.sha}`
                : "local path"}
            </Badge>
            <span>
              <b>{found.count}</b> test{found.count === 1 ? "" : "s"} in{" "}
              <b>{found.files.length}</b> file{found.files.length === 1 ? "" : "s"}
              {found.truncated ? " (capped)" : ""}
            </span>
            <span className="dim">{found.cache_mb} MB cached</span>
          </div>

          {found.count === 0 ? (
            <Empty
              title="No test files found"
              body="Looked for test_*.py and *_test.py, skipping virtualenvs and node_modules."
            />
          ) : (
            <>
              <input
                className="input discovery-search"
                placeholder="Filter by file or test name…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                spellCheck={false}
              />
              <div className="discovery-list">
                {matches.map((t) => (
                  <button
                    key={t.test_id}
                    type="button"
                    className={`discovery-item ${t.test_id === testId ? "is-active" : ""}`}
                    onClick={() => setTestId(t.test_id)}
                    onDoubleClick={() => onRun(repo, repoName, t.test_id)}
                    title={`${t.test_id}
Double-click to navigate it`}
                  >
                    <b>
                      {t.cls ? `${t.cls}::` : ""}
                      {t.name}
                    </b>
                    <span>{t.file}</span>
                  </button>
                ))}
              </div>
              <p className="discovery-note">
                Click to select, double-click to navigate.
                {matches.length < found.count
                  ? ` Showing ${matches.length} of ${found.count}.`
                  : ""}
              </p>
            </>
          )}
        </div>
      ) : null}

      {suggestions.length && !found ? (
        <div className="live-suggestions">
          <span className="live-suggestions-label">Try:</span>
          {suggestions.map((s) => (
            <button
              key={s.test_id + s.repo}
              className="suggestion"
              onClick={() => {
                setRepo(s.repo);
                setRepoName(s.repo_name);
                setTestId(s.test_id);
                onRun(s.repo, s.repo_name, s.test_id);
              }}
              title={s.note}
              type="button"
            >
              <b>{shortId(s.test_id)}</b>
              <span>{s.note}</span>
            </button>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function NodeDetail({ node }: { node: PlacedNode }) {
  return (
    <Card className="node-detail">
      <div className="node-detail-head">
        <Badge tone={node.via === "jedi" ? "jedi" : "ast"} dot>
          {node.edge}
        </Badge>
        <span className="node-detail-name mono">{node.label}</span>
        <span className="node-detail-meta">hop {node.depth}</span>
        <span className="node-detail-meta">score {fmt(node.score)}</span>
        <span className="node-detail-meta mono">
          {node.path ? `${node.path}:${node.start_line}-${node.end_line}` : "—"}
        </span>
      </div>
      <p className="node-detail-why">{EDGE_HELP[node.edge] ?? node.detail}</p>
    </Card>
  );
}
