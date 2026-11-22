import type { SourceRef } from '../types';

const REF = /([\w./-]+\.py):(\d+)/g;

export const refUrl = (source: SourceRef, file: string, line: number) =>
  `https://github.com/${source.repo}/blob/${source.ref}/${file}#L${line}`;

/** Text in which every `path.py:line` becomes a link to that line at the scanned commit.
 *  With no known source (a local folder) the references stay plain text: nothing links to a guess. */
export function RefText({ text, source }: { text: string; source: SourceRef | null | undefined }) {
  if (!source) return <>{text}</>;
  const parts: (string | JSX.Element)[] = [];
  let last = 0;
  for (const m of text.matchAll(REF)) {
    const at = m.index ?? 0;
    parts.push(text.slice(last, at));
    parts.push(
      <a key={at} className="mono" href={refUrl(source, m[1], Number(m[2]))} target="_blank" rel="noopener noreferrer"
        aria-label={`${m[0]} on GitHub, opens in a new tab`}>{m[0]}</a>,
    );
    last = at + m[0].length;
  }
  parts.push(text.slice(last));
  return <>{parts}</>;
}
