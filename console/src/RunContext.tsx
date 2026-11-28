import { createContext, useContext, useState, type ReactNode } from 'react';

interface Ctx {
  runId: string | null;
  setRunId: (id: string | null) => void;
}
const RunCtx = createContext<Ctx>({ runId: null, setRunId: () => {} });

/** Holds the id of the current run so every screen shows the same scan. */
export function RunProvider({ children }: { children: ReactNode }) {
  const [runId, setRaw] = useState<string | null>(() => sessionStorage.getItem('fg-run-id'));
  const setRunId = (id: string | null) => {
    if (id) sessionStorage.setItem('fg-run-id', id); else sessionStorage.removeItem('fg-run-id');
    setRaw(id);
  };
  return <RunCtx.Provider value={{ runId, setRunId }}>{children}</RunCtx.Provider>;
}
export const useRun = () => useContext(RunCtx);
