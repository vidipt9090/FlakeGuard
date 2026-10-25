import { useMemo, useState } from "react";
import { api, useAsync } from "./api";
import { Badge, Card, ErrorBox, Empty, SectionTitle, Spinner, Stat, depthColor, fmt, pct } from "./ui";
import "./DatasetView.css";

/* The benchmark itself: what is in it, how unstable each test actually is,
 * and what the navigator found for each case. The flip rate is the thing a
 * detector is trying to predict, so it belongs beside the labels. */

const CAUSE_LABEL: Record<string, string> = {
  order_dep: "order dependency",
  shared_state: "shared state",
  timing: "timing",
  randomness: "randomness",
  time_tz: "time / timezone",
  none: "none (stable or real)",
};

export function DatasetView() {
  const results = useAsync(() => api.results(), []);
  const runs = useAsync(() => api.runs(), []);
  const [filter, setFilter] = useState<string>("all");

  const navByCase = useMemo(() => {
    const map = new Map<string, Record<string, number | string | null>>();
    for (const row of results.data?.navigation ?? []) {
      map.set(String(row.case_id), row);
    }
    return map;
  }, [results.data]);

  const flipByCase = useMemo(() => {
    const map = new Map<string, number>();
    for (const t of runs.data?.tests ?? []) map.set(t.test_id, t.flip_rate);
    return map;
  }, [runs.data]);

  if (results.loading) return <Spinner label="Loading the benchmark…" />;
  if (results.error) return <ErrorBox message={results.error.message} hint={results.error.hint} />;
  if (!results.data) return <Empty title="No dataset" />;

  const d = results.data;
  const causes = Object.entries(d.root_cause_counts).sort((a, b) => b[1] - a[1]);
  const maxCause = Math.max(1, ...causes.map(([, n]) => n));
  const cases = d.labels.filter((l) => filter === "all" || l.label === filter);
  const maxFlip = Math.max(0.01, ...[...flipByCase.values()]);

  return (
    <div className="ds-view">
      <SectionTitle hint="31 neutralised cases: every test name and fixture uses a neutral identifier, with nothing in the source that reveals its root cause. The labels live in labels/labels.json, and CI fails the run if a name ever leaks one.">
        The planted benchmark
      </SectionTitle>

      <div className="stat-row">
        <Stat value={d.labels.length} label="test cases" />
        <Stat value={d.label_counts.flaky ?? 0} label="flaky" tone="warn" />
        <Stat value={d.label_counts.real ?? 0} label="real failures" tone="bad" />
        <Stat value={d.label_counts.stable ?? 0} label="stable" tone="good" />
        <Stat value={causes.length} label="root-cause families" />
      </div>

      <div className="ds-grid">
        <Card>
          <SectionTitle hint="How many cases carry each planted root cause.">
            Root causes
          </SectionTitle>
          <div className="cause-chart">
            {causes.map(([cause, n], i) => (
              <div key={cause} className="cause-row">
                <span className="cause-name">{CAUSE_LABEL[cause] ?? cause}</span>
                <div className="cause-track">
                  <div
                    className="cause-bar"
                    style={{
                      width: `${(n / maxCause) * 100}%`,
                      background: depthColor(i, Math.max(1, causes.length - 1)),
                    }}
                  />
                </div>
                <b className="cause-n">{n}</b>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionTitle hint="min(passes, fails) / runs across the shuffled runs. A stable test sits at zero; the higher the bar, the more often this test changed its mind.">
            Flip rate
          </SectionTitle>
          {runs.loading ? (
            <Spinner />
          ) : (
            <div className="flip-chart">
              {(runs.data?.tests ?? []).slice(0, 14).map((t) => (
                <div key={t.test_id} className="flip-row">
                  <span className="flip-name mono">{t.test_id.split("::").pop()}</span>
                  <div className="flip-track">
                    <div
                      className="flip-bar"
                      style={{ width: `${(t.flip_rate / maxFlip) * 100}%` }}
                    />
                  </div>
                  <b className="flip-n">{pct(t.flip_rate)}</b>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <SectionTitle
        hint="Every case, with its ground truth, how unstable it actually was, and what the navigator reached for it."
        right={
          <div className="ds-filters">
            {["all", "flaky", "real", "stable"].map((f) => (
              <button
                key={f}
                className={`ds-filter ${filter === f ? "is-active" : ""}`}
                onClick={() => setFilter(f)}
                type="button"
              >
                {f}
                {f !== "all" ? ` (${d.label_counts[f] ?? 0})` : ` (${d.labels.length})`}
              </button>
            ))}
          </div>
        }
      >
        Every case
      </SectionTitle>

      <Card pad={false}>
        <div className="table-scroll" style={{ maxHeight: 560 }}>
          <table className="table">
            <thead>
              <tr>
                <th>case</th>
                <th>label</th>
                <th>root cause</th>
                <th className="num">flip rate</th>
                <th className="num">code reached</th>
                <th className="num">shared state</th>
                <th className="num">smells</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => {
                const nav = navByCase.get(c.id);
                const flip = flipByCase.get(c.id) ?? 0;
                return (
                  <tr key={c.id}>
                    <td className="mono">{c.id.split("::").pop()}</td>
                    <td>
                      <Badge
                        tone={c.label === "flaky" ? "warn" : c.label === "real" ? "bad" : "good"}
                      >
                        {c.label}
                      </Badge>
                    </td>
                    <td className="dim">{CAUSE_LABEL[c.root_cause] ?? c.root_cause}</td>
                    <td className="num">
                      {flip > 0 ? <b>{pct(flip)}</b> : <span className="dim">0%</span>}
                    </td>
                    <td className="num">{fmt(Number(nav?.code_under_test_count ?? 0), 0)}</td>
                    <td className="num">{fmt(Number(nav?.shared_state_count ?? 0), 0)}</td>
                    <td className="num">{fmt(Number(nav?.smells_count ?? 0), 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
