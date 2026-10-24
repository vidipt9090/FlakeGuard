import type {
  Discovery,
  Explain,
  PipelineStatus,
  ResultsPayload,
  Suggestion,
  TreeSet,
} from "./types";
import { useCallback, useEffect, useState } from "react";

/** Everything the server might say went wrong, as one thing to render. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly hint?: string,
  ) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path);
  } catch {
    throw new ApiError(
      "Cannot reach the FlakeGuard server.",
      0,
      "Start it with: python -m flakeguard.app.api",
    );
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      body?.error ?? `${path} returned ${response.status}`,
      response.status,
      body?.hint ?? body?.fix,
    );
  }
  return body as T;
}

async function post<T>(path: string, payload: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError(
      "Cannot reach the FlakeGuard server.",
      0,
      "Start it with: python -m flakeguard.app.api",
    );
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      body?.error ?? `${path} returned ${response.status}`,
      response.status,
      body?.hint,
    );
  }
  return body as T;
}

export const api = {
  sets: () => get<{ sets: TreeSet[] }>("/api/sets"),
  tree: (set: string, testId: string) =>
    get<Explain>(`/api/sets/${encodeURIComponent(set)}/tree?test_id=${encodeURIComponent(testId)}`),
  navigate: (body: { repo: string; repo_name: string; test_id: string }) =>
    post<Explain>("/api/navigate", body),
  discover: (body: { repo: string; refresh?: boolean }) =>
    post<Discovery>("/api/discover", body),
  suggestions: () =>
    get<{ suggestions: Suggestion[]; cachetools_present: boolean }>("/api/suggestions"),
  pipeline: () =>
    get<{ status: PipelineStatus | null; workflows: { name: string; lines: number; text: string }[] }>(
      "/api/pipeline",
    ),
  results: () => get<ResultsPayload>("/api/results"),
  runs: () =>
    get<{ tests: { test_id: string; passes: number; fails: number; total: number; flip_rate: number }[] }>(
      "/api/runs",
    ),
};

/** Fetch once on mount, with the three states a caller actually has to draw. */
export function useAsync<T>(
  load: () => Promise<T>,
  deps: React.DependencyList = [],
): { data: T | null; error: ApiError | null; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  // The loader closes over the caller's deps, which is the intent here.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, deps);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    run()
      .then((value) => live && setData(value))
      .catch((err) => live && setError(err instanceof ApiError ? err : new ApiError(String(err), 0)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [run, nonce]);

  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}
