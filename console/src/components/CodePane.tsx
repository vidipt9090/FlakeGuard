import type { CodeSnippet } from '../types';

/** Annotated code. `hot` lines are tinted: red for the polluter pane, amber for the victim pane. */
export function CodePane({ snippet }: { snippet: CodeSnippet }) {
  const tone = snippet.role === 'the polluter' ? 'hot-write' : 'hot-read';
  return (
    <div className="pane">
      <div className="pane-h">{snippet.file} · {snippet.role}</div>
      {snippet.lines.map((l) => (
        <div key={l.n} className={`ln-wrap ${l.hot ? tone : ''}`}>
          <div className="ln"><span className="n">{l.n}</span><span className="t">{l.t}</span></div>
          {l.hot && l.note && <div className="ln-note">{l.note}</div>}
        </div>
      ))}
    </div>
  );
}
