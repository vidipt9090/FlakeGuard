import { Link } from 'react-router-dom';
import { IconShield } from '../components/Icons';

/** Reference page: the exact wording the bot posts on GitHub. Mirror this in the backend templates. */
export default function BotText() {
  return (
    <>
      <header className="header"><div className="header-in">
        <div className="brand"><IconShield /> FlakeGuard</div><span className="pill">Reference: text posted on GitHub</span>
        <div className="header-right"><Link to="/">Back to Live</Link></div>
      </div></header>
      <main className="main">
        <div>
          <h1>What the bot writes on GitHub</h1>
          <p className="lead">The console sits next to the real pull request in the demo. This is the wording the bot puts there, shown as plain text.</p>
        </div>
        <div className="row">
          <section className="card grow">
            <div className="eyebrow">Comment on the pull request</div>
            <h2 style={{ margin: '8px 0' }}>FlakeGuard · 1 flaky test found</h2>
            <table className="tbl">
              <thead><tr><th>Test</th><th>Verdict</th><th>Evidence</th></tr></thead>
              <tbody>
                <tr><td className="mono">test_report_total</td><td>Flaky, order-dependent</td><td>Failed 4 of 10 shuffled runs</td></tr>
                <tr><td className="mono">test_reserve_negative</td><td>Real failure</td><td>Failed 10 of 10 runs</td></tr>
              </tbody>
            </table>
            <p style={{ marginTop: 14 }}><b>test_report_total</b></p>
            <ul style={{ margin: '4px 0 12px', paddingLeft: 18 }}>
              <li><b>Why:</b> reads CACHE (test_report.py:41), which test_cache_warm sets and never clears (test_cache.py:23).</li>
              <li><b>Where:</b> tests/ › test_report.py › test_report_total › reads CACHE ← test_cache_warm</li>
              <li><b>Limits:</b> order-dependence is shown for these two tests. Other causes are not ruled out.</li>
            </ul>
            <p><b>Reply to this comment with</b></p>
            <pre className="mono" style={{ margin: '4px 0' }}>{'/flakeguard fix\n/flakeguard ask why is this order-dependent?\n/flakeguard quarantine test_report_total'}</pre>
            <p className="footnote">This comment is updated in place on every push.</p>
          </section>
          <section className="card grow">
            <div className="eyebrow">Fix PR description</div>
            <h2 style={{ margin: '8px 0' }}>Fix order dependence in test_report_total</h2>
            <p><b>What this changes</b><br />Adds a fixture in tests/conftest.py (4 lines) that clears CACHE after every test, so no test can leave state behind.</p>
            <p style={{ marginTop: 10 }}><b>How it was checked</b><br />20 shuffled runs, 0 failures. The two-test repro that failed before now passes.</p>
            <p style={{ marginTop: 10 }}><b>What it does not prove</b><br />That the code is correct in orders that were not run.</p>
            <p style={{ marginTop: 10 }}><b>How to undo</b><br />Revert this pull request. Nothing else is touched.</p>
            <p style={{ marginTop: 10 }}><b>Who merges</b><br />A person. FlakeGuard opened this on the fork and will not merge it.</p>
          </section>
        </div>
        <div className="row">
          <section className="card grow">
            <div className="eyebrow">After the merge</div>
            <h2 style={{ margin: '8px 0' }}>FlakeGuard post-merge check</h2>
            <p>No evidence of flakiness in 10 runs after this change.</p>
            <p className="lead" style={{ marginTop: 8 }}>This is not proof it is fixed. If the scan does not finish, this comment says so and shows no verdict.</p>
          </section>
          <section className="card grow">
            <div className="eyebrow">When quarantine is refused</div>
            <h2 style={{ margin: '8px 0' }}>Not quarantined: test_reserve_negative</h2>
            <p>This test failed in 10 of 10 runs, so it looks like a real bug, not a flaky test. Quarantining it would hide the bug.</p>
            <p className="lead" style={{ marginTop: 8 }}>Quarantine also needs write access to the repository. Requests from anyone without it are declined.</p>
          </section>
        </div>
      </main>
    </>
  );
}
