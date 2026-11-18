import type { Severity, Verdict } from '../types';

export function VerdictChip({ verdict, subtype }: { verdict: Verdict; subtype?: string | null }) {
  const word = verdict === 'flaky' ? 'Flaky' : verdict === 'real' ? 'Real failure' : 'Unknown';
  return <span className={`chip ${verdict}`}>{subtype ? `${word} · ${subtype}` : word}</span>;
}

export function SeverityChip({ severity }: { severity: Severity }) {
  if (severity === 'blocking') return <span className="chip real">Blocking</span>;
  if (severity === 'suggestion') return <span className="chip flaky">Suggestion · fix ready</span>;
  return <span className="chip unknown">Unknown</span>;
}
