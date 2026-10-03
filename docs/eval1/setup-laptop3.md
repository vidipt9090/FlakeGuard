# Setup Notes – Laptop 3 (Person A)

## System Info

- **OS:** Windows 11
- **Python:** 3.12.6 (via `py` launcher)
- **Git:** 2.47.0.windows.1
- **GitHub CLI:** 2.102.0 (installed via `winget install GitHub.cli`)
- **CPU:** TODO (check Task Manager → Performance → CPU)
- **GPU:** TODO (check Task Manager → Performance → GPU)
- **RAM:** 16 GB
- **Free disk:** 135 GB

## Exact Commands Used

```powershell
# 1. Verify Python 3.12
py -3.12 --version

# 2. Create and activate virtual environment
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Install dev dependencies
pip install -e ".[dev]"

# 4. Verify tools work
ruff check .
pytest -q

# 5. Install GitHub CLI (run once as administrator or user)
winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements

# 6. Authenticate GitHub CLI
gh auth login

# 7. Clone repo (after remote is set)
git clone https://github.com/<OWNER>/flakeguard.git
cd flakeguard
```

## Notes

- If `Activate.ps1` is blocked by execution policy, run:
  `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`
- `gh auth login` will open a browser; choose HTTPS and paste the one-time code.
- After setup, run `ruff check . && pytest -q` before every commit.
