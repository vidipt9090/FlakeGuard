"""Poll one Actions run once a second and report how quickly job, step and artifact state becomes visible.

usage: python poll_run.py <repo> <workflow name> <head sha> <pushed_at_utc_iso>
Uses the gh credential (token read from `gh auth token`, never printed).
"""
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

repo, wf_name, sha, pushed = sys.argv[1:5]
token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
pushed_at = datetime.fromisoformat(pushed)


def api(path):
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r), dict(r.headers)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def now():
    return datetime.now(timezone.utc)


seen = {}  # key -> first time this exact state was observed
lags = []  # (what, state, github_ts, seen_ts, lag_s)
artifacts_seen = {}
calls = 0
run_id = None
t_start = now()
last_headers = {}
while True:
    if run_id is None:
        data, last_headers = api(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=20")
        calls += 1
        runs = [r for r in data["workflow_runs"] if r["name"] == wf_name]
        if runs:
            run_id = runs[0]["id"]
            t = now()
            print(f"run {run_id} first visible {(t - pushed_at).total_seconds():.1f} s after the push "
                  f"(run created_at {runs[0]['created_at']}) {runs[0]['html_url']}", flush=True)
        else:
            time.sleep(1)
            continue
    jobs, last_headers = api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")
    calls += 1
    t = now()
    for j in jobs["jobs"]:
        for what, status, conclusion, started, completed in (
            [(f"job '{j['name']}'", j["status"], j["conclusion"], j["started_at"], j["completed_at"])]
            + [(f"  step '{j['name']}' / {s['name']}", s["status"], s["conclusion"], s["started_at"], s["completed_at"]) for s in j.get("steps", [])]
        ):
            key = (what, status, conclusion)
            if key not in seen:
                seen[key] = t
                gh_ts = ts(completed) if status == "completed" else ts(started)
                lag = (t - gh_ts).total_seconds() if gh_ts else None
                lags.append((what, f"{status}/{conclusion}", gh_ts, t, lag))
                print(f"{t.strftime('%H:%M:%S')}  {what}: {status}" + (f" ({conclusion})" if conclusion else "")
                      + (f"   [GitHub timestamp {gh_ts.strftime('%H:%M:%S')}, seen {lag:+.1f} s later]" if lag is not None else ""), flush=True)
    arts, last_headers = api(f"repos/{repo}/actions/runs/{run_id}/artifacts")
    calls += 1
    for a in arts["artifacts"]:
        if a["name"] not in artifacts_seen:
            artifacts_seen[a["name"]] = t
            run_now, _ = api(f"repos/{repo}/actions/runs/{run_id}")
            calls += 1
            print(f"{t.strftime('%H:%M:%S')}  ARTIFACT '{a['name']}' visible (created_at {a['created_at']}, expired={a['expired']}); "
                  f"run status at that moment: {run_now['status']}", flush=True)
    done = all(j["status"] == "completed" for j in jobs["jobs"]) and jobs["jobs"]
    if done:
        run_final, _ = api(f"repos/{repo}/actions/runs/{run_id}")
        if run_final["status"] == "completed":
            break
    time.sleep(1)

print(f"\nrun finished: conclusion={run_final['conclusion']}  total {(now() - pushed_at).total_seconds():.0f} s after push; {calls} API calls")
print("rate limit headers on the last call:", {k: v for k, v in last_headers.items() if k.lower().startswith("x-ratelimit")})
l = [x[4] for x in lags if x[4] is not None and x[1].startswith(("in_progress", "completed"))]
print(f"observed lag (poll time minus GitHub's timestamp): min {min(l):.1f} s, median {sorted(l)[len(l)//2]:.1f} s, max {max(l):.1f} s over {len(l)} transitions")
