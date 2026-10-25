import { useMemo } from "react";
import { api, useAsync } from "./api";
import type { MetricRow } from "./types";
import { Badge, Card, ErrorBox, Empty, Meter, SectionTitle, Spinner, Stat, fmt, pct, rate } from "./ui";
import "./ResultsView.css";

/* Detection results — and the number the F1 chart hides.
 *
 * The best prompt reaches recall 1.0 by calling almost everything flaky, and
 * the benchmark's real bugs are part of "everything". Showing F1 without the
 * false-quarantine rate beside it is showing half the result, so the caveat
 * is part of the page rather than a footnote.
 */

const TARGET_F1 = 0.7;

function num(row: MetricRow, key: string): number {
  const v = row[key];
  return typeof v === "number" ? v : Number(v ?? 0);
}

export function ResultsView() {
  const { data, error, loading } = useAsync(() => api.results(), []);

  const methods = useMemo(() => {
    if (!data) return [];
    const out: { name: string; kind: "baseline" | "llm"; row: MetricRow }[] = [];
    for (const row of data.baselines) {
      out.push({ name: `rerun baseline (N=${row.N})`, kind: "baseline", row });
    }
    for (const row of data.llm) {
      out.push({ name: `prompt ${row.prompt_version}`, kind: "llm", row });
    }
    return out;
  }, [data]);

  if (loading) return <Spinner label="Loading results…" />;
  if (error) return <ErrorBox message={error.message} hint={error.hint} />;
  if (!data) return <Empty title="No results" />;

  const bestLlm = data.llm.reduce<MetricRow | null>(
    (best, row) => (!best || num(row, "f1") > num(best, "f1") ? row : best),
    null,
  );
  const bestBaseline = data.baselines.reduce<MetricRow | null>(
    (best, row) => (!best || num(row, "f1") > num(best, "f1") ? row : best),
    null,
  );
  const worstFq = data.llm.reduce((m, r) => Math.max(m, num(r, "false_quarantine_rate")), 0);
  const realCount = data.labels.filter((l) => l.label === "real").length;
  const maxF1 = Math.max(TARGET_F1, ...methods.map((m) => num(m.row, "f1")));

  return (
    <div className="res-view">
      <SectionTitle hint="Precision, recall and F1 for calling a test flaky, with bootstrap confidence intervals, against the rerun baseline.">
        Detection results
      </SectionTitle>

      <div className="stat-row">
        <Stat
          value={rate(bestLlm ? num(bestLlm, "f1") : null)}
          label="best prompt F1"
          tone={bestLlm && num(bestLlm, "f1") >= TARGET_F1 ? "good" : "warn"}
          sub={bestLlm ? `${bestLlm.prompt_version} · target ${TARGET_F1}` : undefined}
        />
        <Stat
          value={rate(bestBaseline ? num(bestBaseline, "f1") : null)}
          label="baseline F1"
          tone="plain"
          sub="rerun"
        />
        <Stat
          value={rate(bestLlm ? num(bestLlm, "root_cause_acc") : null)}
          label="root-cause accuracy"
        />
        <Stat
          value={rate(worstFq, 2)}
          label="false quarantine"
          tone={worstFq > 0.1 ? "bad" : "good"}
          sub="read this one first"
        />
      </div>

      {worstFq > 0.1 ? (
        <div className="caveat">
          <div className="caveat-title">Read the false-quarantine number before the F1 number</div>
          <p>
            Recall of 1.0 is reached by calling almost everything flaky — and the
            benchmark's <b>{realCount} real failures</b> are part of "everything". The
            false-quarantine rate is <b>{rate(worstFq, 2)}</b>, meaning the prompt labels{" "}
            <b>every real bug in the set as flaky</b>. The rerun baseline's rate is{" "}
            <b>{rate(bestBaseline ? num(bestBaseline, "false_quarantine_rate") : 0, 2)}</b>.
          </p>
          <p>
            So F1 alone makes the LLM look strictly better than the baseline, and on the
            one error that costs more than a flake does — hiding a real bug behind a
            quarantine — it is <i>worse</i>. This is exactly why the frozen decision is
            that <b>v1 never quarantines on its own; a person approves every quarantine</b>.
            The quality gate reports it on every run and blocks delivery on it under{" "}
            <code>--strict</code>.
          </p>
        </div>
      ) : null}

      <Card>
        <SectionTitle hint={`The dashed line is the charter's target of F1 ${TARGET_F1}.`}>
          F1 by method
        </SectionTitle>
        <div className="f1-chart">
          {methods.map((m) => {
            const f1 = num(m.row, "f1");
            const lo = num(m.row, "f1_ci_lower");
            const hi = num(m.row, "f1_ci_upper");
            return (
              <div key={m.name} className="f1-row">
                <span className="f1-name">{m.name}</span>
                <div className="f1-track">
                  <div
                    className="f1-target"
                    style={{ left: `${(TARGET_F1 / maxF1) * 100}%` }}
                    title={`target ${TARGET_F1}`}
                  />
                  <div
                    className="f1-ci"
                    style={{
                      left: `${(lo / maxF1) * 100}%`,
                      width: `${((hi - lo) / maxF1) * 100}%`,
                    }}
                    title={`95% CI ${fmt(lo, 2)}–${fmt(hi, 2)}`}
                  />
                  <div
                    className={`f1-bar ${m.kind === "llm" ? "is-llm" : "is-base"}`}
                    style={{ width: `${(f1 / maxF1) * 100}%` }}
                  />
                </div>
                <span className="f1-value mono">{rate(f1)}</span>
              </div>
            );
          })}
        </div>
        <p className="chart-note">
          The lighter band behind each bar is its 95% bootstrap confidence interval. At
          n=31 those intervals overlap heavily, which is the honest reading: the ordering
          of the prompts is suggestive, not established.
        </p>
      </Card>

      <Card pad={false}>
        <div className="card-pad">
          <SectionTitle>Every method</SectionTitle>
        </div>
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>method</th>
                <th>model</th>
                <th className="num">precision</th>
                <th className="num">recall</th>
                <th className="num">F1 [95% CI]</th>
                <th className="num">root-cause</th>
                <th className="num">false quarantine</th>
              </tr>
            </thead>
            <tbody>
              {methods.map((m) => {
                const fq = num(m.row, "false_quarantine_rate");
                return (
                  <tr key={m.name}>
                    <td>
                      <b>{m.name}</b>
                    </td>
                    <td className="mono dim">{String(m.row.model ?? "rerun")}</td>
                    <td className="num">{rate(num(m.row, "precision"))}</td>
                    <td className="num">{rate(num(m.row, "recall"))}</td>
                    <td className="num">
                      <b>{rate(num(m.row, "f1"))}</b>{" "}
                      <span className="dim">
                        [{rate(num(m.row, "f1_ci_lower"), 2)}, {rate(num(m.row, "f1_ci_upper"), 2)}]
                      </span>
                    </td>
                    <td className="num">{rate(num(m.row, "root_cause_acc"))}</td>
                    <td className={`num ${fq > 0.1 ? "tone-bad" : ""}`}>
                      <b>{rate(fq)}</b>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <SectionTitle hint="Every verdict above was made from an evidence bundle, and the bundle's code context comes from the navigator. If it stops resolving test ids the bundle silently empties and these metrics keep reporting on nothing.">
        What the navigator contributed
      </SectionTitle>
      <div className="nav-contrib">
        {[
          { title: "Synthetic benchmark", s: data.nav_summary },
          { title: "cachetools (external, pinned)", s: data.external_summary },
        ].map(({ title, s }) =>
          s ? (
            <Card key={title}>
              <div className="contrib-head">
                <b>{title}</b>
                <Badge>
                  {s.repo}@{s.sha}
                </Badge>
              </div>
              <div className="contrib-rows">
                <ContribRow label="resolved" value={pct(s.resolution_rate)} v={s.resolution_rate} />
                <ContribRow label="jedi hit rate" value={pct(s.jedi_hit_rate)} v={s.jedi_hit_rate} />
                <ContribRow
                  label="trees reaching hop 2"
                  value={`${s.trees_with_depth_2plus} / ${s.cases}`}
                  v={s.cases ? s.trees_with_depth_2plus / s.cases : 0}
                />
                <div className="contrib-plain">
                  <span>mean nodes per tree</span>
                  <b>{fmt(s.mean_tree_nodes)}</b>
                </div>
                <div className="contrib-plain">
                  <span>median / max latency</span>
                  <b>
                    {fmt(s.median_ms, 0)} / {fmt(s.max_ms, 0)} ms
                  </b>
                </div>
              </div>
            </Card>
          ) : null,
        )}
      </div>

      {data.failures.length ? (
        <Card pad={false}>
          <div className="card-pad">
            <SectionTitle hint="Cases the LLM got wrong, by prompt version. The pattern across versions is what the next prompt has to fix.">
              Misclassifications
            </SectionTitle>
          </div>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>version</th>
                  <th>case</th>
                  <th>actual</th>
                  <th>predicted</th>
                </tr>
              </thead>
              <tbody>
                {data.failures.map((f, i) => (
                  <tr key={i}>
                    <td>
                      <Badge>{String(f.prompt_version)}</Badge>
                    </td>
                    <td className="mono">{String(f.case_id ?? "").split("::").pop()}</td>
                    <td>
                      {String(f.actual_label)} / <span className="dim">{String(f.actual_root_cause)}</span>
                    </td>
                    <td className="tone-bad">
                      {String(f.pred_label)} / <span className="dim">{String(f.pred_root_cause)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function ContribRow({ label, value, v }: { label: string; value: string; v: number }) {
  return (
    <div className="contrib-row">
      <span>{label}</span>
      <Meter value={v} tone={v >= 0.9 ? "good" : v >= 0.7 ? "accent" : "warn"} />
      <b>{value}</b>
    </div>
  );
}
