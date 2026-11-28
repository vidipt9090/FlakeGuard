import io, json, subprocess, sys, time, zipfile
from datetime import datetime, timezone
repo, sha = sys.argv[1], sys.argv[2]
def gh(*a):
    return subprocess.run(["gh", "api", *a], capture_output=True)
def now(): return datetime.now(timezone.utc).strftime("%H:%M:%S")
run_id = None
while True:
    if run_id is None:
        d = json.loads(gh(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=20").stdout)
        r = [x for x in d["workflow_runs"] if x["name"] == "spike-live"]
        if r: run_id = r[0]["id"]; print(now(), "run", run_id, flush=True)
        else: time.sleep(1); continue
    run = json.loads(gh(f"repos/{repo}/actions/runs/{run_id}").stdout)
    arts = json.loads(gh(f"repos/{repo}/actions/runs/{run_id}/artifacts").stdout)["artifacts"]
    if arts:
        a = arts[0]
        print(now(), f"artifact {a['name']} id={a['id']} listed; run status={run['status']}", flush=True)
        z = gh(f"repos/{repo}/actions/artifacts/{a['id']}/zip")
        run2 = json.loads(gh(f"repos/{repo}/actions/runs/{run_id}").stdout)
        if z.returncode == 0 and z.stdout:
            content = zipfile.ZipFile(io.BytesIO(z.stdout)).read("progress.json").decode()
            print(now(), f"DOWNLOADED {len(z.stdout)} bytes, content={content.strip()}; run status right after download: {run2['status']}", flush=True)
        else:
            print(now(), "DOWNLOAD FAILED:", z.stderr.decode()[:300], "; run status:", run2["status"], flush=True)
        break
    time.sleep(1)
