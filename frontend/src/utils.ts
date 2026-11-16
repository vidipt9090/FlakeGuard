/**
 * Utility helpers for GitHub URLs and repository resolution
 */

export function getActionsUrl(repo: string | undefined | null): string {
  if (!repo || repo === "synthetic" || repo === "demo" || repo.includes("flakeguard-demo")) {
    return "https://github.com/vidipt9090/FlakeGuard/actions";
  }
  const clean = repo.trim().replace(/\/$/, "");
  if (clean.startsWith("https://github.com/")) {
    return `${clean}/actions`;
  }
  if (clean.includes("/") && !clean.includes(":") && !clean.includes("\\")) {
    return `https://github.com/${clean}/actions`;
  }
  return "https://github.com/vidipt9090/FlakeGuard/actions";
}

export function getRepoUrl(repo: string | undefined | null): string {
  if (!repo || repo === "synthetic" || repo === "demo" || repo.includes("flakeguard-demo")) {
    return "https://github.com/vidipt9090/FlakeGuard";
  }
  const clean = repo.trim().replace(/\/$/, "");
  if (clean.startsWith("https://github.com/")) {
    return clean;
  }
  if (clean.includes("/") && !clean.includes(":") && !clean.includes("\\")) {
    return `https://github.com/${clean}`;
  }
  return "https://github.com/vidipt9090/FlakeGuard";
}

export function getPullsUrl(repo: string | undefined | null): string {
  const base = getRepoUrl(repo);
  return `${base}/pulls`;
}

