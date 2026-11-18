import { useEffect, useRef, useState } from 'react';

/** Calls `fn` now and then every `ms` while `enabled`. Keeps the last good value on error. */
export function usePolling<T>(fn: () => Promise<T>, ms: number, enabled: boolean, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const v = await fnRef.current();
        if (alive) {
          setData(v);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
      if (alive) timer = window.setTimeout(tick, ms);
    };
    tick();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ms, ...deps]);

  return { data, error };
}
