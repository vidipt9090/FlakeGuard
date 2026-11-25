import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { CodePane } from '../components/CodePane';
import { Header } from '../components/Header';
import { IconOk } from '../components/Icons';
import { usePolling } from '../hooks/usePolling';
import { useRun } from '../RunContext';
import type { NoTestsPlan } from '../types';

export default function NoTests() {
  const { runId } = useRun();
  const [params] = useSearchParams();
  const rid = params.get('plan') ?? runId ?? 'none';
  const { data } = usePolling(() => api.getNoTests(rid), 3000, true, [rid]);
  const [changed, setChanged] = useState<NoTestsPlan | null>(null); // the plan returned by the last Drop
  const [error, setError] = useState<string | null>(null);
  const plan = changed && changed.repo === data?.repo ? changed : data;
  const shown = plan?.spots.find((s) => s.test)?.test ?? null; // the test the example pair belongs to

  const drop = async () => {
    if (!shown) return;
    setError(null);
    try { setChanged(await api.dropNoTest(rid, shown)); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <>
      <Header right={plan ? <span className="pill mono">{plan.repo}</span> : null} />
      <main className="main">
        <div>
          <p className="footnote"><Link to="/">Live</Link> › Repo with no tests</p>
          <h1>This repository has no tests</h1>
          <p className="lead">FlakeGuard looks for code that tends to behave differently from run to run, writes a small test for each spot, and keeps only the tests that give the same result every time.</p>
        </div>
        {plan && (
          <>
            <section className="card tight steps" aria-label="Progress">
              {plan.steps.map((s, i) => (
                <div className="step" key={s.name}><span className="num">{i + 1}</span><b>{s.name}</b> <span className="footnote">· {s.state === 'done' ? 'done' : s.state === 'running' ? 'running' : 'waiting'}</span></div>
              ))}
            </section>
            <section className="card">
              <h2>Risky spots found</h2>
              <p className="lead">Places in the code where the result can change from one run to the next.</p>
              <table className="tbl">
                <thead><tr><th>Where</th><th>What the code does</th><th>Why it is risky</th><th>Test</th></tr></thead>
                <tbody>
                  {plan.spots.length === 0 && <tr><td colSpan={4} className="footnote">Nothing was run for this repository yet.</td></tr>}
                  {plan.spots.map((s) => (
                    <tr key={s.where}><td className="mono">{s.where}</td><td>{s.what}</td><td>{s.why}</td><td className="mono">{s.test ?? '—'}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>
            {plan.example && (
              <section className="card">
                <h2>How a test gets written</h2>
                <p className="lead" style={{ marginBottom: 12 }}>The risky spot{shown ? <> for <span className="mono">{shown}</span></> : null}, and the test written for it.</p>
                <div className="code2"><CodePane snippet={plan.example.risky} /><CodePane snippet={plan.example.test} /></div>
                <div className="checks">
                  {plan.checks.map((c) => (
                    <span key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 8, color: c.ok ? 'var(--blue-ink)' : 'var(--muted)' }}><IconOk /> {c.label}</span>
                  ))}
                </div>
                <div className="banner neutral">These tests record what the code does today. They do not prove it is correct.</div>
                <div className="btns" style={{ marginTop: 14 }}>
                  <button type="button" className="btn primary" disabled aria-disabled="true" title="Not enabled in this build">Open PR on your fork</button>
                  <button type="button" className="btn" onClick={drop}>Drop this test</button>
                </div>
                <p className="footnote" role="note" style={{ marginTop: 8 }}>Open PR on your fork is not enabled in this build. Dropping a test only changes this screen's saved scan; no file in the repository and nothing on GitHub is touched.</p>
                {error && <p className="footnote" role="alert">{error}</p>}
              </section>
            )}
            {(plan.dropped ?? []).length > 0 && (
              <section className="card">
                <h2>Dropped tests</h2>
                <p className="lead">A test is dropped when it fails a check or when you drop it. It is listed here with the reason and never removed silently.</p>
                <table className="tbl">
                  <thead><tr><th>Test</th><th>Where</th><th>Why it was dropped</th></tr></thead>
                  <tbody>{(plan.dropped ?? []).map((d) => (
                    <tr key={d.test}><td className="mono">{d.test}</td><td className="mono">{d.where}</td><td>{d.reason}</td></tr>
                  ))}</tbody>
                </table>
              </section>
            )}
            {(plan.notes ?? []).length > 0 && (
              <section className="card" aria-label="How this scan was made">
                <h2>How this scan was made</h2>
                <ul className="notes">{(plan.notes ?? []).map((n) => <li key={n}>{n}</li>)}</ul>
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}
