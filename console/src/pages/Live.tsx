import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { Banner } from '../components/Banner';
import { Header } from '../components/Header';
import { DotMatrix, PipelineList } from '../components/Pipeline';
import { usePolling } from '../hooks/usePolling';
import { useRun } from '../RunContext';
import type { StartRunRequest } from '../types';

export default function Live() {
  const { runId, setRunId } = useRun();
  const [target, setTarget] = useState('demo/inventory#7');
  const [source, setSource] = useState<StartRunRequest['source']>('pull-request');
  const [runs, setRuns] = useState(10);
  const [docker, setDocker] = useState(true);
  const [startError, setStartError] = useState<string | null>(null);

  const { data: run, error } = usePolling(() => api.getRun(runId ?? 'none'), 2000, true, [runId]);
  const { data: health } = usePolling(() => api.health(), 15000, true, []);

  async function start() {
    setStartError(null);
    try {
      const r = await api.startRun({ target, source, runs, docker });
      setRunId(r.id);
    } catch (e) {
      setStartError(e instanceof Error ? e.message : String(e));
    }
  }

  const pr = run?.pr;
  return (
    <>
      <Header right={run?.mode === 'actions' ? <span className="pill blue">GitHub Actions connected</span> : null} />
      <main className="main">
        <section className="card form" aria-label="Scan target">
          <div className="field" style={{ flex: '1 1 320px' }}>
            <label htmlFor="repo">Repository or pull request</label>
            <input id="repo" className="input" value={target} onChange={(e) => setTarget(e.target.value)} />
          </div>
          <div className="field" style={{ flex: '0 1 200px' }}>
            <label htmlFor="src">Source</label>
            <select id="src" className="input" value={source} onChange={(e) => setSource(e.target.value as StartRunRequest['source'])}>
              <option value="pull-request">Pull request</option>
              <option value="repo">Paste a repo</option>
              <option value="sample">Sample repo</option>
            </select>
          </div>
          <div className="field" style={{ flex: '0 1 110px' }}>
            <label htmlFor="runs">Shuffled runs</label>
            <input id="runs" type="number" min={3} max={30} className="input" value={runs} onChange={(e) => setRuns(Number(e.target.value))} />
          </div>
          <label className="check">
            <input type="checkbox" checked={docker} onChange={(e) => setDocker(e.target.checked)} /> Isolate in Docker
            <span className="footnote" style={{ fontWeight: 400 }}>(runs on this machine)</span>
          </label>
          <button type="button" className="btn primary" onClick={start}>Run scan</button>
        </section>

        <p className="footnote" style={{ marginTop: -8 }}>
          Repo has no tests? <Link to="/no-tests?plan=latest">See how FlakeGuard handles it</Link> ·{' '}
          <Link to="/states">Screen states</Link> · <Link to="/bot-text">Text the bot posts on GitHub</Link>
          {health?.recorded && (
            <> · <button type="button" className="linklike" onClick={() => setRunId(health.recorded)}>Replay the recorded run</button></>
          )}
        </p>

        {startError && <Banner kind="scan-incomplete" detail={startError} />}
        {error && !run && <Banner kind="actions-unavailable" detail={`The console cannot reach its backend: ${error}`} />}
        {run?.notice && run.notice.kind !== 'recorded-run' && <Banner kind={run.notice.kind} detail={run.notice.detail} />}
        {run?.notice?.kind === 'recorded-run' && <Banner kind="recorded-run" />}

        {pr && (
          <section className="card tight" aria-label="Pull request status" style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
            <b>PR #{pr.number} · {pr.title}</b>
            <span className="chip blue">{pr.state === 'open' ? 'Open' : pr.state}</span>
            <span className="chip flaky">FlakeGuard check: {pr.checkState}</span>
            <span className="chip">Post-merge check: {pr.postMergeState}</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 16 }}>
              {pr.prUrl && <a href={pr.prUrl} target="_blank" rel="noreferrer">Open PR on GitHub ↗</a>}
              {pr.runUrl && <a href={pr.runUrl} target="_blank" rel="noreferrer">Open Actions run ↗</a>}
            </span>
          </section>
        )}

        {run && run.stages.length > 0 && (
          <div className="split">
            <section className="card" aria-label="Pipeline">
              <h2>Pipeline</h2>
              <p className="lead" style={{ marginBottom: 8 }}>Each stage updates as the run on GitHub progresses.</p>
              <PipelineList stages={run.stages} />
            </section>
            <div className="stack">
              <section className="card" aria-label="Right now">
                <h2>Right now</h2>
                {run.current && (
                  <>
                    <p className="footnote" style={{ marginTop: 10 }}>Test under perturbation</p>
                    <p className="mono">{run.current.test}</p>
                    <p className="footnote" style={{ marginTop: 10 }}>Condition</p>
                    <p style={{ fontWeight: 500 }}>{run.current.condition}</p>
                  </>
                )}
                <div className="stats">
                  <div className="stat"><div className="k">Runs done</div><div className="v">{run.counters.runsDone} / {run.counters.runsTotal}</div></div>
                  <div className="stat warn"><div className="k">Failures</div><div className="v">{run.counters.failures}</div></div>
                  <div className="stat"><div className="k">Tests flagged</div><div className="v">{run.counters.flagged}</div></div>
                </div>
              </section>
              <section className="card" aria-label="Outcome by condition">
                <h2>Outcome by condition</h2>
                <p className="footnote" style={{ marginBottom: 6 }}>one mark per run</p>
                <DotMatrix rows={run.matrix} />
              </section>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
