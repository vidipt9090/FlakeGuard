import type { CSSProperties, ReactNode } from "react";
import "./ui.css";

/* Small, shared pieces. Everything here is presentational — no data access,
   no business rules — so a view reads as layout rather than as markup. */

export function Card({
  children,
  pad = true,
  className = "",
  style,
}: {
  children: ReactNode;
  pad?: boolean;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div className={`card ${pad ? "card-pad" : ""} ${className}`} style={style}>
      {children}
    </div>
  );
}

export function SectionTitle({
  children,
  hint,
  right,
}: {
  children: ReactNode;
  hint?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        <h2>{children}</h2>
        {hint ? <p className="section-hint">{hint}</p> : null}
      </div>
      {right ? <div className="section-right">{right}</div> : null}
    </div>
  );
}

/** A headline number. The label sits under it, quieter, never shouting. */
export function Stat({
  value,
  label,
  tone = "accent",
  sub,
  title,
}: {
  value: ReactNode;
  label: string;
  tone?: "accent" | "ast" | "jedi" | "good" | "warn" | "bad" | "plain";
  sub?: ReactNode;
  title?: string;
}) {
  return (
    <div className="stat" title={title}>
      <div className={`stat-value tone-${tone}`}>{value}</div>
      <div className="stat-label">{label}</div>
      {sub ? <div className="stat-sub">{sub}</div> : null}
    </div>
  );
}

export function Badge({
  children,
  tone = "plain",
  dot = false,
}: {
  children: ReactNode;
  tone?: "accent" | "ast" | "jedi" | "good" | "warn" | "bad" | "plain";
  dot?: boolean;
}) {
  return (
    <span className={`badge badge-${tone}`}>
      {dot ? <i className="badge-dot" /> : null}
      {children}
    </span>
  );
}

/** A bar that reads as a proportion without needing an axis. */
export function Meter({
  value,
  max = 1,
  tone = "accent",
  label,
}: {
  value: number;
  max?: number;
  tone?: "accent" | "good" | "warn" | "bad" | "ast" | "jedi";
  label?: ReactNode;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(1, value / max)) * 100 : 0;
  return (
    <div className="meter-wrap">
      <div className="meter-track">
        <div className={`meter-fill tone-bg-${tone}`} style={{ width: `${pct}%` }} />
      </div>
      {label ? <span className="meter-label">{label}</span> : null}
    </div>
  );
}

export function Empty({ title, body }: { title: string; body?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {body ? <div className="empty-body">{body}</div> : null}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="spinner-wrap" role="status" aria-live="polite">
      <div className="spinner" />
      {label ? <span className="spinner-label">{label}</span> : null}
    </div>
  );
}

export function ErrorBox({
  message,
  hint,
  onRetry,
}: {
  message: string;
  hint?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="errorbox" role="alert">
      <div className="errorbox-title">{message}</div>
      {hint ? <code className="errorbox-hint">{hint}</code> : null}
      {onRetry ? (
        <button className="btn btn-sm" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "default",
  size = "md",
  disabled,
  title,
  active,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "ghost";
  size?: "sm" | "md";
  disabled?: boolean;
  title?: string;
  active?: boolean;
}) {
  return (
    <button
      className={`btn btn-${variant} btn-${size} ${active ? "is-active" : ""}`}
      onClick={onClick}
      disabled={disabled}
      title={title}
      type="button"
    >
      {children}
    </button>
  );
}

/** Segmented control. Used for view switches where tabs would be too heavy. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: ReactNode; title?: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          className={`segmented-item ${o.value === value ? "is-active" : ""}`}
          onClick={() => onChange(o.value)}
          title={o.title}
          type="button"
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

/** The legend for the one categorical split the whole app uses. */
export function ResolverLegend({ note }: { note?: ReactNode }) {
  return (
    <div className="legend">
      <span className="legend-item">
        <i className="legend-swatch" style={{ background: "var(--ast)" }} />
        found by the AST walk
      </span>
      <span className="legend-item">
        <i className="legend-swatch" style={{ background: "var(--jedi)" }} />
        resolved by jedi
      </span>
      {note ? <span className="legend-note">{note}</span> : null}
    </div>
  );
}

export const EDGE_HELP: Record<string, string> = {
  calls: "the test names it — jedi.goto resolved the name",
  infers: "operator use — jedi.infer gave the type whose method runs",
  fixture: "a pytest fixture the test requests, or an autouse one",
  "fixture-builds": "built by a fixture; the test only sees an untyped argument",
  overrides: "self.x resolved against the concrete class in the test id",
  expands: "reached from its parent's bases, decorators, defaults or body",
  touches: "module-level mutable state in a file this test reaches",
  smells: "a flakiness pattern matched in directly-exercised code",
  reaches: "reached by the navigator; the edge was not recorded",
  root: "the failing test the navigator was asked about",
};

export const PHASE_HELP: Record<string, string> = {
  locate: "test id → file, class, function (pure ast)",
  inherit: "the body is in a base class, not the class the id names",
  ast_walk: "walk the test body and collect every candidate name",
  jedi_goto: "name → definition",
  jedi_infer: "expression → the type whose operator actually runs",
  fixture: "test arguments → the conftest.py chain",
  concrete: "self.x → the override in the class the test id names",
  expand: "a definition's bases, decorators, defaults and callees",
  shared_state: "module-level mutable values in reachable files",
  smell: "flakiness pattern scan over directly-exercised code",
};

export const PHASE_ORDER = [
  "locate",
  "inherit",
  "ast_walk",
  "jedi_goto",
  "jedi_infer",
  "fixture",
  "concrete",
  "expand",
  "shared_state",
  "smell",
];

/** One step off the sequential ramp, by how far from the test a node sits. */
export function depthColor(depth: number, maxDepth: number): string {
  const ramp = ["--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5"];
  if (maxDepth <= 0) return `var(${ramp[ramp.length - 1]})`;
  const i = Math.round((depth / maxDepth) * (ramp.length - 1));
  return `var(${ramp[Math.max(0, Math.min(ramp.length - 1, i))]})`;
}

export function fmt(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

/** A rate or score always keeps its decimals: a false-quarantine rate of
 *  1.00 reads as a rate, while "1" reads as a count of one. */
export function rate(n: number | null | undefined, digits = 3): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function pct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${Math.round(n * 100)}%`;
}

export function ms(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(2)} s` : `${Math.round(n)} ms`;
}

export function shortId(testId: string): string {
  const [file, ...rest] = testId.split("::");
  return `${file.split("/").pop() ?? file}::${rest.join("::")}`;
}
