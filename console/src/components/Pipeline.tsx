import type { MatrixRow, Stage } from '../types';

export function PipelineList({ stages }: { stages: Stage[] }) {
  return (
    <div>
      {stages.map((s) => (
        <div className="stage" key={s.id}>
          <span className={`dot ${s.state}`} role="img" aria-label={s.state} />
          <div>
            <div><span className="name">{s.name}</span><span className="tool">{s.tool}</span></div>
            <div className="detail">{s.detail}</div>
          </div>
          <span className="time">{s.state === 'running' ? 'running' : s.state === 'pending' ? 'waiting' : s.time ?? ''}</span>
        </div>
      ))}
    </div>
  );
}

const CELL_LABEL = { pass: 'passed', fail: 'failed', none: 'not run yet' } as const;

/** One mark per run. Meaning is never colour only: filled = passed, crossed ring = failed, empty ring = not run. */
export function DotMatrix({ rows }: { rows: MatrixRow[] }) {
  return (
    <div>
      {rows.map((r) => (
        <div className="matrix-row" key={r.label} title={r.summary}>
          <span className="lab">{r.label}</span>
          <span className="cells" role="img" aria-label={`${r.label}: ${r.summary}`}>
            {r.cells.map((c, i) => (
              <span key={i} className={`cell ${c}`} title={`Run ${i + 1}: ${CELL_LABEL[c]}`}>
                {c === 'fail' && (
                  <svg width="12" height="12" viewBox="0 0 12 12" style={{ margin: '0' }} aria-hidden="true">
                    <path d="M3 3l6 6M9 3l-6 6" stroke="#C4501B" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                )}
              </span>
            ))}
          </span>
        </div>
      ))}
      <p className="footnote">Filled = passed · crossed ring = failed · empty ring = not run yet</p>
    </div>
  );
}
