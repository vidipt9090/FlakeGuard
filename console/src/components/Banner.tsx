import { STATE_COPY } from '../copy';
import type { ScreenState } from '../types';
import { IconInfo, IconOk, IconReal, IconWarn } from './Icons';

const ICON = { neutral: IconInfo, amber: IconWarn, red: IconReal, blue: IconOk } as const;

/** One banner for every unusual state. Wording comes from copy.ts, never from the caller. */
export function Banner({ kind, onAction, detail }: { kind: ScreenState; onAction?: () => void; detail?: string }) {
  const c = STATE_COPY[kind];
  const Icon = ICON[c.tone];
  return (
    <div className="banner-wrap" role={c.tone === 'red' ? 'alert' : 'status'}>
      <div className={`banner ${c.tone}`}>
        <div className="t"><Icon /> {c.title}</div>
        <div className="x">{detail ?? c.text}</div>
      </div>
      {c.action && onAction && <button type="button" className="btn" onClick={onAction}>{c.action}</button>}
    </div>
  );
}
