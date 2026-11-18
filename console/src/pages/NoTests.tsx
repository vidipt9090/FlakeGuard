import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { CodePane } from '../components/CodePane';
import { Header } from '../components/Header';
import { IconOk } from '../components/Icons';
import { usePolling } from '../hooks/usePolling';
import { useRun } from '../RunContext';

export default function NoTests() {
  const { runId } = useRun();
  const rid = runId ?? 'none';
  const { data } = usePolling(() => api.getNoTests(rid), 3000, true, [rid]);
  return (
    <>
      <Header right={data ? <span className="pill mono">{data.repo}</span> : null} />
      <main className="main">
        <div>
          <p className="footnote"><Link to="/">Live</Link> › Repo with no tests</p>
          <h1>This repository has no tests</h1>
          <p className="lead">FlakeGuard looks for code that tends to behave differently from run to run, writes a small test for each spot, and keeps only the tests that give the same result every time.</p>
        </div>
        {data && (
          <>
            <section className="card tight steps" aria-label="Progress">
              {data.steps.map((s, i) => (
                <div className="step" key={s.name}><span className="num">{i + 1}</span><b>{s.name}</b> <span className="footnote">· {s.state === 'done' ? 'done' : s.state === 'running' ? 'running' : 'waiting'}</span></div>
              ))}
            </section>
            <section className="card">
              <h2>Risky spots found</h2>
              <p className="lead">Places in the code where the result can change from one run to the next.</p>
              <table className="tbl">
                <thead><tr><th>Where</th><th>What the code does</th><th>Why it is risky</th><th>Test</th></tr></thead>
                <tbody>{data.spots.map((s) => (
                  <tr key={s.where}><td className="mono">{s.where}</td><td>{s.what}</td><td>{s.why}</td><td className="mono">{s.test ?? '—'}</td></tr>
                ))}</tbody>
              </table>
            </section>
            {data.example && (
              <section className="card">
                <h2>How a test gets written</h2>
                <p className="lead" style={{ marginBottom: 12 }}>The spot that depends on the clock, and the test written for it.</p>
                <div className="code2"><CodePane snippet={data.example.risky} /><CodePane snippet={data.example.test} /></div>
                <div className="checks">
                  {data.checks.map((c) => (
                    <span key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 8, color: c.ok ? 'var(--blue-ink)' : 'var(--muted)' }}><IconOk /> {c.label}</span>
                  ))}
                </div>
                <div className="banner neutral">These tests record what the code does today. They do not prove it is correct.</div>
                <div className="btns" style={{ marginTop: 14 }}>
                  <button type="button" className="btn primary">Open PR on your fork</button>
                  <button type="button" className="btn">Drop this test</button>
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </>
  );
}
