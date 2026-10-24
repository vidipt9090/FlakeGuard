import { useEffect, useState } from "react";
import { NavigatorView } from "./NavigatorView";
import { PipelineView } from "./PipelineView";
import { ResultsView } from "./ResultsView";
import { DatasetView } from "./DatasetView";
import "./App.css";

type View = "navigator" | "results" | "dataset" | "pipeline";

const VIEWS: { id: View; label: string; blurb: string; icon: JSX.Element }[] = [
  {
    id: "navigator",
    label: "Knowledge tree",
    blurb: "watch the AST walk and jedi build it",
    icon: (
      <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden>
        <circle cx="3" cy="8" r="2" fill="currentColor" />
        <circle cx="12.5" cy="3.5" r="1.8" fill="currentColor" opacity="0.75" />
        <circle cx="12.5" cy="8" r="1.8" fill="currentColor" opacity="0.75" />
        <circle cx="12.5" cy="12.5" r="1.8" fill="currentColor" opacity="0.75" />
        <path
          d="M5 8 H8 M8 3.5 V12.5 M8 3.5 H10.7 M8 8 H10.7 M8 12.5 H10.7"
          stroke="currentColor"
          strokeWidth="1.1"
          fill="none"
        />
      </svg>
    ),
  },
  {
    id: "results",
    label: "Results",
    blurb: "detection scores and the caveat",
    icon: (
      <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden>
        <rect x="1.5" y="9" width="3" height="5.5" rx="1" fill="currentColor" opacity="0.6" />
        <rect x="6.5" y="5" width="3" height="9.5" rx="1" fill="currentColor" opacity="0.8" />
        <rect x="11.5" y="2" width="3" height="12.5" rx="1" fill="currentColor" />
      </svg>
    ),
  },
  {
    id: "dataset",
    label: "Benchmark",
    blurb: "31 planted cases and their flip rates",
    icon: (
      <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden>
        <ellipse cx="8" cy="3.6" rx="6" ry="2.3" fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d="M2 3.6 V12.4 C2 13.7 4.7 14.7 8 14.7 S14 13.7 14 12.4 V3.6"
              fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d="M2 8 C2 9.3 4.7 10.3 8 10.3 S14 9.3 14 8"
              fill="none" stroke="currentColor" strokeWidth="1.3" opacity="0.6" />
      </svg>
    ),
  },
  {
    id: "pipeline",
    label: "CI/CD",
    blurb: "the gate between testing and delivery",
    icon: (
      <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden>
        <circle cx="3" cy="3.5" r="1.9" fill="currentColor" opacity="0.7" />
        <circle cx="3" cy="12.5" r="1.9" fill="currentColor" opacity="0.7" />
        <circle cx="8" cy="8" r="2.1" fill="currentColor" />
        <circle cx="13" cy="8" r="1.9" fill="currentColor" opacity="0.7" />
        <path d="M4.6 4.4 L6.4 6.8 M4.6 11.6 L6.4 9.2 M10.1 8 H11.1"
              stroke="currentColor" strokeWidth="1.2" fill="none" />
      </svg>
    ),
  },
];

export default function App() {
  const [view, setView] = useState<View>("navigator");
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    try {
      return (localStorage.getItem("fg-theme") as "dark" | "light") ?? "dark";
    } catch {
      return "dark";
    }
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("fg-theme", theme);
    } catch {
      /* private mode: the theme just will not persist */
    }
  }, [theme]);

  const active = VIEWS.find((v) => v.id === view)!;

  return (
    <div className="app">
      <aside className="rail">
        <div className="brand">
          <div className="brand-mark" aria-hidden>
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path
                d="M12 2 L21 5.6 V11.4 C21 16.6 17.2 20.9 12 22 C6.8 20.9 3 16.6 3 11.4 V5.6 Z"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinejoin="round"
              />
              <path d="M8.3 11.9 L10.9 14.5 L15.9 9.3" fill="none" stroke="currentColor"
                    strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="brand-text">
            <b>FlakeGuard</b>
            <span>flaky-test triage</span>
          </div>
        </div>

        <nav className="rail-nav">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              className={`rail-item ${view === v.id ? "is-active" : ""}`}
              onClick={() => setView(v.id)}
              type="button"
            >
              <span className="rail-icon">{v.icon}</span>
              <span className="rail-text">
                <b>{v.label}</b>
                <small>{v.blurb}</small>
              </span>
            </button>
          ))}
        </nav>

        <div className="rail-foot">
          <button
            className="theme-toggle"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            title="Switch theme"
            type="button"
          >
            {theme === "dark" ? "☾" : "☀"}
            <span>{theme === "dark" ? "Dark" : "Light"}</span>
          </button>
          <div className="rail-pipeline">
            collect → parse → <b>navigate</b> → evidence → LLM → verdict
          </div>
          <div className="rail-team">
            <span>A — data &amp; CI</span>
            <span>B — navigation &amp; retrieval</span>
            <span>C — LLM &amp; evaluation</span>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{active.label}</h1>
            <p>{active.blurb}</p>
          </div>
        </header>
        <div className="content">
          {view === "navigator" ? <NavigatorView /> : null}
          {view === "results" ? <ResultsView /> : null}
          {view === "dataset" ? <DatasetView /> : null}
          {view === "pipeline" ? <PipelineView /> : null}
        </div>
      </main>
    </div>
  );
}
