import { Link } from 'react-router-dom';
import { Banner } from '../components/Banner';
import { IconShield } from '../components/Icons';
import { STATE_COPY } from '../copy';
import type { ScreenState } from '../types';

export default function States() {
  return (
    <>
      <header className="header"><div className="header-in">
        <div className="brand"><IconShield /> FlakeGuard</div><span className="pill">Reference: screen states</span>
        <div className="header-right"><Link to="/">Back to Live</Link></div>
      </div></header>
      <main className="main">
        <div>
          <h1>What the console says when things go differently</h1>
          <p className="lead">Each message says what happened, what was not done, and what to do next. It never guesses, and it never shows a result that was not produced.</p>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 20 }}>
          {(Object.keys(STATE_COPY) as ScreenState[]).map((k) => (
            <section className="card" key={k}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <span className="eyebrow">{k.replace(/-/g, ' ')}</span><span className="footnote">{STATE_COPY[k].where}</span>
              </div>
              <Banner kind={k} onAction={() => {}} />
            </section>
          ))}
        </div>
        <p className="footnote">Colour is never the only signal: each state has an icon and a plain heading.</p>
      </main>
    </>
  );
}
