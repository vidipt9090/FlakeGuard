import { useState } from 'react';
import { api } from '../api/client';
import { Header } from '../components/Header';
import { usePolling } from '../hooks/usePolling';
import type { LabelType, Provenance, ResultsTable } from '../types';

function Table({ t }: { t: ResultsTable }) {
  return (
    <table className="tbl">
      <thead><tr>{t.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
      <tbody>
        {t.rows.length === 0 && <tr><td colSpan={t.columns.length} className="footnote">No run recorded yet. Cells show a dash until a run has been done.</td></tr>}
        {t.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c ?? '—'}</td>)}</tr>)}
      </tbody>
    </table>
  );
}

function Prov({ p }: { p: Provenance }) {
  const v = (x: string | number | null) => (x === null ? '[filled by the run]' : String(x));
  return (
    <div className="prov">
      <span><b>Dataset</b>{v(p.dataset)}</span><span><b>Label type</b>{p.labelType}</span>
      <span><b>N</b>{v(p.n)}</span><span><b>Command</b>{v(p.command)}</span>
      <span><b>Date</b>{v(p.date)}</span><span><b>Commit</b>{v(p.commit)}</span>
    </div>
  );
}

export default function Results() {
  const [label, setLabel] = useState<LabelType>('injected');
  const { data } = usePolling(() => api.getResults(label), 15000, true, [label]);
  return (
    <>
      <Header />
      <main className="main">
        <div>
          <h1>Results</h1>
          <p className="lead">These tables are static by design. They come from recorded runs made offline, and every table says where its numbers came from. Cells show a dash until that run has been done.</p>
        </div>
        <div className="seg" role="group" aria-label="Label type">
          <span style={{ fontWeight: 600, fontSize: 13 }}>Show flakes that are</span>
          {(['injected', 'natural', 'planted'] as LabelType[]).map((l) => (
            <button key={l} type="button" aria-pressed={label === l} onClick={() => setLabel(l)}>{l[0].toUpperCase() + l.slice(1)}</button>
          ))}
          <span className="footnote">Kept separate: planted flakes alone would be circular evidence.</span>
        </div>

        {data && (
          <>
            <section className="card">
              <h2>Does the knowledge tree help the diagnosis? <span className="footnote">RQ4</span></h2>
              <p className="lead">Same flaky tests, four ways of giving the model code context.</p>
              <Table t={data.ablation.table} /><Prov p={{ ...data.ablation.provenance, labelType: label }} />
            </section>
            <section className="card">
              <h2>Does perturbation find more flaky tests in the same time? <span className="footnote">RQ1</span></h2>
              <p className="lead">Compared with plain reruns, a coverage-based check, and a trained classifier.</p>
              <Table t={data.baselines.table} /><Prov p={{ ...data.baselines.provenance, labelType: label }} />
            </section>
            <div className="row">
              <section className="card grow">
                <h2>How many runs does a decision take? <span className="footnote">RQ2</span></h2>
                <p className="lead">Fixed number of reruns versus stopping early once the evidence is clear.</p>
                <div className="kpi2">
                  <div className="kpi"><div className="k">Fixed reruns</div><div className="v">{data.runsToDecision.fixed ?? '—'}</div></div>
                  <div className="kpi"><div className="k">Adaptive stopping</div><div className="v">{data.runsToDecision.adaptive ?? '—'}</div></div>
                </div>
              </section>
              <section className="card grow">
                <h2>Does triage avoid noise without hiding bugs? <span className="footnote">RQ3</span></h2>
                <p className="lead">Red PRs caused by flakes that were cleared, and real failures that were wrongly quarantined.</p>
                <div className="kpi2">
                  <div className="kpi"><div className="k">Flake-caused red PRs cleared</div><div className="v">{data.triage.redPrsCleared ?? '—'}</div></div>
                  <div className="kpi"><div className="k">Real failures quarantined</div><div className="v">{data.triage.realQuarantined ?? '—'}</div></div>
                </div>
              </section>
            </div>
          </>
        )}
      </main>
    </>
  );
}
