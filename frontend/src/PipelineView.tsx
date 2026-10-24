import { useState } from "react";
import { api, useAsync } from "./api";
import type { GateCheck } from "./types";
import { Badge, Card, ErrorBox, Empty, SectionTitle, Spinner, Stat } from "./ui";
import "./PipelineView.css";

/* The pipeline, and in particular where testing stops and delivery starts.
 *
 * The stage list is checked against .github/workflows/cicd.yml by a Python
 * test, so this page cannot drift into describing a pipeline the repository
 * does not have.
 */

type Side = "ci" | "gate" | "cd";

const STAGES: { job: string; title: string; detail: string; side: Side }[] = [
  { job: "static", title: "lint", detail: "ruff over the whole tree", side: "ci" },
  { job: "build", title: "build", detail: "sdist + wheel, metadata checked, uploaded once", side: "ci" },
  { job: "ui", title: "web ui", detail: "React dashboard: typecheck + build, carried forward", side: "ci" },
  { job: "test", title: "unit tests", detail: "pytest with coverage; records the jedi version", side: "ci" },
  { job: "navigate", title: "navigate (synthetic)", detail: "neutralisation check, nav eval, knowledge trees", side: "ci" },
  { job: "navigate-external", title: "navigate (cachetools)", detail: "a repo that is not ours, pinned by SHA", side: "ci" },
  { job: "gate", title: "quality gate", detail: "measured thresholds; blocks everything downstream", side: "gate" },
  { job: "report", title: "report", detail: "static HTML built from the gated bundle", side: "cd" },
  { job: "deploy", title: "deploy", detail: "publishes it to Pages (develop / main)", side: "cd" },
  { job: "release", title: "release", detail: "tagged release carrying the build and its evidence", side: "cd" },
];

const SIDE_LABEL: Record<Side, string> = {
  ci: "Continuous integration — does it work?",
  gate: "The boundary — is it good enough to ship?",
  cd: "Continuous delivery — ship it",
};

const TRANSITION = [
  {
    aspect: "Shape",
    before: "one job doing everything in sequence",
    after: "nine jobs in a dependency graph, fanning out and back in",
    why: "a lint failure should not cost you the navigator run",
  },
  {
    aspect: "Artifacts",
    before: "none — every step rebuilt from source",
    after: "dist, test reports, both result sets, the gated bundle, the report",
    why: "delivery means shipping the thing you tested, not a later rebuild of the same source",
  },
  {
    aspect: "Gate",
    before: "pass/fail of pytest only",
    after: "measured thresholds on navigator reach, jedi hit rate, prompt F1 against the baseline",
    why: "tests passing does not mean the result is still good — a navigator that resolves nothing passes every unit test",
  },
  {
    aspect: "Generalisation",
    before: "scored on our own fixtures",
    after: "a pinned external repository scored on a hand-labelled gold set, as a pipeline stage",
    why: "a navigator tuned and scored on one library measures fit, not skill",
  },
  {
    aspect: "Output",
    before: "a green tick",
    after: "a deployed HTML report and a tagged release carrying its evidence",
    why: "someone outside the team can read the result without running anything",
  },
  {
    aspect: "Reproducibility",
    before: "implicit",
    after: "jedi version and full pip freeze recorded next to the numbers",
    why: "the navigator resolves against what is installed — the same test id returned 3 chunks on one interpreter and 1 on another",
  },
];

export function PipelineView() {
  const { data, error, loading } = useAsync(() => api.pipeline(), []);
  const [openWorkflow, setOpenWorkflow] = useState<string | null>(null);

  if (loading) return <Spinner label="Loading pipeline status…" />;
  if (error) return <ErrorBox message={error.message} hint={error.hint} />;

  const status = data?.status ?? null;
  const promote = status?.promote ?? null;

  return (
    <div className="pipe-view">
      <SectionTitle
        hint={
          <>
            Running <code>pytest</code> on every push is continuous integration: it
            answers <i>did it break?</i> A delivery pipeline answers a second question —{" "}
            <i>is this build good enough to ship?</i> — and acts on the answer. The stage
            that does that is the <b>quality gate</b>. Everything to its left is testing;
            everything to its right only runs through it.
          </>
        }
      >
        From a test suite to a delivery pipeline
      </SectionTitle>

      {status ? (
        <div className={`verdict verdict-${promote ? "promote" : "blocked"}`}>
          <div className="verdict-main">
            <span className="verdict-word">{promote ? "PROMOTE" : "BLOCKED"}</span>
            <span className="verdict-counts">
              {status.counts.pass} passed · {status.counts.fail} failed ·{" "}
              {status.counts.warn} warned · {status.counts.skip} skipped
            </span>
          </div>
          <div className="verdict-meta mono">
            commit {status.commit} · {status.branch || "local"} · {status.workflow} ·
            python {status.python} · {status.generated_at}
            {status.strict ? " · strict" : ""}
          </div>
        </div>
      ) : (
        <Empty
          title="No gate verdict yet"
          body={
            <>
              Run <code>python scripts/quality_gate.py</code>. The pipeline writes this in
              its <code>gate</code> stage.
            </>
          }
        />
      )}

      {(["ci", "gate", "cd"] as Side[]).map((side) => (
        <div key={side} className="pipe-band">
          <h3 className="pipe-band-title">{SIDE_LABEL[side]}</h3>
          <div className={`pipe-stages pipe-stages-${side}`}>
            {STAGES.filter((s) => s.side === side).map((s) => {
              const tone =
                side === "gate"
                  ? promote
                    ? "good"
                    : "bad"
                  : side === "cd"
                    ? promote
                      ? "good"
                      : "mute"
                    : "accent";
              return (
                <div key={s.job} className={`pipe-stage tone-edge-${tone}`}>
                  <div className="pipe-stage-title">{s.title}</div>
                  <div className="pipe-stage-detail">{s.detail}</div>
                  <div className={`pipe-stage-badge tone-${tone === "mute" ? "plain" : tone}`}>
                    {side === "gate"
                      ? promote
                        ? "PROMOTE"
                        : "BLOCKED"
                      : side === "cd"
                        ? promote
                          ? "reachable"
                          : "blocked"
                        : s.job}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {status ? (
        <>
          <SectionTitle hint="Each check names the artifact it reads, the threshold, and why the threshold is where it is. Thresholds sit below what we measure, so the gate catches a regression rather than fencing in today's result.">
            Every check
          </SectionTitle>
          <div className="checks">
            {status.checks.map((c) => (
              <CheckRow key={c.name} check={c} />
            ))}
          </div>
        </>
      ) : null}

      <SectionTitle hint="What changed, and why each change is what makes this delivery rather than integration.">
        The transition
      </SectionTitle>
      <div className="transition">
        {TRANSITION.map((t) => (
          <Card key={t.aspect} className="transition-card">
            <div className="transition-aspect">{t.aspect}</div>
            <div className="transition-cols">
              <div>
                <span className="transition-when">Before</span>
                <p>{t.before}</p>
              </div>
              <div>
                <span className="transition-when transition-now">Now</span>
                <p className="transition-after">{t.after}</p>
              </div>
            </div>
            <div className="transition-why">
              <b>Why:</b> {t.why}
            </div>
          </Card>
        ))}
      </div>

      {data?.workflows.length ? (
        <>
          <SectionTitle hint="Read from .github/workflows/ on disk, so this page cannot claim a pipeline the repository does not have.">
            The workflows themselves
          </SectionTitle>
          <div className="workflows">
            {data.workflows.map((w) => (
              <Card key={w.name} pad={false}>
                <button
                  className="wf-head"
                  onClick={() => setOpenWorkflow(openWorkflow === w.name ? null : w.name)}
                  type="button"
                >
                  <span className="wf-name mono">{w.name}</span>
                  <span className="wf-lines">{w.lines} lines</span>
                  <span className="wf-chevron">{openWorkflow === w.name ? "−" : "+"}</span>
                </button>
                {openWorkflow === w.name ? <pre className="wf-body">{w.text}</pre> : null}
              </Card>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

function CheckRow({ check }: { check: GateCheck }) {
  const tone =
    check.status === "pass"
      ? "good"
      : check.status === "fail"
        ? "bad"
        : check.status === "warn"
          ? "warn"
          : "plain";
  const mark = { pass: "✓", fail: "✕", warn: "!", skip: "–" }[check.status];
  return (
    <div className={`check check-${check.status}`}>
      <div className={`check-mark tone-${tone}`}>{mark}</div>
      <div className="check-body">
        <div className="check-head">
          <span className="check-name">{check.name}</span>
          <Badge>{check.stage}</Badge>
          <span className="check-source mono">{check.source}</span>
        </div>
        <div className="check-detail mono">{check.detail}</div>
        <div className="check-why">{check.why}</div>
      </div>
    </div>
  );
}

/** Small summary strip reused on the overview. */
export function GateStrip() {
  const { data } = useAsync(() => api.pipeline(), []);
  const status = data?.status;
  if (!status) return null;
  return (
    <div className="stat-row">
      <Stat
        value={status.promote ? "PROMOTE" : "BLOCKED"}
        label="delivery status"
        tone={status.promote ? "good" : "bad"}
      />
      <Stat value={status.counts.pass} label="checks passed" tone="good" />
      <Stat value={status.counts.warn} label="warned" tone="warn" />
      <Stat value={status.counts.fail} label="failed" tone={status.counts.fail ? "bad" : "plain"} />
    </div>
  );
}
