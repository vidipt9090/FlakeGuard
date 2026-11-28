import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { Banner } from '../components/Banner';
import { CodePane } from '../components/CodePane';
import { Header } from '../components/Header';
import { RefText } from '../components/RefText';
import { RunNotice } from '../components/RunNotice';
import { SeverityChip, VerdictChip } from '../components/StatusChip';
import { usePolling } from '../hooks/usePolling';
import { useRun } from '../RunContext';
import type { AskAnswer, Finding } from '../types';

const GROUPS: { key: Finding['verdict']; title: string }[] = [
  { key: 'real', title: 'Real failures' },
  { key: 'flaky', title: 'Flaky' },
  { key: 'unknown', title: 'Needs more evidence' },
];

export default function Findings() {
  const { runId } = useRun();
  const rid = runId ?? 'none';
  const { data: findings } = usePolling(() => api.getFindings(rid), 4000, true, [rid]);
  const { data: scanRun } = usePolling(() => api.getRun(rid), 4000, true, [rid]);
  const [selId, setSelId] = useState<string | null>(null);
  const [question, setQuestion] = useState('Why is this test order-dependent?');
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);

  useEffect(() => {
    if (findings && !selId) setSelId(findings.find((f) => f.verdict === 'flaky')?.id ?? findings[0]?.id ?? null);
  }, [findings, selId]);

  const src = scanRun?.source;
  const sel = useMemo(() => findings?.find((f) => f.id === selId) ?? null, [findings, selId]);

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label); setNote(null); setLink(null);
    try {
      const r = (await fn()) as { prUrl?: string; issueUrl?: string } | undefined;
      const url = r?.prUrl ?? r?.issueUrl ?? null;
      setLink(url);
      setNote(url ? `${label}: opened.` : label === 'Re-verify' ? 'Re-verify: started. The result is added to Evidence when the runs finish.' : `${label}: started.`);
    } catch (e) { setNote(`${label} failed: ${e instanceof Error ? e.message : e}`); }
    setBusy(null);
  }

  return (
    <>
      <Header />
      <main className="main">
        <RunNotice runId={runId} />
        {findings && findings.length === 0 && scanRun?.status === 'complete' && (
          <Banner kind="no-findings"
            title={`No evidence of flakiness in ${scanRun.counters.runsDone} ${scanRun.counters.runsDone === 1 ? 'run' : 'runs'}`} />
        )}
        <div className="findings-grid">
          <aside aria-label="Findings list">
            {GROUPS.map((g) => {
              const items = (findings ?? []).filter((f) => f.verdict === g.key);
              if (items.length === 0) return null;
              return (
                <div key={g.key}>
                  <div className="eyebrow list-h">{g.title} · {items.length}</div>
                  {items.map((f) => (
                    <button key={f.id} type="button" className={`item ${f.id === selId ? 'sel' : ''}`} onClick={() => { setSelId(f.id); setAnswer(null); setNote(null); setLink(null); }}>
                      <SeverityChip severity={f.severity} fixReady={f.fix !== null} />
                      <div className="nm">{f.test}</div>
                      <div className="sm">{f.summaryLine}</div>
                    </button>
                  ))}
                </div>
              );
            })}
          </aside>

          {sel && (
            <div className="stack">
              <section className="card">
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
                  <h2 className="mono" style={{ fontSize: 22, margin: 0 }}>{sel.test}</h2>
                  <VerdictChip verdict={sel.verdict} subtype={sel.subtype} />
                  <span className="chip blue">Evidence: {sel.evidenceTier}</span>
                </div>
                <p className="mono footnote" style={{ marginTop: 4 }}><RefText text={`${sel.file}:${sel.line}`} source={src} /></p>
                <dl className="dl">
                  <dt>Why</dt><dd><RefText text={sel.why} source={src} /></dd>
                  <dt>Evidence</dt><dd><ul>{sel.evidence.map((e) => <li key={e}><RefText text={e} source={src} /></li>)}</ul></dd>
                  <dt>Where it lives</dt>
                  <dd>
                    <div className="lives">
                      {sel.lives.map((c, i) => (
                        <span key={i} style={{ display: 'contents' }}>
                          {i > 0 && <span className="sep">{c.tone === 'write' ? '←' : '›'}</span>}
                          <span className={`c ${c.tone}`}>{c.text}</span>
                        </span>
                      ))}
                    </div>
                    <p style={{ marginTop: 8 }}><Link to="/repo-map">Open in Repo map →</Link></p>
                  </dd>
                  <dt>Did</dt><dd><RefText text={sel.did} source={src} /></dd>
                  <dt>Limits</dt><dd><RefText text={sel.limits} source={src} /></dd>
                </dl>
              </section>

              {sel.writer && sel.reader && (
                <div className="code2"><CodePane snippet={sel.writer} /><CodePane snippet={sel.reader} /></div>
              )}

              {sel.repro && (
                <section className="card">
                  <h2 style={{ fontSize: 16 }}>Reproduce it on your machine</h2>
                  <p className="lead">Run the two tests in this order. Failing means the order dependence is real.</p>
                  <div className="cmd">
                    <code>{sel.repro}</code>
                    <button type="button" className="btn" onClick={() => navigator.clipboard?.writeText(sel.repro!)}>Copy command</button>
                  </div>
                </section>
              )}

              <section className="card">
                <h2 style={{ fontSize: 16 }}>What do you want to do?</h2>
                <div className="btns">
                  <button type="button" className="btn primary" disabled={!sel.fix || !!busy} onClick={() => run('Propose fix PR', () => api.proposeFix(sel.id))}>Propose fix PR</button>
                  <button type="button" className="btn" disabled={!!busy} onClick={() => run('Re-verify', () => api.reverify(sel.id, 5))}>Re-verify, 5 runs</button>
                  <button type="button" className="btn" disabled={!!busy} onClick={() => sel.quarantine.allowed ? run('Quarantine', () => api.quarantine(sel.id)) : setNote('refused')}>Quarantine this test</button>
                </div>
                <p className="footnote">Quarantine needs write access to the repo, opens a tracking issue, and is refused for real failures. The fix PR is opened on the fork and a person merges it.</p>
                {note === 'refused' && <Banner kind="quarantine-refused" detail={sel.quarantine.reason ?? undefined} />}
                {note && note !== 'refused' && (
                  <p role="status" style={{ marginTop: 8 }}>
                    {note}{link && <> <a href={link} target="_blank" rel="noopener noreferrer">{link}</a></>}
                  </p>
                )}
              </section>

              {sel.fix && (
                <section className="card">
                  <h2 style={{ fontSize: 16 }}>Fix preview</h2>
                  <p className="lead">{sel.fix.summary}</p>
                  <p className="mono footnote" style={{ margin: '10px 0 4px' }}>{sel.fix.file}</p>
                  <div className="diff">{sel.fix.diff.join('\n')}</div>
                  <p style={{ marginTop: 10 }}><b>Checked before opening:</b> {sel.fix.checked}</p>
                  <p><b>Does not prove:</b> {sel.fix.doesNotProve}</p>
                </section>
              )}

              <section className="card">
                <h2 style={{ fontSize: 16 }}>Ask about this finding</h2>
                <form className="form" style={{ marginTop: 10 }} onSubmit={async (e) => { e.preventDefault(); setAnswer(await api.ask(sel.id, question)); }}>
                  <div className="field" style={{ flex: 1 }}>
                    <label htmlFor="q">Your question</label>
                    <input id="q" className="input" value={question} onChange={(e) => setQuestion(e.target.value)} />
                  </div>
                  <button type="submit" className="btn primary">Ask</button>
                </form>
                {answer && (answer.chunks === 0
                  ? <div style={{ marginTop: 14 }}><Banner kind="ask-nothing" /></div>
                  : (
                    <div className="answer">
                      <p>{answer.text}</p>
                      <p style={{ marginTop: 8 }}>{answer.citations.map((c) => <code key={c.label} style={{ marginRight: 8 }}>{c.label}</code>)}</p>
                      <p className="footnote" style={{ marginTop: 6 }}>Answered from {answer.chunks} retrieved code chunks. If nothing relevant is found, the answer says so.</p>
                    </div>
                  ))}
              </section>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
